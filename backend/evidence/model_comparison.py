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
