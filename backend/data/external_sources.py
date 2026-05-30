"""External data source readiness catalog and opt-in probes.

This module intentionally does not register production market providers. It
keeps candidate sources observable before any endpoint is allowed into signal
inputs or scheduled jobs.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ExternalSource:
    id: str
    name: str
    repository_url: str
    recommended_stage: str
    high_value_datasets: list[str]
    useful_for: list[str]
    integration_notes: list[str]
    risk_level: str
    risk_notes: list[str]


@dataclass(frozen=True)
class ExternalEvidenceTrial:
    id: str
    source_id: str
    dataset: str
    stage: str
    signal_impact: str
    write_policy: str
    intended_use: list[str]
    required_fields: list[str]
    pit_requirements: list[str]
    failure_policy: str
    promotion_gate: list[str]


FTSHARE_STOCK_LIST_URL = "https://market.ft.tech/data/api/v1/market/data/stock-list"


def _sources() -> list[ExternalSource]:
    return [
        ExternalSource(
            id="a_stock_data",
            name="a-stock-data",
            repository_url="https://github.com/simonlin1212/a-stock-data",
            recommended_stage="evidence_trial",
            high_value_datasets=[
                "margin_trading",
                "limit_up_lhb",
                "unlock_calendar",
                "announcements",
                "research_reports",
                "shareholder_count",
                "block_trades",
            ],
            useful_for=[
                "risk_review",
                "deep_research_evidence",
                "long_term_analyst_context",
                "future_market_features",
            ],
            integration_notes=[
                "Treat endpoint outputs as evidence first, not signal weights.",
                "Add PIT timestamps before any dataset joins qlib features.",
                "Normalize fields behind StockSage-owned adapters instead of copying skill code.",
            ],
            risk_level="medium",
            risk_notes=[
                "Public or reverse-engineered endpoints can change without notice.",
                "Large endpoint set should be introduced one dataset at a time.",
            ],
        ),
        ExternalSource(
            id="ftshare",
            name="ftshare-market-data",
            repository_url="https://github.com/Shawn92/ftshare-market-data",
            recommended_stage="provider_probe",
            high_value_datasets=[
                "stock_list",
                "realtime_snapshot",
                "index_constituents",
                "etf_holdings",
                "convertible_bonds",
            ],
            useful_for=[
                "source_availability_monitoring",
                "universe_cross_check",
                "future_index_or_etf_context",
            ],
            integration_notes=[
                "Keep as an opt-in probe or fallback until reliability is measured.",
                "Do not replace existing efinance/AkShare/yfinance chain.",
            ],
            risk_level="medium_high",
            risk_notes=[
                "Depends on a single third-party service domain.",
                "Repository is small and should not become a direct runtime dependency.",
            ],
        ),
        ExternalSource(
            id="tickflow",
            name="TickFlow",
            repository_url="https://tickflow.org/",
            recommended_stage="provider_probe",
            high_value_datasets=[
                "daily_kline",
                "realtime_quote",
                "minute_kline",
                "market_depth",
                "financial_metrics",
                "cross_market_universes",
            ],
            useful_for=[
                "source_availability_monitoring",
                "future_cn_hk_us_market_data",
                "future_intraday_or_realtime_dashboard",
                "financial_quality_cross_check",
            ],
            integration_notes=[
                "Keep disabled by default behind TICKFLOW_ENABLED until data parity is measured.",
                "Use HTTP probe first; do not expose the API key to frontend code.",
                "Match StockSage's adjusted-price policy before registering as a signal provider.",
            ],
            risk_level="medium",
            risk_notes=[
                "Useful features depend on API key plan and channel permissions.",
                "Realtime, minute bars, WebSocket and market depth can consume paid quota.",
            ],
        ),
        ExternalSource(
            id="tushare_qfq",
            name="Tushare qfq",
            repository_url="https://tushare.pro/",
            recommended_stage="provider_probe",
            high_value_datasets=[
                "daily_kline",
                "adjustment_factor",
                "daily_basic",
                "financial_disclosure_calendar",
            ],
            useful_for=[
                "source_availability_monitoring",
                "cn_daily_fallback_after_qfq_normalization",
                "financial_quality_cross_check",
            ],
            integration_notes=[
                "Do not register raw pro.daily output as a production provider.",
                "Use daily plus adj_factor to emit qfq-compatible OHLCV bars.",
                "Respect adj_factor rate limits and prefer cached factors.",
            ],
            risk_level="medium",
            risk_notes=[
                "adj_factor frequency can be lower than daily-bar frequency on basic plans.",
                "Quota and point requirements depend on the Tushare account.",
            ],
        ),
        ExternalSource(
            id="ifind_mcp",
            name="iFinD MCP",
            repository_url="https://mcp.51ifind.com/",
            recommended_stage="evidence_probe",
            high_value_datasets=[
                "stock_financials",
                "stock_events",
                "stock_shareholders",
                "search_news",
                "search_notice",
                "index_data",
                "sector_data",
            ],
            useful_for=[
                "deep_research_evidence",
                "long_term_analyst_context",
                "news_and_notice_gap_fill",
                "single_day_quote_cross_check",
            ],
            integration_notes=[
                "Keep observe-only until field normalization and provider health are measured.",
                "Do not use natural-language OHLCV responses for bulk historical backfills.",
                "Store tokens only in local environment variables or MCP client config.",
            ],
            risk_level="medium",
            risk_notes=[
                "MCP responses can be Markdown or JSON text rather than stable OHLCV schemas.",
                "Paid plans increase quota but do not change the need for parser validation.",
            ],
        ),
    ]


def build_external_source_catalog() -> dict:
    """Return a stable, conservative catalog for candidate external sources."""
    sources = {source.id: asdict(source) for source in _sources()}
    evidence_trials = {trial.id: asdict(trial) for trial in _evidence_trials()}
    return {
        "policy": {
            "first_stage_rule": "observe_only",
            "production_signal_impact": "none",
            "scheduled_job_impact": "none",
            "write_policy": "no_database_writes",
        },
        "summary": {
            "source_count": len(sources),
            "recommended_first": [
                "ifind_mcp.search_news",
                "ifind_mcp.search_notice",
                "tushare_qfq.daily_kline",
            ],
            "next_safe_step": "probe_and_measure_before_ingestion",
        },
        "sources": sources,
        "evidence_trials": evidence_trials,
    }


def _evidence_trials() -> list[ExternalEvidenceTrial]:
    """Return observe-only evidence trials that are approved for design work."""
    return [
        ExternalEvidenceTrial(
            id="a_stock_data.margin_trading",
            source_id="a_stock_data",
            dataset="margin_trading",
            stage="evidence_trial",
            signal_impact="none",
            write_policy="no_database_writes",
            intended_use=[
                "risk_review",
                "evidence_card_auxiliary_context",
                "deep_research_question_generation",
            ],
            required_fields=[
                "symbol",
                "trade_date",
                "financing_balance",
                "financing_buy_amount",
                "securities_lending_balance",
                "source_url_or_endpoint",
            ],
            pit_requirements=[
                "trade_date must be <= decision as_of date",
                "provider timestamp must be preserved when available",
                "missing or stale data must be displayed as unavailable, not neutral",
            ],
            failure_policy="do_not_block_signal_generation",
            promotion_gate=[
                "provider health measured for at least 2 trading weeks",
                "field normalization covered by tests",
                "no composite_score or position_pct dependency",
            ],
        )
    ]


def _fetch_json(url: str, timeout_seconds: float) -> dict:
    request = Request(url, headers={"User-Agent": "StockSage/1.0"})
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(512_000)
    return json.loads(body.decode("utf-8"))


def probe_ftshare_stock_list(symbol: str = "600519", timeout_seconds: float = 5.0) -> dict:
    """Probe ftshare stock-list availability without writing to local state."""
    started = time.perf_counter()
    try:
        data = _fetch_json(FTSHARE_STOCK_LIST_URL, timeout_seconds=timeout_seconds)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("unexpected stock-list payload")
        matched = any(
            str(item.get("stock_code", "")).startswith(symbol)
            for item in items
            if isinstance(item, dict)
        )
        return {
            "ok": True,
            "symbol": symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "sample_size": len(items),
            "matched_symbol": matched,
            "error": None,
        }
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "symbol": symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "sample_size": 0,
            "matched_symbol": False,
            "error": str(exc),
        }


def probe_external_sources(symbol: str = "600519") -> dict:
    """Run explicit, side-effect-free probes for candidate external sources."""
    from backend.data.ifind_mcp import probe_ifind_mcp
    from backend.data.tickflow import probe_tickflow_daily
    from backend.data.tushare_qfq import probe_tushare_qfq_daily

    return {
        "ftshare": probe_ftshare_stock_list(symbol=symbol),
        "tickflow": probe_tickflow_daily(symbol=symbol, market="CN"),
        "tushare_qfq": probe_tushare_qfq_daily(symbol=symbol),
        "ifind_mcp": probe_ifind_mcp(),
    }
