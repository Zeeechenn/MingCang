"""Read-only global market data facade for M41.

This module does not fetch remote providers by itself, write the database, or
promote any HK/US dataset into StockSage scoring. It turns existing DB rows,
capability metadata, and explicit probe summaries into auditable envelopes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc

from backend.data.database import Price
from backend.data.external_sources import summarize_probe_results
from backend.data.market_capabilities import CAPABILITY_LAYERS, build_market_capability_catalog
from backend.data.price_quality import (
    DEFAULT_PRICE_QUALITY_POLICY,
    evaluate_price_quality,
    not_applicable_price_quality_gate,
)
from backend.decision.market_policy import (
    is_production_signal_market,
    production_signal_policy_payload,
)

SUPPORTED_MARKETS = {"CN", "HK", "US"}
INTENT_TO_LAYER = {
    "quote": "quote",
    "latest_quote": "quote",
    "kline": "kline",
    "daily_ohlcv": "kline",
    "fundamentals": "fundamentals",
    "financial_metrics": "fundamentals",
    "capital_flow": "capital_flow",
    "capital_and_liquidity": "capital_flow",
    "derivatives": "derivatives",
    "options": "derivatives",
    "options_or_related_instruments": "derivatives",
    "filings": "filings",
    "regulatory_filings": "filings",
    "tools_fallback": "tools_fallback",
    "symbol_calendar_provider_health": "tools_fallback",
}

MARKET_METADATA = {
    "CN": {"currency": "CNY", "timezone": "Asia/Shanghai", "symbol_namespace": "A-share local code"},
    "HK": {"currency": "HKD", "timezone": "Asia/Hong_Kong", "symbol_namespace": "HK numeric code"},
    "US": {"currency": "USD", "timezone": "America/New_York", "symbol_namespace": "US exchange ticker"},
}

CANONICAL_SCHEMAS: dict[str, dict[str, Any]] = {
    "quote": {
        "required_fields": ["symbol", "price", "volume", "as_of", "source", "fetched_at"],
        "pit_date_field": "as_of",
        "decision_visibility_rule": "as_of must be <= decision date",
    },
    "kline": {
        "required_fields": ["symbol", "date", "open", "high", "low", "close", "volume", "source", "fetched_at"],
        "pit_date_field": "date",
        "decision_visibility_rule": "bar date must be <= decision date",
    },
    "fundamentals": {
        "required_fields": [
            "symbol",
            "report_date",
            "disclosure_date",
            "currency",
            "source",
            "fetched_at",
        ],
        "pit_date_field": "disclosure_date",
        "decision_visibility_rule": "disclosure_date must be known and <= decision date",
    },
    "capital_flow": {
        "required_fields": ["symbol", "trade_date", "metric", "value", "currency", "source", "fetched_at"],
        "pit_date_field": "trade_date",
        "decision_visibility_rule": "trade_date must be <= decision date and metric definition must be stable",
    },
    "derivatives": {
        "required_fields": ["symbol", "contract", "expiry", "strike", "currency", "source", "fetched_at"],
        "pit_date_field": "fetched_at",
        "decision_visibility_rule": "chain snapshot timestamp must be preserved",
    },
    "filings": {
        "required_fields": ["symbol", "published_at", "title", "url", "source", "fetched_at"],
        "pit_date_field": "published_at",
        "decision_visibility_rule": "published_at must be known and <= decision date",
    },
    "tools_fallback": {
        "required_fields": ["market", "provider", "status", "updated_at", "source"],
        "pit_date_field": "updated_at",
        "decision_visibility_rule": "provider status timestamp must be visible",
    },
}


@dataclass(frozen=True)
class GateResult:
    status: str
    blockers: list[str]
    notes: list[str]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _capability_for(market: str, layer: str) -> dict[str, Any]:
    catalog = build_market_capability_catalog()
    market_detail = (catalog.get("markets_detail") or {}).get(market, {})
    for row in market_detail.get("layers") or []:
        if row.get("id") == layer:
            return row
    return {}


def _layer_required_fields(layer: str) -> list[str]:
    schema = CANONICAL_SCHEMAS.get(layer, {})
    if schema:
        return list(schema["required_fields"])
    for row in CAPABILITY_LAYERS:
        if row["id"] == layer:
            return list(row["required_fields"])
    return []


def normalize_global_data_row(
    *,
    market: str,
    symbol: str,
    layer: str,
    raw: dict[str, Any] | None,
    source: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Return a canonical row plus missing-field metadata."""
    market = market.upper()
    raw = dict(raw or {})
    metadata = MARKET_METADATA.get(market, {})
    normalized = {
        "market": market,
        "symbol": symbol,
        "layer": layer,
        "currency": raw.get("currency") or metadata.get("currency"),
        "timezone": raw.get("timezone") or metadata.get("timezone"),
        "symbol_namespace": raw.get("symbol_namespace") or metadata.get("symbol_namespace"),
        "source": source,
        "fetched_at": fetched_at or raw.get("fetched_at") or _utc_now(),
        **raw,
    }
    required = _layer_required_fields(layer)
    missing = [field for field in required if normalized.get(field) in (None, "", [])]
    return {
        "data": normalized,
        "required_fields": required,
        "missing_fields": missing,
        "field_status": "complete" if not missing else "missing_fields",
    }


def pit_gate_for_layer(layer: str, normalized_row: dict[str, Any] | None = None) -> GateResult:
    """Evaluate the minimum point-in-time gate for an adapter row."""
    schema = CANONICAL_SCHEMAS.get(layer, {})
    pit_field = schema.get("pit_date_field")
    if not schema or not pit_field:
        return GateResult("blocked", ["unknown_canonical_schema"], ["Layer has no StockSage schema contract."])
    if not normalized_row:
        return GateResult("observe_only", ["no_normalized_row"], ["No row was normalized for PIT evaluation."])
    value = normalized_row.get(pit_field)
    if not value:
        return GateResult("observe_only", [f"missing_{pit_field}"], [schema["decision_visibility_rule"]])
    return GateResult("passed_for_read_only", [], [schema["decision_visibility_rule"]])


def _latest_price_payload(db, symbol: str) -> dict[str, Any] | None:
    price = db.query(Price).filter(Price.symbol == symbol).order_by(desc(Price.date)).first()
    if price is None:
        return None
    return {
        "date": price.date,
        "as_of": price.date,
        "price": price.close,
        "open": price.open,
        "high": price.high,
        "low": price.low,
        "close": price.close,
        "volume": price.volume,
        "source": price.source,
        "fetched_at": price.fetched_at.isoformat() if price.fetched_at else None,
        "adjustment": price.adjustment,
    }


def _recent_price_rows(db, symbol: str, limit: int = DEFAULT_PRICE_QUALITY_POLICY.recent_window) -> list[Price]:
    return (
        db.query(Price)
        .filter(Price.symbol == symbol)
        .order_by(desc(Price.date))
        .limit(limit)
        .all()
    )

def build_global_data_context(
    db,
    *,
    market: str,
    symbol: str,
    intent: str,
    probe_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an agent-facing read-only data envelope."""
    market = market.upper()
    if market not in SUPPORTED_MARKETS:
        raise ValueError("market must be CN, HK, or US")
    layer = INTENT_TO_LAYER.get(intent, intent)
    if layer not in CANONICAL_SCHEMAS:
        raise ValueError("intent must map to a known M41 layer")

    capability = _capability_for(market, layer)
    source = "local_price_db" if layer in {"quote", "kline"} else "capability_catalog"
    is_price_layer = layer in {"quote", "kline"}
    row = _latest_price_payload(db, symbol) if is_price_layer else None
    recent_rows = _recent_price_rows(db, symbol) if is_price_layer else []
    quality_gate = (
        evaluate_price_quality(market=market, row=row, recent_rows=recent_rows).to_payload()
        if is_price_layer
        else not_applicable_price_quality_gate().to_payload()
    )
    normalized = normalize_global_data_row(
        market=market,
        symbol=symbol,
        layer=layer,
        raw=row,
        source=source,
    )
    pit_gate = pit_gate_for_layer(layer, normalized["data"] if row else None)
    available = bool(row) if layer in {"quote", "kline"} else False
    status = "available" if available else "unavailable"
    if layer not in {"quote", "kline"}:
        status = "observe_only_unavailable"

    return {
        "market": market,
        "symbol": symbol,
        "intent": intent,
        "layer": layer,
        "status": status,
        "source": source,
        "fetched_at": normalized["data"]["fetched_at"],
        "freshness_status": "unmeasured" if not row else (
            "latest_local_bar" if quality_gate["status"] == "passed" else quality_gate["status"]
        ),
        "field_status": normalized["field_status"],
        "quality_gate": quality_gate,
        "required_fields": normalized["required_fields"],
        "missing_fields": normalized["missing_fields"],
        "canonical_schema": CANONICAL_SCHEMAS[layer],
        "pit_gate": asdict(pit_gate),
        "normalization": {
            "status": "contract_defined" if row else "adapter_required",
            "currency": normalized["data"].get("currency"),
            "timezone": normalized["data"].get("timezone"),
            "symbol_namespace": normalized["data"].get("symbol_namespace"),
        },
        "data": normalized["data"] if available else None,
        "capability": capability,
        "probe_summary": probe_summary or {},
        "write_policy": "no_database_writes",
        "signal_impact": "none" if not is_production_signal_market(market) else capability.get("signal_impact", "none"),
        "safe_for_research_scoring": False,
        "safe_for_production_signal": (
            is_production_signal_market(market)
            and capability.get("status") == "production"
            and available
            and quality_gate["status"] != "blocked"
        ),
        "production_signal_policy": production_signal_policy_payload(),
    }


def build_probe_health_ledger(
    summaries: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Aggregate explicit probe summaries into a read-only health ledger."""
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        for row in summary.get("rows") or []:
            rows.append({
                "market": row.get("market") or summary.get("market"),
                "symbol": row.get("symbol") or summary.get("symbol"),
                "layer": row.get("layer") or "unknown",
                "probe_id": row.get("probe_id"),
                "provider": row.get("provider"),
                "ok": bool(row.get("ok")),
                "health_status": row.get("health_status") or ("ok" if row.get("ok") else "failed"),
                "latency_ms": row.get("latency_ms"),
                "sample_size": int(row.get("sample_size") or 0),
                "missing_fields": list(row.get("missing_fields") or []),
                "field_status": row.get("field_status") or "normalization_pending",
                "freshness_status": row.get("freshness_status") or "unmeasured",
                "error": row.get("error"),
                "write_policy": row.get("write_policy") or "no_database_writes",
                "signal_impact": row.get("signal_impact") or "none",
            })

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["market"]), str(row["layer"]), str(row["provider"]))].append(row)

    health_rows: list[dict[str, Any]] = []
    for (market, layer, provider), items in sorted(grouped.items()):
        ok_count = sum(1 for item in items if item["ok"])
        error_classes = Counter(str(item["error"]) for item in items if item.get("error"))
        missing = sorted({field for item in items for field in item.get("missing_fields", [])})
        latencies = [float(item["latency_ms"]) for item in items if item.get("latency_ms") is not None]
        health_rows.append({
            "market": market,
            "layer": layer,
            "provider": provider,
            "sample_count": len(items),
            "ok_count": ok_count,
            "ok_rate": round(ok_count / len(items), 4) if items else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "total_sample_size": sum(int(item.get("sample_size") or 0) for item in items),
            "field_gaps": missing,
            "error_classes": dict(error_classes),
            "freshness_status": "unmeasured",
            "continuous_health_status": "needs_more_samples" if len(items) < 3 else ("stable" if ok_count == len(items) else "mixed"),
            "safe_for_research_scoring": False,
            "safe_for_production_signal": False,
        })

    return {
        "generated_at": generated_at or _utc_now(),
        "source": "explicit_probe_summaries",
        "write_policy": "no_database_writes",
        "signal_impact": "none",
        "total_rows": len(rows),
        "health_rows": health_rows,
        "raw_rows": rows,
    }


def load_probe_summaries(paths: list[Path]) -> list[dict[str, Any]]:
    """Load probe_summary objects from JSON files written by explicit probes."""
    import json

    summaries: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "probe_summary" in payload:
            summaries.append(payload["probe_summary"])
        elif isinstance(payload, dict) and "rows" in payload:
            summaries.append(payload)
    return summaries


def probe_summary_from_payload(probes: dict[str, Any], *, market: str, symbol: str) -> dict[str, Any]:
    """Small wrapper used by tools/tests to avoid route imports."""
    return summarize_probe_results(probes, market=market, symbol=symbol)
