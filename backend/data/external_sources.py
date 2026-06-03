"""External data source readiness catalog and opt-in probes.

This module intentionally does not register production market providers. It
keeps candidate sources observable before any endpoint is allowed into signal
inputs or scheduled jobs.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import requests
import yfinance as yf


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
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
HKEXNEWS_TITLE_SEARCH_URL = "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en"


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
        ExternalSource(
            id="sec_data_api",
            name="SEC EDGAR data APIs",
            repository_url="https://www.sec.gov/edgar/sec-api-documentation",
            recommended_stage="provider_probe",
            high_value_datasets=[
                "company_submissions",
                "company_facts_xbrl",
                "recent_filings",
            ],
            useful_for=[
                "us_filings_layer",
                "us_fundamentals_probe",
                "deep_research_evidence",
            ],
            integration_notes=[
                "Use official SEC JSON endpoints with a descriptive User-Agent.",
                "Keep submissions/companyfacts as read-only evidence until XBRL fields are normalized.",
                "Preserve filing date, form type, accession number, and source URL in downstream adapters.",
            ],
            risk_level="medium",
            risk_notes=[
                "SEC responses can be large and should keep timeout and response-size guards.",
                "Ticker-to-CIK mapping must be measured before assuming symbol coverage.",
            ],
        ),
        ExternalSource(
            id="hkexnews",
            name="HKEXnews",
            repository_url="https://www.hkexnews.hk/",
            recommended_stage="provider_probe",
            high_value_datasets=[
                "announcements",
                "financial_reports",
                "issuer_filings",
            ],
            useful_for=[
                "hk_filings_layer",
                "hk_fundamentals_probe",
                "deep_research_evidence",
            ],
            integration_notes=[
                "Start with reachability and schema discovery before symbol-level ingestion.",
                "Do not scrape filings into research outputs until URL, title, issuer, and publication time are normalized.",
            ],
            risk_level="medium_high",
            risk_notes=[
                "HKEXnews search behavior can change and may require separate field parser tests.",
                "Issuer-code matching is not equivalent to Yahoo .HK ticker mapping.",
            ],
        ),
        ExternalSource(
            id="yfinance_global",
            name="Yahoo Finance global",
            repository_url="https://finance.yahoo.com/",
            recommended_stage="provider_probe",
            high_value_datasets=[
                "hk_us_daily_kline",
                "basic_info",
                "options_expiries",
            ],
            useful_for=[
                "hk_us_daily_price_bridge",
                "basic_fundamentals_probe",
                "us_options_probe",
            ],
            integration_notes=[
                "Daily HK/US bars are already registered through provider fallback.",
                "Fundamentals/options remain read-only probes until freshness and field stability are measured.",
            ],
            risk_level="medium",
            risk_notes=[
                "Unofficial endpoints can change and should not be treated as production fundamentals.",
                "Options availability varies by ticker and market.",
            ],
        ),
    ]


def build_external_source_catalog() -> dict:
    """Return a stable, conservative catalog for candidate external sources."""
    from backend.data.market_capabilities import build_market_probe_links

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
            "global_market_recommended_first": [
                "sec_data_api.company_submissions",
                "sec_data_api.company_facts_xbrl",
                "hkexnews.announcements",
                "yfinance_global.options_expiries",
            ],
            "next_safe_step": "probe_and_measure_before_ingestion",
        },
        "sources": sources,
        "evidence_trials": evidence_trials,
        "market_probe_links": build_market_probe_links(),
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


def _fetch_json(url: str, timeout_seconds: float, max_bytes: int = 512_000) -> dict:
    response = requests.get(
        url,
        headers={"User-Agent": "StockSage/1.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if len(response.content) > max_bytes:
        raise ValueError("response too large")
    return response.json()


def _fetch_text(url: str, timeout_seconds: float, max_bytes: int = 512_000) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "StockSage/1.0"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    if len(response.content) > max_bytes:
        raise ValueError("response too large")
    return response.text


def _probe_payload(
    *,
    ok: bool,
    provider: str,
    market: str,
    layer: str,
    symbol: str,
    started: float,
    sample_size: int = 0,
    fields_present: list[str] | None = None,
    error: str | None = None,
) -> dict:
    return {
        "ok": ok,
        "provider": provider,
        "market": market,
        "layer": layer,
        "symbol": symbol,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "sample_size": sample_size,
        "fields_present": fields_present or [],
        "write_policy": "no_database_writes",
        "signal_impact": "none",
        "error": error,
    }


def _probe_link_lookup(market: str) -> dict[str, str]:
    from backend.data.market_capabilities import build_market_probe_links

    lookup: dict[str, str] = {}
    for layer_id, links in build_market_probe_links().get(market, {}).items():
        for link in links:
            probe_id = str(link.get("probe_id") or "")
            if probe_id and probe_id not in lookup:
                lookup[probe_id] = layer_id
    return lookup


def _required_fields_for_layers() -> dict[str, list[str]]:
    from backend.data.market_capabilities import CAPABILITY_LAYERS

    return {str(layer["id"]): list(layer["required_fields"]) for layer in CAPABILITY_LAYERS}


def summarize_probe_results(probes: dict, *, market: str, symbol: str) -> dict:
    """Normalize explicit probe payloads into read-only health rows.

    The summary is intentionally metadata-only: it describes field gaps and
    probe availability, but does not mark any source as research/scoring-ready.
    """
    market = market.upper()
    required_fields = _required_fields_for_layers()
    link_lookup = _probe_link_lookup(market)
    rows: list[dict[str, object]] = []

    for probe_id, raw_payload in sorted(probes.items()):
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        layer = str(payload.get("layer") or link_lookup.get(str(probe_id)) or "unknown")
        fields_present = payload.get("fields_present")
        present = [str(field) for field in fields_present] if isinstance(fields_present, list) else []
        required = required_fields.get(layer, [])
        missing = [field for field in required if field not in present]
        ok = bool(payload.get("ok"))
        rows.append(
            {
                "probe_id": str(probe_id),
                "provider": str(payload.get("provider") or probe_id),
                "market": str(payload.get("market") or market),
                "layer": layer,
                "symbol": str(payload.get("symbol") or symbol),
                "ok": ok,
                "health_status": "ok" if ok else "failed",
                "sample_size": int(payload.get("sample_size") or 0),
                "latency_ms": payload.get("latency_ms"),
                "fields_present": present,
                "required_fields": required,
                "missing_fields": missing,
                "field_status": "required_fields_present" if ok and required and not missing else "normalization_pending",
                "freshness_status": "unmeasured",
                "write_policy": str(payload.get("write_policy") or "no_database_writes"),
                "signal_impact": str(payload.get("signal_impact") or "none"),
                "error": payload.get("error"),
            }
        )

    ok_count = sum(1 for row in rows if row["ok"])
    return {
        "probed": True,
        "market": market,
        "symbol": symbol,
        "checked_at": datetime.now(UTC).isoformat(),
        "total_probes": len(rows),
        "ok_count": ok_count,
        "failed_count": len(rows) - ok_count,
        "layers_covered": sorted({str(row["layer"]) for row in rows if row["layer"] != "unknown"}),
        "required_fields_present_count": sum(1 for row in rows if row["field_status"] == "required_fields_present"),
        "safe_for_research_scoring": False,
        "safe_for_production_signal": False,
        "write_policy": "no_database_writes",
        "signal_impact": "none",
        "rows": rows,
    }


def _sec_cik_for_symbol(symbol: str, timeout_seconds: float) -> str | None:
    tickers = _fetch_json(SEC_COMPANY_TICKERS_URL, timeout_seconds=timeout_seconds, max_bytes=2_000_000)
    target = symbol.strip().upper()
    rows = tickers.values() if isinstance(tickers, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker", "")).upper() == target:
            return str(row.get("cik_str", "")).zfill(10)
    return None


def probe_sec_filings(symbol: str = "AAPL", timeout_seconds: float = 5.0) -> dict:
    """Probe official SEC recent filing availability without writing local state."""
    started = time.perf_counter()
    try:
        cik = _sec_cik_for_symbol(symbol, timeout_seconds)
        if not cik:
            raise ValueError("no SEC CIK mapping for symbol")
        data = _fetch_json(SEC_SUBMISSIONS_URL.format(cik=cik), timeout_seconds=timeout_seconds, max_bytes=2_000_000)
        recent = ((data.get("filings") or {}).get("recent") or {}) if isinstance(data, dict) else {}
        forms = recent.get("form") if isinstance(recent, dict) else None
        accession = recent.get("accessionNumber") if isinstance(recent, dict) else None
        filing_dates = recent.get("filingDate") if isinstance(recent, dict) else None
        sample_size = len(forms) if isinstance(forms, list) else 0
        fields = [
            field
            for field, value in {
                "form": forms,
                "accessionNumber": accession,
                "filingDate": filing_dates,
            }.items()
            if isinstance(value, list) and value
        ]
        if sample_size <= 0:
            raise ValueError("no recent SEC filings in payload")
        return _probe_payload(
            ok=True,
            provider="sec_data_api",
            market="US",
            layer="filings",
            symbol=symbol,
            started=started,
            sample_size=sample_size,
            fields_present=fields,
        )
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        return _probe_payload(
            ok=False,
            provider="sec_data_api",
            market="US",
            layer="filings",
            symbol=symbol,
            started=started,
            error=str(exc),
        )


def probe_sec_companyfacts(symbol: str = "AAPL", timeout_seconds: float = 5.0) -> dict:
    """Probe official SEC companyfacts availability without normalizing fields."""
    started = time.perf_counter()
    try:
        cik = _sec_cik_for_symbol(symbol, timeout_seconds)
        if not cik:
            raise ValueError("no SEC CIK mapping for symbol")
        data = _fetch_json(SEC_COMPANYFACTS_URL.format(cik=cik), timeout_seconds=timeout_seconds, max_bytes=3_000_000)
        facts = data.get("facts") if isinstance(data, dict) else None
        if not isinstance(facts, dict) or not facts:
            raise ValueError("no SEC companyfacts in payload")
        namespaces = sorted(facts.keys())
        return _probe_payload(
            ok=True,
            provider="sec_data_api",
            market="US",
            layer="fundamentals",
            symbol=symbol,
            started=started,
            sample_size=sum(len(v) for v in facts.values() if isinstance(v, dict)),
            fields_present=namespaces,
        )
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        return _probe_payload(
            ok=False,
            provider="sec_data_api",
            market="US",
            layer="fundamentals",
            symbol=symbol,
            started=started,
            error=str(exc),
        )


def probe_yfinance_basic(symbol: str, market: str = "US") -> dict:
    """Probe Yahoo Finance basic-info field availability for HK/US research only."""
    started = time.perf_counter()
    try:
        ticker_symbol = symbol
        if market == "HK":
            from backend.data.market import hk_yfinance_ticker
            ticker_symbol = hk_yfinance_ticker(symbol)
        info = yf.Ticker(ticker_symbol).info or {}
        fields = [field for field in ("marketCap", "trailingPE", "currency", "longName") if info.get(field) is not None]
        if not fields:
            raise ValueError("no basic-info fields in yfinance payload")
        return _probe_payload(
            ok=True,
            provider="yfinance_global",
            market=market,
            layer="fundamentals",
            symbol=symbol,
            started=started,
            sample_size=len(fields),
            fields_present=fields,
        )
    except Exception as exc:
        return _probe_payload(
            ok=False,
            provider="yfinance_global",
            market=market,
            layer="fundamentals",
            symbol=symbol,
            started=started,
            error=str(exc),
        )


def probe_yfinance_options(symbol: str = "AAPL") -> dict:
    """Probe Yahoo Finance option-expiry availability without fetching chains."""
    started = time.perf_counter()
    try:
        expiries = list(yf.Ticker(symbol).options or [])
        if not expiries:
            raise ValueError("no option expiries in yfinance payload")
        return _probe_payload(
            ok=True,
            provider="yfinance_global",
            market="US",
            layer="derivatives",
            symbol=symbol,
            started=started,
            sample_size=len(expiries),
            fields_present=["expiry"],
        )
    except Exception as exc:
        return _probe_payload(
            ok=False,
            provider="yfinance_global",
            market="US",
            layer="derivatives",
            symbol=symbol,
            started=started,
            error=str(exc),
        )


def probe_hkex_filings(symbol: str = "700", timeout_seconds: float = 5.0) -> dict:
    """Probe HKEXnews availability before symbol-level filing parsing exists."""
    started = time.perf_counter()
    try:
        text = _fetch_text(HKEXNEWS_TITLE_SEARCH_URL, timeout_seconds=timeout_seconds, max_bytes=512_000)
        markers = [marker for marker in ("HKEXnews", "Headline Category", "Title Search") if marker in text]
        if not markers:
            raise ValueError("unexpected HKEXnews title-search page")
        return _probe_payload(
            ok=True,
            provider="hkexnews",
            market="HK",
            layer="filings",
            symbol=symbol,
            started=started,
            sample_size=1,
            fields_present=markers,
        )
    except (requests.RequestException, ValueError) as exc:
        return _probe_payload(
            ok=False,
            provider="hkexnews",
            market="HK",
            layer="filings",
            symbol=symbol,
            started=started,
            error=str(exc),
        )


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
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "symbol": symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "sample_size": 0,
            "matched_symbol": False,
            "error": str(exc),
        }


def probe_external_sources(symbol: str = "600519", market: str = "CN") -> dict:
    """Run explicit, side-effect-free probes for candidate external sources."""
    market = market.upper()
    if market not in {"CN", "HK", "US"}:
        raise ValueError("market must be CN, HK, or US")
    if market == "US":
        return {
            "sec_filings": probe_sec_filings(symbol=symbol),
            "sec_companyfacts": probe_sec_companyfacts(symbol=symbol),
            "yfinance_basic": probe_yfinance_basic(symbol=symbol, market="US"),
            "yfinance_options": probe_yfinance_options(symbol=symbol),
        }
    if market == "HK":
        return {
            "hkex_filings": probe_hkex_filings(symbol=symbol),
            "yfinance_basic": probe_yfinance_basic(symbol=symbol, market="HK"),
        }

    from backend.data.ifind_mcp import probe_ifind_mcp
    from backend.data.tickflow import probe_tickflow_daily
    from backend.data.tushare_qfq import probe_tushare_qfq_daily

    return {
        "ftshare": probe_ftshare_stock_list(symbol=symbol),
        "tickflow": probe_tickflow_daily(symbol=symbol, market="CN"),
        "tushare_qfq": probe_tushare_qfq_daily(symbol=symbol),
        "ifind_mcp": probe_ifind_mcp(),
    }
