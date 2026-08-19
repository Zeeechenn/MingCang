"""Read-only Stage4 facade for M54/M68 news event risk.

This module exposes event-risk slots for product panels while keeping any
directional/news-weight experiment shadow-blocked behind separate statistical
and user-confirmation gates.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.data.models.news_shadow import NewsShadowRun

NEWS_EVENT_RISK_GOVERNANCE = {
    "owner_domain": "backend.data",
    "unique_consumer": "daily_panel.news_event_risk",
    "input_contract": "M68 NewsShadowRun rows plus optional M54 accrual/test2 summaries",
    "output_contract": "news_event_risk_facade.v1",
    "failure_mode": "missing M68 rows or M54 stats are explicit degradation flags",
    "degradation": "panel receives event cards only; direction weights stay blocked",
    "baseline": "legacy sentiment/news slots and M68 observe-only rows",
    "success_metric": "100% of event-risk cards expose event level, reasons, refs and blocked direction accounting",
    "minimum_sample": "30 event-risk observations before statistical gate discussion",
    "expiry_or_exit": "expires when M54/M68 are merged into a canonical evidence ledger",
    "rollback": "remove facade consumer; NewsShadowRun/M54 producers are unchanged",
    "replacement": "canonical news evidence ledger with independent promotion gate",
    "lifecycle": "shadow",
    "signal_impact": "none",
}


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def event_risk_card_from_row(row: Any) -> dict:
    """Normalize one M68 row/dict into a panel-safe event-risk card."""

    reasons = _loads(_row_get(row, "event_risk_reasons_json"), [])
    evidence = _loads(_row_get(row, "evidence_json"), {})
    degradation = _loads(_row_get(row, "degradation_flags_json"), [])
    attribution = _loads(_row_get(row, "attribution_json"), {})
    return {
        "symbol": _row_get(row, "symbol"),
        "as_of": _row_get(row, "as_of"),
        "run_id": _row_get(row, "run_id"),
        "profile": _row_get(row, "profile"),
        "status": _row_get(row, "status"),
        "event_risk_level": _row_get(row, "event_risk_level", "unavailable"),
        "event_risk_reasons": reasons if isinstance(reasons, list) else [],
        "would_change_action": bool(_row_get(row, "would_change_action", False)),
        "confidence": _row_get(row, "confidence"),
        "counterfactual_recommendation": _row_get(row, "counterfactual_recommendation"),
        "attribution": attribution if isinstance(attribution, dict) else {},
        "evidence_refs": evidence if isinstance(evidence, dict) else {},
        "degradation_flags": degradation if isinstance(degradation, list) else [],
        "panel_consumable": True,
        "direction_weight_impact": "blocked_shadow_only",
        "signal_impact": "none",
    }


def build_news_event_risk_facade(
    *,
    as_of: str,
    rows: list[Any] | None = None,
    m54_summary: dict | None = None,
    direction_experiment: dict | None = None,
) -> dict:
    """Build a read-only panel facade from already materialized M54/M68 facts."""

    cards = [event_risk_card_from_row(row) for row in (rows or [])]
    high_or_action = [
        card for card in cards
        if card["event_risk_level"] == "high" or card["would_change_action"]
    ]
    missing: list[str] = []
    if not cards:
        missing.append("missing_m68_event_rows")
    if not m54_summary:
        missing.append("missing_m54_accrual_summary")

    direction = direction_experiment or {}
    direction_gate = {
        "lifecycle": "shadow",
        "status": "blocked",
        "direction_weights_allowed": False,
        "promotion_requires": [
            "independent_statistical_gate",
            "leader_real_data_verdict",
            "explicit_user_confirmation",
        ],
        "m54_summary": m54_summary or {},
        "experiment_summary": direction,
        "reason": "event risk may inform panels; directional weights remain shadow-blocked",
        "signal_impact": "none",
    }

    return {
        "schema_version": "news_event_risk_facade.v1",
        "as_of": as_of,
        "status": "ready" if not missing else "degraded",
        "event_risk_cards": cards,
        "panel_payload": {
            "as_of": as_of,
            "total": len(cards),
            "attention_count": len(high_or_action),
            "attention": high_or_action,
        },
        "direction_experiment": direction_gate,
        "degradation_flags": missing,
        "read_only": True,
        "write_policy": "no_database_writes",
        "signal_impact": "none",
        "generated_at": _stamp(),
        "governance": dict(NEWS_EVENT_RISK_GOVERNANCE),
    }


def build_news_event_risk_from_db(
    db,
    *,
    as_of: str,
    symbol: str | None = None,
    limit: int = 20,
    m54_summary: dict | None = None,
    direction_experiment: dict | None = None,
) -> dict:
    """Read M68 rows and return the same facade; performs no writes."""

    query = db.query(NewsShadowRun).filter(NewsShadowRun.as_of == as_of)
    if symbol:
        query = query.filter(NewsShadowRun.symbol == symbol)
    rows = (
        query.order_by(
            NewsShadowRun.would_change_action.desc(),
            NewsShadowRun.event_risk_level.asc(),
            NewsShadowRun.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return build_news_event_risk_facade(
        as_of=as_of,
        rows=list(rows),
        m54_summary=m54_summary,
        direction_experiment=direction_experiment,
    )
