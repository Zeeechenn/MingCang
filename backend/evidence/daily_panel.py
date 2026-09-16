"""Stage5 canonical daily panel aggregation.

The builder is read-only and wraps existing owner-domain outputs into one
product-facing envelope.  It never synthesizes a successful batch: RunEnvelope
truth comes only from ``backend.ops.run_envelope.select_complete_daily_run``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from backend.data.news_event_risk import build_news_event_risk_from_db
from backend.evidence.daily_panel_sources import (
    EFFECTIVE_SINCE,
    apply_daily_sources,
    bind_daily_sources,
    previous_committed_panel,
)
from backend.evidence.run_card import build_run_card
from backend.notification.contract import evaluate_notification_contract
from backend.ops.run_envelope import select_complete_daily_run, stored_run_envelope_from_row
from backend.portfolio.daily_panel import build_panel as build_postmarket_panel

DAILY_PANEL_VERSION = "daily_panel.v1"
CARD_TYPES = (
    "batch_integrity",
    "candidate",
    "position_health",
    "event_risk",
    "watchtower",
    "daily_delta",
    "human_confirmation",
    "review_attribution",
)


class DailyPanelArtifactError(RuntimeError):
    """Raised when a scheduled panel artifact cannot be tied to one RunEnvelope."""


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_only(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:10]


def _summary_count(label: str, count: int, *, missing: bool = False) -> str:
    if missing:
        return f"{label} 缺失或不可用"
    return f"{label} {count} 项"


def _ref(source_type: str, source_ref: str | None, *, as_of: str | None = None, status: str | None = None) -> dict:
    return {
        "source_type": source_type,
        "source_ref": source_ref,
        "as_of": _date_only(as_of),
        "status": status,
    }


def _card(
    card_type: str,
    *,
    lifecycle: str,
    status: str,
    summary: str,
    payload: dict | None = None,
    evidence_refs: list[dict] | None = None,
    run_ref: dict | None = None,
    drilldown: dict | None = None,
) -> dict:
    return {
        "card_type": card_type,
        "lifecycle": lifecycle,
        "status": status,
        "summary": summary,
        "payload": payload or {},
        "evidence_refs": evidence_refs or [],
        "run_ref": run_ref,
        "drilldown": drilldown or {"kind": "none", "href": None, "label": "暂无可钻取入口"},
    }


def _run_ref(selection: dict[str, Any]) -> dict | None:
    envelope = selection.get("run_envelope")
    if not isinstance(envelope, dict):
        return None
    return {
        "run_id": envelope.get("run_id"),
        "batch_id": envelope.get("batch_id"),
        "as_of": _date_only(envelope.get("as_of")),
        "status": envelope.get("status"),
        "entrypoint": envelope.get("entrypoint"),
    }


def _build_postmarket_source(as_of: str | None, db_path: str | Path | None) -> tuple[dict | None, list[str]]:
    if db_path is None:
        return None, ["postmarket_panel_unavailable:no_file_sqlite_path"]
    try:
        return build_postmarket_panel(db_path=db_path, as_of=as_of), []
    except Exception as exc:  # noqa: BLE001 - product panel must degrade explicitly.
        return None, [f"postmarket_panel_unavailable:{exc.__class__.__name__}"]


def _sqlite_file_path_from_session(db) -> Path | None:
    try:
        url = db.get_bind().url
    except Exception:  # noqa: BLE001 - unknown injected session shape.
        return None
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    if str(database).startswith("file:"):
        path = str(database)[5:].split("?", 1)[0]
        return Path(unquote(path))
    return Path(database)


def _artifact_ref(path: Path) -> str:
    resolved = path.expanduser()
    try:
        return str(resolved.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved.resolve())
    except OSError:
        return str(resolved)


def _json_default(value: Any) -> str:
    return str(value)


def _date_key(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        parsed = _date_only(value)
        if parsed:
            return parsed
    return None


def _load_m63_queue_for_artifact() -> dict[str, Any]:
    from backend.workflows import m63_daily

    queue_path = m63_daily.DEFAULT_QUEUE_PATH
    if not queue_path.exists():
        return {
            "status": "unavailable",
            "reason": "m63_queue_missing",
            "source_path": str(queue_path),
            "items": [],
            "pending": [],
            "done": [],
        }
    queue = m63_daily.load_queue(queue_path)
    items = [item for item in queue if isinstance(item, dict)]
    return {
        "status": "available",
        "source_path": str(queue_path),
        "items": items,
        "pending": [item for item in items if item.get("status") != "done"],
        "done": [item for item in items if item.get("status") == "done"],
    }


def _queue_cohorts(queue_source: dict[str, Any], as_of: str) -> dict[str, Any]:
    if queue_source.get("status") != "available":
        return {"status": queue_source.get("status"), "reason": queue_source.get("reason")}
    raw_items = queue_source.get("items")
    items: list[Any] = raw_items if isinstance(raw_items, list) else []
    as_of_items: list[dict[str, Any]] = []
    created_on_day: list[dict[str, Any]] = []
    completed_on_day: list[dict[str, Any]] = []
    as_of_backlog: list[dict[str, Any]] = []
    future_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        created_day = _date_key(item, "created_at", "created_on", "date")
        done_day = _date_key(item, "done_at", "completed_at")
        if created_day and created_day > as_of:
            future_items.append(item)
            continue
        if done_day and done_day > as_of:
            if created_day and created_day <= as_of:
                as_of_items.append(item)
                if created_day == as_of:
                    created_on_day.append(item)
                as_of_backlog.append(item)
            else:
                future_items.append(item)
            continue
        as_of_items.append(item)
        if created_day == as_of:
            created_on_day.append(item)
            if item.get("status") == "done" and done_day == as_of:
                completed_on_day.append(item)
        if item.get("status") != "done":
            as_of_backlog.append(item)
    return {
        "status": "available",
        "source_path": queue_source.get("source_path"),
        "as_of_items": as_of_items,
        "created_on_day": created_on_day,
        "completed_on_day": completed_on_day,
        "as_of_backlog": as_of_backlog,
        "future_count": len(future_items),
        "historical_completed_count": sum(
            1
            for item in as_of_items
            if item.get("status") == "done"
            and (_date_key(item, "done_at", "completed_at") or as_of) < as_of
        ),
    }


def _card_by_type(payload: dict[str, Any], card_type: str) -> dict[str, Any]:
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return {}
    for card in cards:
        if isinstance(card, dict) and card.get("card_type") == card_type:
            return card
    return {}


def _metric_unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason}


def _build_work_metrics(
    *,
    db,
    row,
    payload: dict[str, Any],
    run_envelope: dict[str, Any],
    queue_source: dict[str, Any],
    as_of: str,
) -> dict[str, dict[str, Any]]:
    watchtower = _card_by_type(payload, "watchtower")
    raw_watch_payload = watchtower.get("payload")
    watch_payload: dict[str, Any] = raw_watch_payload if isinstance(raw_watch_payload, dict) else {}
    notification_contract = watch_payload.get("notification_contract") if isinstance(watch_payload, dict) else None
    if isinstance(notification_contract, dict):
        duplicate_suppression = {
            "status": "available",
            "evaluated": 1,
            "suppressed": 1 if notification_contract.get("would_suppress") else 0,
            "evidence": "shadow_contract_evaluation_only",
            "delivery_history_status": watch_payload.get("suppression_history_status") or "unknown",
        }
    else:
        duplicate_suppression = _metric_unavailable("notification_contract_missing")

    queue_cohorts = _queue_cohorts(queue_source, as_of)
    if queue_cohorts.get("status") == "available":
        raw_created_on_day = queue_cohorts.get("created_on_day")
        created_on_day: list[Any] = raw_created_on_day if isinstance(raw_created_on_day, list) else []
        raw_completed_on_day = queue_cohorts.get("completed_on_day")
        completed_on_day: list[Any] = (
            raw_completed_on_day
            if isinstance(raw_completed_on_day, list)
            else []
        )
        human_review = {
            "status": "available",
            "cohort": "created_on_day",
            "required": len(created_on_day),
            "completed": len(completed_on_day),
            "source": queue_source.get("source_path"),
            "excluded_future": queue_cohorts.get("future_count", 0),
            "excluded_historical_completed": queue_cohorts.get("historical_completed_count", 0),
        }
    else:
        human_review = _metric_unavailable(str(queue_source.get("reason") or "m63_queue_unavailable"))

    human_confirmation = _card_by_type(payload, "human_confirmation")
    if queue_cohorts.get("status") == "available":
        raw_backlog = queue_cohorts.get("as_of_backlog")
        backlog: list[Any] = raw_backlog if isinstance(raw_backlog, list) else []
        raw_human_payload = human_confirmation.get("payload")
        human_payload: dict[str, Any] = raw_human_payload if isinstance(raw_human_payload, dict) else {}
        raw_as_of_items = queue_cohorts.get("as_of_items")
        as_of_items: list[Any] = raw_as_of_items if isinstance(raw_as_of_items, list) else []
        review_freshness = {
            "status": "available",
            "cohort": "as_of_backlog",
            "total": len(backlog),
            "stale": int(human_payload.get("queue_stale_count") or 0),
            "source": queue_source.get("source_path"),
            "as_of_items": len(as_of_items),
            "excluded_future": queue_cohorts.get("future_count", 0),
        }
    else:
        review_freshness = _metric_unavailable(str(queue_source.get("reason") or "m63_queue_unavailable"))

    try:
        from backend.data.models.job import JobRun

        prior_rows = db.query(JobRun).filter(
            JobRun.job_name == row.job_name,
            JobRun.as_of == row.as_of,
            JobRun.id < row.id,
        ).order_by(JobRun.id.asc()).all()
        prior_failed = [
            prior
            for prior in prior_rows
            if prior.status in {"error", "degraded"}
            or (stored_run_envelope_from_row(prior) or {}).get("status") not in (None, "complete")
        ]
        failure_recovery = {
            "status": "available",
            "recovered": len(prior_failed),
            "open_failures": 0,
            "evidence": "same_day_prior_failed_or_degraded_m63_job_runs",
        }
    except Exception as exc:  # noqa: BLE001 - Stage6 artifact must not invent recovery.
        failure_recovery = _metric_unavailable(f"failure_recovery_query_failed:{exc.__class__.__name__}")

    price_basis_integrity = _build_price_basis_integrity(db, as_of=as_of)
    return {
        "duplicate_suppression": duplicate_suppression,
        "human_review": human_review,
        "review_freshness": review_freshness,
        "failure_recovery": failure_recovery,
        "price_basis_integrity": price_basis_integrity,
    }


def _build_price_basis_integrity(db, *, as_of: str) -> dict[str, Any]:
    """M69 follow-up: surface unresolved adjustment-basis drift as panel evidence.

    Before this the detector only ever wrote a log warning, and the 2026-09-02
    audit found ten consecutive days of warnings that nobody acted on while the
    affected symbols kept flowing into the official signal batch.  Publishing it
    as a work metric lets the continuity auditor gate the day on it.
    """
    import json as _json

    try:
        from sqlalchemy import func

        from backend.data.models.degradation import (
            AdjustmentBasisClearance,
            DegradationEvent,
        )
        from backend.data.price_quality import summarize_basis_drift_events

        rows = (
            db.query(DegradationEvent.context_json)
            .filter(
                DegradationEvent.category == "adjustment_basis_drift",
                func.date(DegradationEvent.ts) == as_of[:10],
            )
            .all()
        )
        payloads: list[dict[str, Any]] = []
        for (context_json,) in rows:
            if not context_json:
                continue
            try:
                parsed = _json.loads(context_json)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                payloads.append(parsed)
        # Clearances are keyed by the day they clear, not the day someone got
        # around to recording them, so a late acknowledgement still lands on the
        # right panel when that day is regenerated.
        cleared = [
            symbol
            for (symbol,) in db.query(AdjustmentBasisClearance.symbol)
            .filter(AdjustmentBasisClearance.event_date == as_of[:10])
            .all()
        ]
        return summarize_basis_drift_events(payloads, cleared)
    except Exception as exc:  # noqa: BLE001 - never let evidence collection break the panel.
        return _metric_unavailable(f"price_basis_query_failed:{exc.__class__.__name__}")


def _require_available_work_metrics(work_metrics: dict[str, dict[str, Any]]) -> None:
    for name, metric in work_metrics.items():
        if not isinstance(metric, dict) or metric.get("status") != "available":
            reason = metric.get("reason") if isinstance(metric, dict) else "missing"
            raise DailyPanelArtifactError(f"work_metric_unavailable:{name}:{reason}")


def mark_daily_panel_artifact_committed(path: str | Path, *, run_id: str) -> None:
    panel_path = Path(path)
    try:
        payload = json.loads(panel_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DailyPanelArtifactError(f"artifact_commit_mark_unreadable:{exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise DailyPanelArtifactError("artifact_commit_mark_not_object")
    contract = payload.get("artifact_contract")
    if not isinstance(contract, dict) or contract.get("source_job_run_id") != run_id:
        raise DailyPanelArtifactError("artifact_commit_mark_run_mismatch")
    if payload.get("ledger_commit_state") != "pending":
        raise DailyPanelArtifactError(f"artifact_commit_mark_bad_state:{payload.get('ledger_commit_state')}")
    payload["ledger_commit_state"] = "committed"
    payload["ledger_committed_at"] = _stamp()
    tmp_path = panel_path.with_name(f".{panel_path.name}.{run_id}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
            encoding="utf-8",
        )
        tmp_path.replace(panel_path)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise DailyPanelArtifactError(f"artifact_commit_mark_write_failed:{exc.__class__.__name__}") from exc


def _build_news_source(db, *, as_of: str | None) -> dict:
    as_of = _date_only(as_of)
    if not as_of or db is None:
        flags = ["missing_as_of"] if not as_of else ["news_event_risk_db_not_supplied"]
        return {
            "schema_version": "news_event_risk_facade.v1",
            "as_of": None,
            "status": "degraded",
            "event_risk_cards": [],
            "panel_payload": {"total": 0, "attention_count": 0, "attention": []},
            "direction_experiment": {
                "lifecycle": "shadow",
                "status": "blocked",
                "direction_weights_allowed": False,
                "promotion_requires": ["complete_run_envelope"],
                "signal_impact": "none",
            },
            "degradation_flags": flags,
        }
    try:
        return build_news_event_risk_from_db(db, as_of=as_of)
    except Exception as exc:  # noqa: BLE001 - facade is optional product evidence.
        return {
            "schema_version": "news_event_risk_facade.v1",
            "as_of": as_of,
            "status": "degraded",
            "event_risk_cards": [],
            "panel_payload": {"total": 0, "attention_count": 0, "attention": []},
            "direction_experiment": {
                "lifecycle": "shadow",
                "status": "blocked",
                "direction_weights_allowed": False,
                "promotion_requires": ["news_event_risk_query_success"],
                "signal_impact": "none",
            },
            "degradation_flags": [f"news_event_risk_unavailable:{exc.__class__.__name__}"],
        }


def _build_cards(
    *,
    mode: str,
    as_of: str | None,
    run_selection: dict[str, Any],
    postmarket: dict | None,
    source_flags: list[str],
    news_event_risk: dict,
    m63_report: dict | None,
    m63_queue: dict | None,
    discretion_cards: list[dict],
) -> list[dict]:
    as_of = _date_only(as_of)
    selected_run_ref = _run_ref(run_selection)
    run_verified = bool(selected_run_ref and run_selection.get("status") == "selected")
    raw_status = "ready" if run_verified else ("degraded" if postmarket else "missing")
    raw_evidence_status = "ready" if run_verified and postmarket else ("unverified" if postmarket else "missing")
    run_envelope = run_selection.get("run_envelope") if isinstance(run_selection.get("run_envelope"), dict) else None
    run_card = build_run_card(
        as_of=as_of or "",
        symbol=None,
        run_envelope=run_envelope,
        decision_run=None,
        evidence_cards=[
            _ref("postmarket_panel", "postmarket_panel.v1", as_of=as_of, status="ready" if postmarket else "missing"),
        ],
        pit_audit={"id": f"daily_panel:{as_of or 'unknown'}", "pit_ok": run_selection.get("status") == "selected"},
        trade_journal_ref=None,
        review_case_ref=None,
    )
    batch_status = run_selection.get("status")
    candidate_items = ((postmarket or {}).get("buy_candidates") or {}).get("items") or []
    position_items = ((postmarket or {}).get("position_health") or {}).get("items") or []
    risk_warnings = (postmarket or {}).get("risk_warnings") or {}
    event_risk_payload = news_event_risk.get("panel_payload") or {}
    watchtower_followups = (postmarket or {}).get("watchtower_followups") or {}
    watchtower_confirm = (postmarket or {}).get("watchtower_confirm") or {}
    notification_contract = evaluate_notification_contract(
        {
            "channel": "daily_panel",
            "symbol": "",
            "event_type": "watchtower",
            "dedupe_key": f"daily_panel:{as_of or 'unknown'}:watchtower",
        }
    )
    pending_queue = (m63_queue or {}).get("pending") or []
    queue_items = [item for item in pending_queue if isinstance(item, dict)]
    stale_queue_items = [
        item for item in queue_items
        if _date_only(item.get("created_at") or item.get("updated_at") or item.get("done_at")) not in (None, as_of)
    ]
    queue_status = "stale" if stale_queue_items else "ready"
    review_attribution = (postmarket or {}).get("review_attribution") or {}
    structured_delta = (postmarket or {}).get("daily_delta")
    if not isinstance(structured_delta, dict):
        structured_delta = None
    delta_ready = bool(structured_delta and structured_delta.get("current_as_of") and structured_delta.get("previous_as_of")
                       and structured_delta.get("status", "ready") in {"ready", "ready_zero"})
    bound_watch = bool(run_verified and watchtower_followups.get("run_id") == (selected_run_ref or {}).get("run_id")
                       and watchtower_followups.get("as_of") == as_of)
    watch_status = (watchtower_followups.get("status", "missing") if bound_watch else
                    ("degraded" if watchtower_followups.get("items") or not run_verified else "missing"))
    event_status = news_event_risk.get("status")
    event_not_applicable = bool(run_verified and as_of and as_of >= EFFECTIVE_SINCE
                                and event_status == "not_applicable" and news_event_risk.get("reason"))
    report_as_of = (m63_report or {}).get("as_of")
    report_stale = bool(_date_only(report_as_of) and as_of and _date_only(report_as_of) != as_of)
    enriched_discretion_cards = []
    for item in discretion_cards:
        item_as_of = item.get("as_of")
        enriched_discretion_cards.append({
            **item,
            "stale": bool(_date_only(item_as_of) and as_of and _date_only(item_as_of) != as_of),
            "panel_as_of": as_of,
        })
    stale_discretion_count = sum(1 for item in enriched_discretion_cards if item.get("stale"))
    daily_delta_payload = {
        "structured_delta": structured_delta,
        "reason": (structured_delta or {}).get("reason"),
        "m63_report": {
            "mode": (m63_report or {}).get("mode") or mode,
            "as_of": report_as_of,
            "available": bool(m63_report and m63_report.get("text")),
            "stale": report_stale,
        },
        "missing_reason": None if delta_ready else "missing_structured_current_vs_previous_delta",
    }

    return [
        _card(
            "batch_integrity",
            lifecycle="stable",
            status="ready" if batch_status == "selected" else ("blocked" if batch_status == "ambiguous" else "missing"),
            summary=(
                "已选中唯一完整 RunEnvelope"
                if batch_status == "selected"
                else f"未选中完整批次：{batch_status or 'missing'}"
            ),
            payload={
                "selector_status": batch_status,
                "candidate_count": run_selection.get("candidates", 0),
                "run_card": run_card,
                "source_flags": source_flags,
                "no_synthetic_batch": True,
            },
            evidence_refs=[_ref("run_envelope_selector", "select_complete_daily_run", as_of=as_of, status=batch_status)],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/health", "label": "查看运行健康"},
        ),
        _card(
            "candidate",
            lifecycle="stable",
            status=raw_status,
            summary=_summary_count("候选", len(candidate_items), missing=not postmarket),
            payload={
                "items": candidate_items,
                "vetoed_items": ((postmarket or {}).get("buy_candidates") or {}).get("vetoed_items") or [],
                "shadow_discretion_cards": enriched_discretion_cards,
                "stale_discretion_count": stale_discretion_count,
                "verification": "run_verified" if run_verified else "raw_unverified_missing_run_envelope",
            },
            evidence_refs=[_ref("postmarket_panel", "buy_candidates", as_of=as_of, status=raw_evidence_status)],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/pulse", "label": "打开今日裁决"},
        ),
        _card(
            "position_health",
            lifecycle="stable",
            status=raw_status,
            summary=_summary_count("持仓体检", len(position_items), missing=not postmarket),
            payload={
                "items": position_items,
                "risk_budget": risk_warnings.get("concentration") or {},
                "stop_loss_buffer": risk_warnings.get("stop_loss_buffer_ranking") or {},
            },
            evidence_refs=[_ref("postmarket_panel", "position_health", as_of=as_of, status=raw_evidence_status)],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/positions", "label": "查看持仓"},
        ),
        _card(
            "event_risk",
            lifecycle="shadow",
            status="not_applicable" if event_not_applicable else ("ready" if run_verified and event_status == "ready" else ("degraded" if event_status == "ready" else "missing")),
            summary=news_event_risk["reason"] if event_not_applicable else f"事件风险 {event_risk_payload.get('attention_count', 0)} 项需关注；方向权重 blocked",
            payload={
                **news_event_risk,
                "direction_weights": {
                    "lifecycle": "shadow",
                    "status": "blocked",
                    "reason": "requires independent statistical gate and explicit user confirmation",
                },
            },
            evidence_refs=[_ref("news_event_risk", "M68/M54 facade", as_of=as_of, status=news_event_risk.get("status") if run_verified else "unverified")],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/news-shadow", "label": "查看新闻试用"},
        ),
        _card(
            "watchtower",
            lifecycle="shadow",
            status=watch_status,
            summary=_summary_count("观察哨触发", len(watchtower_followups.get("items") or [])),
            payload={
                "followups": watchtower_followups,
                "reason": watchtower_followups.get("reason"),
                "confirm": watchtower_confirm,
                "notification_contract": notification_contract,
                "suppression_history_status": "missing",
                "degradation_reason": None if bound_watch else "notification history ledger not supplied; suppression coverage is not proven",
                "notification_scope": "scan evidence only; notification delivery and suppression are not certified",
            },
            evidence_refs=[_ref("watchtower", "job_run.daily_panel_sources" if bound_watch else "latest_watchtower_output", as_of=as_of, status=watch_status)],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/daily?tab=shadow", "label": "查看观察哨"},
        ),
        _card(
            "daily_delta",
            lifecycle="stable",
            status=(structured_delta or {}).get("status", "ready") if run_verified and delta_ready else ("degraded" if delta_ready else "missing"),
            summary=(structured_delta or {}).get("summary") or (structured_delta or {}).get("reason") or "缺少结构化 current-vs-previous delta",
            payload=daily_delta_payload,
            evidence_refs=[_ref("m63_report", "latest_report", as_of=report_as_of, status="stale" if report_stale else ("ready" if run_verified and m63_report else ("unverified" if m63_report else "missing")))],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/reports", "label": "查看报告"},
        ),
        _card(
            "human_confirmation",
            lifecycle="stable",
            status="degraded" if stale_queue_items else ("blocked" if pending_queue else ("ready" if run_verified else "degraded")),
            summary=_summary_count("需要人工确认", len(pending_queue)),
            payload={
                "pending_queue": pending_queue,
                "queue_stale_count": len(stale_queue_items),
                "queue_status": queue_status,
                "panel_as_of": as_of,
                "event_risk_attention": event_risk_payload.get("attention") or [],
                "watchtower_confirm": watchtower_confirm,
            },
            evidence_refs=[_ref("m63_queue", "research_queue", as_of=as_of, status=queue_status if run_verified else "unverified")],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/chat", "label": "进入研究副驾驶"},
        ),
        _card(
            "review_attribution",
            lifecycle="stable",
            status=raw_status,
            summary=review_attribution.get("note") or "复盘归因缺失",
            payload=review_attribution,
            evidence_refs=[_ref("review_attribution", "postmarket_panel.review_attribution", as_of=as_of, status=raw_evidence_status)],
            run_ref=selected_run_ref,
            drilldown={"kind": "route", "href": "/reports", "label": "查看复盘案卷"},
        ),
    ]


def build_daily_panel_payload(
    *,
    mode: str = "postmarket",
    as_of: str | None = None,
    run_selection: dict[str, Any] | None = None,
    postmarket_panel: dict | None = None,
    source_flags: list[str] | None = None,
    news_event_risk: dict | None = None,
    m63_report: dict | None = None,
    m63_queue: dict | None = None,
    discretion_cards: list[dict] | None = None,
) -> dict:
    """Wrap already-collected facts into the Stage5 daily_panel.v1 envelope."""

    selection = run_selection or {"status": "missing", "job_run": None, "candidates": 0}
    resolved_as_of = _date_only(as_of or selection.get("as_of") or (postmarket_panel or {}).get("header", {}).get("as_of"))
    news = news_event_risk or _build_news_source(None, as_of=resolved_as_of)
    cards = _build_cards(
        mode=mode,
        as_of=resolved_as_of,
        run_selection=selection,
        postmarket=postmarket_panel,
        source_flags=source_flags or [],
        news_event_risk=news,
        m63_report=m63_report,
        m63_queue=m63_queue,
        discretion_cards=discretion_cards or [],
    )
    if resolved_as_of and resolved_as_of >= EFFECTIVE_SINCE:
        for card in cards:
            card["product_group"] = ("运行控制" if card["card_type"] == "batch_integrity" else
                                     "治理闭环" if card["card_type"] in {"human_confirmation", "review_attribution"} else "决策证据")
    card_map = {card["card_type"]: card for card in cards}
    ordered_cards = [card_map[card_type] for card_type in CARD_TYPES]
    return {
        "schema_version": DAILY_PANEL_VERSION,
        "mode": mode,
        "as_of": resolved_as_of,
        "generated_at": _stamp(),
        "status": "ready" if selection.get("status") == "selected" else "degraded",
        "cards": ordered_cards,
        "lifecycle_visibility": {
            "stable": [card["card_type"] for card in ordered_cards if card["lifecycle"] == "stable"],
            "shadow": [card["card_type"] for card in ordered_cards if card["lifecycle"] == "shadow"],
            "dormant": [],
            "rejected": [],
        },
        "source_contract": {
            "no_synthetic_batch": True,
            "read_only": True,
            "owner_domain": "backend.evidence",
            "consumer": "frontend.features.daily",
        },
    }


def build_latest_daily_panel(
    db,
    *,
    mode: str = "postmarket",
    as_of: str | None = None,
    db_path: str | Path | None = None,
    m63_report: dict | None = None,
    m63_queue: dict | None = None,
    discretion_cards: list[dict] | None = None,
) -> dict:
    """Build the latest canonical daily panel from read-only sources."""

    selection = select_complete_daily_run(db, as_of=as_of)
    selected_as_of = _date_only(selection.get("as_of") or as_of)
    resolved_db_path = Path(db_path) if db_path is not None else _sqlite_file_path_from_session(db)
    postmarket, source_flags = _build_postmarket_source(selected_as_of, resolved_db_path)
    resolved_as_of = _date_only(selected_as_of or (postmarket or {}).get("header", {}).get("as_of"))
    news = _build_news_source(db, as_of=resolved_as_of)
    selected_row = selection.get("job_run")
    try:
        stored = json.loads(getattr(selected_row, "output_summary_json", None) or "{}")
    except (ValueError, TypeError):
        stored = {}
    postmarket, news = apply_daily_sources(postmarket, news, stored.get("daily_panel_sources"), selection.get("run_envelope") or {})
    return build_daily_panel_payload(
        mode=mode,
        as_of=resolved_as_of,
        run_selection=selection,
        postmarket_panel=postmarket,
        source_flags=source_flags,
        news_event_risk=news,
        m63_report=m63_report,
        m63_queue=m63_queue,
        discretion_cards=discretion_cards,
    )


def _close_confirmed_for(db, as_of: str) -> bool:
    """True when the database already holds price rows for the panel's trade date.

    A postmarket panel built before the close describes the previous session, so
    it must not be able to stand as the authoritative panel for the current day.
    """
    from sqlalchemy import text

    try:
        row = db.execute(
            text("SELECT 1 FROM prices WHERE substr(date, 1, 10) = :day LIMIT 1"),
            {"day": as_of},
        ).fetchone()
    except Exception:  # noqa: BLE001 - an unreadable prices table cannot confirm a close.
        return False
    return row is not None


def build_and_write_daily_panel_artifact_for_job_run(
    db,
    row,
    *,
    markdown_artifact_path: str | Path,
    workflow_result: dict | None = None,
) -> dict[str, Any]:
    """Persist a daily_panel.v1 artifact for one selected scheduler JobRun.

    This helper is intentionally row-bound: it first proves the just-finished
    JobRun is the unique selected complete RunEnvelope for its day, then writes
    a JSON artifact next to the Markdown report.  It never synthesizes a run.
    """

    envelope = stored_run_envelope_from_row(row)
    if envelope is None:
        raise DailyPanelArtifactError("missing_explicit_run_envelope")
    if envelope.get("status") != "complete":
        raise DailyPanelArtifactError(f"run_envelope_not_complete:{envelope.get('status') or 'unknown'}")
    as_of = _date_only(envelope.get("as_of") or row.as_of)
    if not as_of:
        raise DailyPanelArtifactError("missing_as_of")

    selection = select_complete_daily_run(db, as_of=as_of, job_names=(row.job_name,))
    if selection.get("status") != "selected":
        raise DailyPanelArtifactError(f"run_selection_{selection.get('status') or 'missing'}")
    selected_row = selection.get("job_run")
    if selected_row is None or getattr(selected_row, "run_id", None) != row.run_id:
        raise DailyPanelArtifactError("selected_run_mismatch")

    markdown_path = Path(markdown_artifact_path).expanduser()
    if not markdown_path.exists():
        raise DailyPanelArtifactError("missing_markdown_artifact")
    panel_path = markdown_path.with_name(f"{markdown_path.stem}.daily_panel.json")
    markdown_ref = _artifact_ref(markdown_path)
    panel_ref = _artifact_ref(panel_path)
    artifacts = list(dict.fromkeys([
        *[str(item) for item in (envelope.get("artifacts") or []) if item],
        markdown_ref,
        panel_ref,
    ]))
    close_confirmed = _close_confirmed_for(db, as_of)
    freshness = dict(envelope.get("freshness") or {})
    freshness["close_confirmed"] = close_confirmed
    final_envelope = {**envelope, "artifacts": artifacts, "freshness": freshness}
    selection["run_envelope"] = final_envelope

    queue_source = _load_m63_queue_for_artifact()
    queue_cohorts = _queue_cohorts(queue_source, as_of)
    panel_pending = queue_cohorts.get("as_of_backlog") if isinstance(queue_cohorts.get("as_of_backlog"), list) else []
    resolved_db_path = _sqlite_file_path_from_session(db)
    postmarket, source_flags = _build_postmarket_source(as_of, resolved_db_path)
    news = _build_news_source(db, as_of=as_of)
    sources = None
    if as_of >= EFFECTIVE_SINCE:
        previous, previous_reason = previous_committed_panel(db, as_of)
        sources = bind_daily_sources(envelope=final_envelope, workflow_result=workflow_result,
                                     postmarket=postmarket, previous=previous, no_previous_reason=previous_reason)
        postmarket, news = apply_daily_sources(postmarket, news, sources, final_envelope)
    payload = build_daily_panel_payload(
        mode="postmarket",
        as_of=as_of,
        run_selection=selection,
        postmarket_panel=postmarket,
        source_flags=source_flags,
        news_event_risk=news,
        m63_report={"mode": "postmarket", "as_of": as_of, "text": markdown_path.read_text(encoding="utf-8")},
        m63_queue={"pending": panel_pending, "done": queue_cohorts.get("completed_on_day") or []},
    )
    work_metrics = _build_work_metrics(
        db=db,
        row=row,
        payload=payload,
        run_envelope=final_envelope,
        queue_source=queue_source,
        as_of=as_of,
    )
    _require_available_work_metrics(work_metrics)
    artifact_payload = {
        **payload,
        "ledger_commit_state": "pending",
        "run_envelope": final_envelope,
        "work_metrics": work_metrics,
        "artifact_contract": {
            "schema_version": "daily_panel_artifact_contract.v1",
            "source_job_run_id": row.run_id,
            "markdown_artifact": markdown_ref,
            "panel_artifact": panel_ref,
            "no_synthetic_envelope": True,
            "close_confirmed": close_confirmed,
        },
    }
    panel_path.write_text(
        json.dumps(artifact_payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    output_summary = json.loads(row.output_summary_json or "{}")
    if not isinstance(output_summary, dict):
        output_summary = {}
    output_summary["run_envelope"] = final_envelope
    if sources is not None:
        output_summary["daily_panel_sources"] = sources
    row.output_summary_json = json.dumps(output_summary, ensure_ascii=False, default=_json_default, sort_keys=True)
    row.artifact_path = panel_ref
    return {
        "artifact_path": panel_path,
        "artifact_ref": panel_ref,
        "markdown_ref": markdown_ref,
        "run_envelope": final_envelope,
    }
