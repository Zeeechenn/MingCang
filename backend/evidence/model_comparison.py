"""Offline matched-model simulation, using the existing cash NAV engine.

Caller-supplied provenance is auditable, not independently certified here. This
module neither calls models nor activates a trial, modifies a DB or repairs data.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from backend.backtest.nav_replay import (
    CorporateAction,
    DailyBar,
    ReplayConfig,
    ReplayCostModel,
    SignalIntent,
    run_nav_replay,
)

ZONE = ZoneInfo("Asia/Shanghai")


def content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _date(value: str) -> date:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("date must use YYYY-MM-DD")
    return result


def _instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(ZONE)


def _number(value: Any, *, minimum: float = 0) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError("expected finite numeric value")
    return float(value)


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _execution_inputs(bundle: dict) -> tuple[list[DailyBar], list[CorporateAction], list[str]]:
    """Reject incomplete price grids instead of letting stale marks appear current."""
    days = bundle["calendar"]
    symbols = bundle["universe"]
    if not days or days != sorted(set(days)):
        raise ValueError("calendar must be nonempty, unique and sorted")
    for day in days:
        _date(day)
    if (
        not symbols
        or len(symbols) != len(set(symbols))
        or any(not isinstance(s, str) or len(s) != 6 or not s.isdigit() for s in symbols)
    ):
        raise ValueError("invalid CN universe")
    if set(bundle["sectors"]) != set(symbols) or any(
        not _nonempty(v) for v in bundle["sectors"].values()
    ):
        raise ValueError("every symbol requires a sector")
    bars = [DailyBar(**row) for row in bundle["bars"]]
    expected = {(s, d) for s in symbols for d in days}
    if len(bars) != len(expected) or {(b.symbol, b.date) for b in bars} != expected:
        raise ValueError("incomplete or duplicate price grid; include explicit suspended bars")
    for bar in bars:
        for value in (bar.open, bar.high, bar.low, bar.close):
            if _number(value) <= 0:
                raise ValueError("raw price must be positive")
        _number(bar.volume)
        if type(bar.tradable) is not bool:
            raise ValueError("tradable must be boolean")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close, bar.low):
            raise ValueError("invalid OHLC bounds")
    actions = [CorporateAction(**row) for row in bundle["corporate_actions"]]
    for action in actions:
        if (action.symbol, action.date) not in expected:
            raise ValueError("corporate action outside execution grid")
        _number(action.cash_dividend_per_share)
        if _number(action.split_ratio) <= 0:
            raise ValueError("invalid split ratio")
    if len({(a.symbol, a.date) for a in actions}) != len(actions):
        raise ValueError("duplicate corporate action")
    provenance = bundle.get("provenance", {})
    blockers = []
    for name, required in (("price_basis", "raw"), ("volume_unit", "shares"), ("currency", "CNY")):
        if provenance.get(name) != required:
            blockers.append(f"{name}_not_verified")
    for name in ("price_source", "calendar_source", "corporate_action_source", "reviewed_by"):
        if not _nonempty(provenance.get(name)):
            blockers.append(f"{name}_missing")
    for name in ("calendar", "bars", "corporate_actions", "sectors"):
        if provenance.get(name + "_sha256") != content_hash(bundle[name]):
            blockers.append(f"{name}_hash_mismatch")
    if provenance.get("action_coverage") != {
        s: {"start": days[0], "end": days[-1]} for s in symbols
    }:
        blockers.append("corporate_action_coverage_incomplete")
    # An empty action list needs the same positive coverage evidence as a nonempty one.
    if not _sha(provenance.get("source_receipt_sha256")):
        blockers.append("source_receipt_missing")
    return bars, actions, blockers


def _decision_signals(
    attempt: dict,
    *,
    as_of: str,
    cutoff: datetime,
    symbols: list[str],
    model: str,
    days: list[str],
    report_at: datetime,
) -> tuple[list[SignalIntent], dict]:
    if attempt.get("resolved_model") != model:
        raise ValueError("resolved_model_mismatch")
    for name in ("request_sha256", "response_sha256", "receipt_sha256"):
        if not _sha(attempt.get(name)):
            raise ValueError(f"{name}_missing")
    answer = attempt["answer"]
    if not isinstance(answer, dict):
        raise ValueError("invalid_answer_object")
    if content_hash(answer) != attempt.get("answer_sha256"):
        raise ValueError("answer_hash_mismatch")
    completed = _instant(attempt["completed_at"])
    if not cutoff <= completed <= report_at:
        raise ValueError("decision_timestamp_outside_window")
    if answer.get("as_of") != as_of:
        raise ValueError("answer_date_mismatch")
    decisions = answer["decisions"]
    if not isinstance(decisions, list) or any(not isinstance(d, dict) for d in decisions):
        raise ValueError("invalid_decision_list")
    if len(decisions) != len(symbols) or {d["symbol"] for d in decisions} != set(symbols):
        raise ValueError("decision_universe_mismatch")
    # Use completion, not request/as_of date. A delayed answer cannot trade an earlier open.
    future_opens = [d for d in days if datetime.combine(_date(d), time(9, 30), ZONE) > completed]
    next_open = future_opens[0] if future_opens else None
    # Existing engine queues at the previous close. This internal scheduling key is
    # never exposed as the actual decision timestamp and never rewrites a stored signal.
    anchor = days[days.index(next_open) - 1] if next_open and days.index(next_open) else None
    if next_open and anchor is None:
        raise ValueError("missing_pre_execution_anchor")
    signals = []
    for d in decisions:
        score = _number(d["score"], minimum=-100)
        action = d["action"]
        if score > 100 or not (
            (action == "buy" and score > 0)
            or (action == "hold" and score == 0)
            or (action == "sell" and score < 0)
        ):
            raise ValueError("action_score_mismatch")
        if any(not _nonempty(d.get(k)) for k in ("reason", "risk")):
            raise ValueError("decision_explanation_missing")
        refs = d.get("evidence_refs")
        allowed = {f"{kind}:{s}" for kind in ("source", "desk") for s in symbols}
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(r, str) or r not in allowed for r in refs)
        ):
            raise ValueError("decision_evidence_missing")
        if anchor is not None:
            signals.append(SignalIntent(d["symbol"], anchor, score))
    return signals, {
        "completed_at": completed.isoformat(),
        "eligible_open": next_open,
        "engine_queue_date": anchor,
        "pending_future_open": next_open is None,
    }


def build_model_comparison_report(bundle: dict) -> dict:
    """Evaluate an explicit immutable input bundle; never certify source truth or alpha.

    Scheduled missing/failed attempts stay in the denominator. Valid arms continue
    independently. Unknown subscription billing blocks total-net-return claims,
    but does not erase an otherwise attributable diagnostic decision.
    """
    if bundle.get("schema_version") != "matched_model_replay.v1":
        raise ValueError("unsupported comparison schema")
    report_at = _instant(bundle["report_at"])
    bars, actions, blockers = _execution_inputs(bundle)
    days, symbols = bundle["calendar"], bundle["universe"]
    if datetime.combine(_date(days[-1]), time(15), ZONE) > report_at:
        raise ValueError("unclosed or future execution bar")
    models = bundle["models"]
    if (
        len(models) != 2
        or len(set(models.values())) != 2
        or any(not _nonempty(v) for v in models.values())
    ):
        raise ValueError("exactly two distinct resolved models required")
    config = ReplayConfig(**bundle["execution_config"])
    costs = ReplayCostModel(**bundle["cost_model"])
    # Fixed action semantics: all positive buys qualify; hold cannot create entry.
    if not 0 < config.entry_threshold <= 0.000001 or config.reversal_threshold != 0:
        raise ValueError("configuration does not preserve buy/hold/sell semantics")
    for value in asdict(config).values():
        if value is not None:
            _number(value)
    if config.initial_cash <= 0 or any(
        type(getattr(config, k)) is not int or getattr(config, k) < 1
        for k in ("lot_size", "entry_ttl_sessions", "max_positions")
    ):
        raise ValueError("invalid account configuration")
    if (
        not 0
        < config.target_position_weight
        <= config.max_sector_weight
        <= config.max_total_weight
        <= 1
    ):
        raise ValueError("invalid portfolio weight limits")
    for name, value in asdict(costs).items():
        if name != "version":
            _number(value)
    sessions = bundle["sessions"]
    scheduled = bundle["scheduled_sessions"]
    if not scheduled or scheduled != sorted(set(scheduled)) or len(scheduled) > 60:
        raise ValueError("invalid fixed scheduled denominator")
    if len({s["session_id"] for s in sessions}) != len(sessions) or any(
        s["session_id"] not in scheduled for s in sessions
    ):
        raise ValueError("duplicate or unscheduled session")
    by_id = {s["session_id"]: s for s in sessions}
    arm_signals: dict[str, list[SignalIntent]] = {a: [] for a in models}
    attempts: dict[str, list[dict]] = {a: [] for a in models}
    billing: dict[str, list[float | None]] = {a: [] for a in models}
    anchors: dict[str, set[str]] = {a: set() for a in models}
    for session_id in scheduled:
        _date(session_id)
        if _date(session_id) > report_at.date():
            raise ValueError("scheduled denominator contains future session")
        session = by_id.get(session_id)
        if session is None:
            for arm in models:
                attempts[arm].append({"session_id": session_id, "status": "missing"})
                billing[arm].append(None)
            continue
        cutoff = _instant(session["cutoff"])
        as_of = session["as_of"]
        if cutoff.date().isoformat() != session_id or cutoff > report_at:
            raise ValueError("session cutoff mismatch")
        if as_of not in days or datetime.combine(_date(as_of), time(15), ZONE) > cutoff:
            raise ValueError("input close unavailable at cutoff")
        if not _sha(session.get("shared_input_sha256")) or set(session["arms"]) - set(models):
            raise ValueError("invalid shared input or unexpected arm")
        for arm, model in models.items():
            attempt = session["arms"].get(arm)
            row = {"session_id": session_id, "status": "missing"}
            cost = None
            if attempt is not None:
                supplied_cost = attempt.get("billed_cost_cny")
                if supplied_cost is not None:
                    cost = _number(supplied_cost)
                    if not _sha(attempt.get("billing_receipt_sha256")):
                        raise ValueError("billed cost needs a receipt")
                status = attempt.get("status")
                row["status"] = status
                if status not in ("recorded", "failed", "not_invoked"):
                    raise ValueError("invalid attempt status")
                if status == "recorded":
                    try:
                        if attempt.get("shared_input_sha256") != session["shared_input_sha256"]:
                            raise ValueError("shared_input_mismatch")
                        signals, timing = _decision_signals(
                            attempt,
                            as_of=as_of,
                            cutoff=cutoff,
                            symbols=symbols,
                            model=model,
                            days=days,
                            report_at=report_at,
                        )
                        anchor = timing["engine_queue_date"]
                        if anchor is not None and anchor in anchors[arm]:
                            raise ValueError("multiple_decisions_for_same_open")
                        if any(s.score > 0 and s.score < config.entry_threshold for s in signals):
                            raise ValueError("buy_score_below_execution_threshold")
                        if anchor is not None:
                            anchors[arm].add(anchor)
                        arm_signals[arm].extend(signals)
                        row.update(timing)
                    except (ValueError, KeyError, TypeError) as exc:
                        row.update(status="invalid", error=str(exc))
            attempts[arm].append(row)
            billing[arm].append(cost)
    result: dict[str, Any] = {
        "schema_version": "matched_model_report.v1",
        "input_sha256": content_hash(bundle),
        "status": "blocked" if blockers else "diagnostic_simulation",
        "certifies_returns": False,
        "economic_trial_activated": False,
        "source_truth_independently_verified": False,
        "execution_blockers": blockers,
        "scheduled_sessions": scheduled,
        "scheduled_count": len(scheduled),
        "paired_decisions": sum(
            all(attempts[a][i]["status"] == "recorded" for a in models)
            for i in range(len(scheduled))
        ),
        "arms": {},
        "comparison": None,
    }
    for arm in models:
        valid = sum(r["status"] == "recorded" for r in attempts[arm])
        result["arms"][arm] = {
            "requested_model": models[arm],
            "attempts": attempts[arm],
            "valid_decisions": valid,
            "failure_or_missing_rate": (len(scheduled) - valid) / len(scheduled),
            "known_billed_cost_cny": sum(c for c in billing[arm] if c is not None),
            "billing_complete": all(c is not None for c in billing[arm]),
            "replay": None,
            "return_after_model_billing_pct": None,
        }
        if not blockers:
            replay = run_nav_replay(
                arm_signals[arm],
                bars,
                corporate_actions=actions,
                sectors=bundle["sectors"],
                config=config,
                costs=costs,
            )
            result["arms"][arm]["replay"] = replay
            notional = sum(f["notional"] for f in replay["fills"])
            result["arms"][arm]["gross_turnover_over_initial_nav"] = notional / config.initial_cash
            if result["arms"][arm]["billing_complete"]:
                result["arms"][arm]["return_after_model_billing_pct"] = (
                    (replay["summary"]["ending_nav"] - result["arms"][arm]["known_billed_cost_cny"])
                    / config.initial_cash
                    - 1
                ) * 100
    if not blockers:
        left, right = models
        lhs, rhs = result["arms"][left], result["arms"][right]
        result["comparison"] = {
            "left_arm": left,
            "right_arm": right,
            "trading_net_return_difference_pp": lhs["replay"]["summary"]["total_return_pct"]
            - rhs["replay"]["summary"]["total_return_pct"],
            "total_net_return_difference_pp": (
                lhs["return_after_model_billing_pct"] - rhs["return_after_model_billing_pct"]
                if lhs["billing_complete"] and rhs["billing_complete"]
                else None
            ),
            "cash_baseline_return_pct": 0.0,
            "conclusion": "diagnostic_only_no_alpha_claim",
        }
    return result


def build_model_account_context(bundle: dict, *, arm: str, cutoff: str) -> dict:
    """Return only one arm's closed-session account and visible own decisions.

    Future prices/actions/answers are excluded before replay. Source authenticity
    and original PIT availability remain independent prerequisites, not inferred.
    """
    import copy

    instant = _instant(cutoff)
    if arm not in bundle["models"]:
        raise ValueError("unknown arm")
    if instant > _instant(bundle["report_at"]):
        raise ValueError("account cutoff exceeds supplied report horizon")
    _, _, blockers = _execution_inputs(bundle)
    if blockers:
        raise ValueError("account blocked: " + ",".join(blockers))
    visible = copy.deepcopy(bundle)
    visible["report_at"] = instant.isoformat()
    visible["calendar"] = [
        d for d in bundle["calendar"] if datetime.combine(_date(d), time(15), ZONE) <= instant
    ]
    if not visible["calendar"]:
        raise ValueError("no closed-session account at cutoff")
    days = visible["calendar"]
    visible["bars"] = [b for b in visible["bars"] if b["date"] in days]
    visible["corporate_actions"] = [a for a in visible["corporate_actions"] if a["date"] in days]
    visible["scheduled_sessions"] = [
        d for d in visible["scheduled_sessions"] if _date(d) <= instant.date()
    ]
    visible["sessions"] = [s for s in visible["sessions"] if _instant(s["cutoff"]) <= instant]
    for session in visible["sessions"]:
        # Other-arm response bodies are not needed for this context.
        own = session["arms"].get(arm)
        session["arms"] = {}
        if own is not None and (
            own.get("status") != "recorded" or _instant(own["completed_at"]) <= instant
        ):
            session["arms"][arm] = own
    for name in ("calendar", "bars", "corporate_actions", "sectors"):
        visible["provenance"][name + "_sha256"] = content_hash(visible[name])
    visible["provenance"]["action_coverage"] = {
        s: {"start": days[0], "end": days[-1]} for s in visible["universe"]
    }
    report = build_model_comparison_report(visible)
    result = report["arms"][arm]
    replay = result["replay"]
    if replay is None:
        raise ValueError("account replay blocked")
    valid_ids = {row["session_id"] for row in result["attempts"] if row["status"] == "recorded"}
    history = [
        {
            "session_id": s["session_id"],
            "completed_at": s["arms"][arm]["completed_at"],
            "answer": s["arms"][arm]["answer"],
        }
        for s in visible["sessions"]
        if s["session_id"] in valid_ids
    ]
    last = replay["equity_curve"][-1]
    return {
        "schema_version": "matched_model_account.v1",
        "arm_id": arm,
        "account_id": arm + "-synthetic",
        "cutoff": instant.isoformat(),
        "valuation_as_of": last["date"],
        "initial_cash": replay["config"]["initial_cash"],
        "cash": last["cash"],
        "market_value": last["market_value"],
        "nav": last["nav"],
        "holdings": replay["open_positions"],
        "own_fills": replay["fills"],
        "own_prior_decisions": sorted(history, key=lambda h: (h["completed_at"], h["session_id"])),
        "visible_replay_input_sha256": report["input_sha256"],
        "status": "diagnostic_closed_session_account",
        "certifies_returns": False,
        "limits": [
            "Not a real account; cash excludes model billing.",
            "No intraday fill/valuation claim; replay ends at the last closed session.",
            "PIT/source authenticity and prospective activation require separate review.",
        ],
    }


def build_model_trial_request_context(bundle: dict, *, arm: str, cutoff: str) -> dict:
    """Prepare one arm's prior account fields for a separately registered runner.

    This is an offline proposal. The caller must independently review source
    receipts and register an execution version before using it in a model call.
    """
    context = build_model_account_context(bundle, arm=arm, cutoff=cutoff)
    return {
        "schema_version": "matched_model_request_context.v1",
        "status": "diagnostic_request_context_execution_blocked",
        "economic_trial_activated": False,
        "arm_id": arm,
        "account_context_sha256": content_hash(context),
        "visible_replay_input_sha256": context["visible_replay_input_sha256"],
        "account": {
            "account_id": context["account_id"],
            "initial_cash": context["initial_cash"],
            "cash": context["cash"],
            "holdings": context["holdings"],
            "market_value": context["market_value"],
            "nav": context["nav"],
            "valuation_as_of": context["valuation_as_of"],
            "prior_fills": len(context["own_fills"]),
            "status": context["status"],
        },
        "own_prior_decisions": context["own_prior_decisions"],
        "own_fills": context["own_fills"],
        "risk": bundle["execution_config"],
        "costs": bundle["cost_model"],
        "cutoff": context["cutoff"],
        "limits": context["limits"],
    }


def _candidate_shared_symbols(shared_input: dict) -> list[str]:
    allowed = {
        "as_of", "cutoff", "symbols", "common", "desk", "gaps", "limitations",
        "source_snapshot_sha256", "official_batch", "official_run_id",
    }
    if set(shared_input) - allowed:
        raise ValueError("v3 shared input contains unreviewed top-level fields")
    forbidden = {
        "account", "accounts", "holdings", "own_prior_decisions", "own_fills",
        "opponent", "other_arm", "outcomes", "positions", "broker_credentials",
        "private_notes", "decision", "decisions", "model_response",
    }

    def check(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("v3 shared input has non-string field")
                if key.lower() in forbidden:
                    if path == ("common",) and key == "holdings" and item == "synthetic account supplied separately":
                        continue
                    raise ValueError("v3 shared input contains account or cross-arm fields")
                check(item, (*path, key))
        elif isinstance(value, list):
            for item in value:
                check(item, path)

    check(shared_input)
    if "symbols" in shared_input:
        symbols = shared_input["symbols"]
    else:
        stocks = shared_input.get("desk", {}).get("stocks")
        if not isinstance(stocks, list) or any(not isinstance(s, dict) for s in stocks):
            raise ValueError("v3 shared input lacks a stock universe")
        symbols = [s.get("symbol") for s in stocks]
    if (
        not isinstance(symbols, list)
        or any(not isinstance(s, str) or len(s) != 6 or not s.isdigit() for s in symbols)
        or len(symbols) != len(set(symbols))
    ):
        raise ValueError("v3 shared input has duplicate stock symbols")
    return symbols


def assemble_candidate_v3_request(
    bundle: dict,
    *,
    arm: str,
    session_id: str,
    cutoff: str,
    shared_input: dict,
    protocol: dict,
    authorization: dict,
    registration: dict,
    ledger: dict,
    source_review: dict,
) -> dict:
    """Gate a versioned, offline candidate request before any reservation or call.

    The review and ledger objects are caller-supplied evidence, not independent
    proof. The returned payload is only for an injected fake provider until a
    separate version and source/transport acceptance activates real calls.
    """
    if (
        registration.get("schema_version") != "matched_model_candidate_registration.v3"
        or registration.get("status") != "prepared_not_activated"
        or registration.get("execution_mode") != "injected_fake_only"
        or registration.get("parent_protocol_sha256") != content_hash(protocol)
        or registration.get("authorization_sha256") != content_hash(authorization)
        or not _sha(registration.get("v2_registration_sha256"))
        or registration.get("maximum_total_sessions") != protocol.get("maximum_sessions")
        or registration.get("same_budget_and_ledger_root") is not True
    ):
        raise ValueError("v3 registration, parent protocol or shared budget mismatch")
    if (
        authorization.get("authorized") is not True
        or "real account" not in authorization["scope"]["excluded"]
        or "real holdings" not in authorization["scope"]["excluded"]
        or arm not in protocol["models"]
        or bundle["models"] != protocol["models"]
        or len(authorization["scope"]["symbols"])
        != len(set(authorization["scope"]["symbols"]))
        or len(bundle["universe"]) != len(authorization["scope"]["symbols"])
        or set(bundle["universe"]) != set(authorization["scope"]["symbols"])
        or bundle["execution_config"] != protocol["execution_config"]
        or bundle["cost_model"] != protocol["cost_model"]
        or protocol["initial_cash_per_arm"] != bundle["execution_config"]["initial_cash"]
    ):
        raise ValueError("v3 authorization, account, risk or cost scope mismatch")
    instant = _instant(cutoff)
    if (
        _date(session_id) != instant.date()
        or instant.weekday() > 4
        or (instant.hour, instant.minute) < (23, 0)
        or session_id in {s["session_id"] for s in bundle["sessions"]}
        or session_id > protocol["expires_at"]
    ):
        raise ValueError("v3 session cutoff, expiry or retry mismatch")
    if (
        ledger.get("root") != registration.get("ledger_root")
        or not _nonempty(ledger.get("root"))
        or ledger.get("maximum_sessions") != protocol["maximum_sessions"]
        or ledger.get("reserved_session_ids") != sorted(set(ledger["reserved_session_ids"]))
        or session_id in ledger["reserved_session_ids"]
        or len(ledger["reserved_session_ids"]) >= protocol["maximum_sessions"]
    ):
        raise ValueError("v3 shared ledger capacity or no-retry check failed")
    last_closed = [
        day for day in bundle["calendar"]
        if datetime.combine(_date(day), time(15), ZONE) <= instant
    ]
    if (
        not last_closed
        or shared_input.get("as_of") != last_closed[-1]
        or shared_input.get("as_of") != session_id
    ):
        raise ValueError("v3 input is not the latest closed session")
    if (
        _instant(shared_input["cutoff"]) > instant
        or _instant(shared_input["cutoff"])
        < datetime.combine(_date(shared_input["as_of"]), time(15), ZONE)
        or _candidate_shared_symbols(shared_input) != bundle["universe"]
    ):
        raise ValueError("v3 shared input cutoff or universe mismatch")
    context = build_model_account_context(bundle, arm=arm, cutoff=cutoff)
    proposal = build_model_trial_request_context(bundle, arm=arm, cutoff=cutoff)
    if (
        context["arm_id"] != arm
        or context["account_id"] != registration["account_ids"][arm]
        or context["valuation_as_of"] != shared_input["as_of"]
        or context["cutoff"] != instant.isoformat()
        or proposal["status"] != "diagnostic_request_context_execution_blocked"
        or proposal["account_context_sha256"] != content_hash(context)
        or proposal["visible_replay_input_sha256"] != context["visible_replay_input_sha256"]
    ):
        raise ValueError("v3 arm account or visible context mismatch")
    if (
        source_review.get("status") != "candidate_source_reviewed"
        or not _nonempty(source_review.get("reviewed_by"))
        or source_review.get("bundle_sha256") != content_hash(bundle)
        or source_review.get("provenance_sha256") != content_hash(bundle["provenance"])
        or source_review.get("source_receipt_sha256") != bundle["provenance"]["source_receipt_sha256"]
        or source_review.get("shared_input_sha256") != content_hash(shared_input)
        or source_review.get("account_context_sha256") != content_hash(context)
    ):
        raise ValueError("v3 source or account context review hash mismatch")
    if any(
        _instant(item["completed_at"]) >= instant or item["session_id"] >= session_id
        for item in context["own_prior_decisions"]
    ) or any(fill["date"] > shared_input["as_of"] for fill in context["own_fills"]):
        raise ValueError("v3 future or current-session account history")
    # Reconstruct a fresh envelope; the blocked diagnostic object itself is never sent.
    return {
        "schema_version": "matched_model_candidate_request.v3",
        "candidate_status": "prepared_not_activated",
        "session_id": session_id,
        "arm_id": arm,
        "account_id": context["account_id"],
        "requested_model": protocol["models"][arm],
        "cutoff": instant.isoformat(),
        "shared": shared_input,
        "shared_input_sha256": content_hash(shared_input),
        "account": proposal["account"],
        "own_prior_decisions": proposal["own_prior_decisions"],
        "own_fills": proposal["own_fills"],
        "account_context_sha256": content_hash(context),
        "visible_replay_input_sha256": context["visible_replay_input_sha256"],
        "risk": protocol["execution_config"],
        "costs": protocol["cost_model"],
        "economic_trial_activated": False,
    }


def run_candidate_v3_offline(
    bundle: dict,
    *,
    reserve: Any,
    provider: Any,
    **candidate_inputs: Any,
) -> dict:
    """Consume the gated request once through injected offline fakes only."""
    if getattr(reserve, "offline_fake", False) is not True or getattr(
        provider, "offline_fake", False
    ) is not True:
        raise ValueError("v3 requires explicitly marked offline fake adapters")
    request = assemble_candidate_v3_request(bundle, **candidate_inputs)
    request_bytes = json.dumps(
        request, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
    reservation = reserve(request["session_id"], request["arm_id"])
    if not isinstance(reservation, dict) or reservation.get("status") != "fake_reserved":
        raise ValueError("v3 offline fake reservation failed")
    response = provider(request_bytes)
    return {
        "schema_version": "matched_model_candidate_run.v3",
        "status": "offline_fake_consumed_not_activated",
        "request_sha256": request_sha256,
        "reservation": reservation,
        "response": response,
        "provider_receipt_validated": False,
        "billing_validated": False,
        "economic_trial_activated": False,
    }
