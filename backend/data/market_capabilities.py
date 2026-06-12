"""A/HK/US market-data capability catalog.

This module is metadata-only: it does not fetch remote endpoints, write the
database, or promote any dataset into signal scoring.
"""
from __future__ import annotations

from copy import deepcopy

from backend.config import settings
from backend.data.providers import provider_fallback_chains

SUPPORTED_MARKETS = ("CN", "HK", "US")

CAPABILITY_LAYERS = (
    {
        "id": "quote",
        "label": "行情",
        "intent": "latest_quote",
        "required_fields": ["symbol", "price", "volume", "as_of", "source"],
    },
    {
        "id": "kline",
        "label": "K线",
        "intent": "daily_ohlcv",
        "required_fields": ["symbol", "date", "open", "high", "low", "close", "volume", "source"],
    },
    {
        "id": "fundamentals",
        "label": "基本面",
        "intent": "financial_metrics",
        "required_fields": ["symbol", "report_date", "disclosure_date", "revenue", "net_profit", "source"],
    },
    {
        "id": "capital_flow",
        "label": "资金面",
        "intent": "capital_and_liquidity",
        "required_fields": ["symbol", "trade_date", "metric", "value", "source"],
    },
    {
        "id": "derivatives",
        "label": "衍生品",
        "intent": "options_or_related_instruments",
        "required_fields": ["symbol", "contract", "expiry", "strike", "source"],
    },
    {
        "id": "filings",
        "label": "披露文件",
        "intent": "regulatory_filings",
        "required_fields": ["symbol", "published_at", "title", "url", "source"],
    },
    {
        "id": "tools_fallback",
        "label": "工具/备用",
        "intent": "symbol_calendar_provider_health",
        "required_fields": ["market", "provider", "status", "updated_at"],
    },
)

PROBE_LINKS: dict[str, dict[str, list[dict[str, object]]]] = {
    "CN": {
        "kline": [
            {
                "probe_id": "tickflow",
                "source_id": "tickflow",
                "default_symbol": "600519",
                "probe_market": "CN",
                "status": "observe_only",
            },
            {
                "probe_id": "tushare_qfq",
                "source_id": "tushare_qfq",
                "default_symbol": "600519",
                "probe_market": "CN",
                "status": "optional_probe",
            },
        ],
        "fundamentals": [
            {
                "probe_id": "ifind_mcp",
                "source_id": "ifind_mcp",
                "default_symbol": "600519",
                "probe_market": "CN",
                "status": "evidence_probe",
            }
        ],
        "capital_flow": [
            {
                "probe_id": "ftshare",
                "source_id": "ftshare",
                "default_symbol": "600519",
                "probe_market": "CN",
                "status": "provider_probe",
            }
        ],
        "filings": [
            {
                "probe_id": "ifind_mcp",
                "source_id": "ifind_mcp",
                "default_symbol": "600519",
                "probe_market": "CN",
                "status": "evidence_probe",
            }
        ],
    },
    "HK": {
        "fundamentals": [
            {
                "probe_id": "yfinance_basic",
                "source_id": "yfinance_global",
                "default_symbol": "700",
                "probe_market": "HK",
                "status": "read_only_probe",
            }
        ],
        "filings": [
            {
                "probe_id": "hkex_filings",
                "source_id": "hkexnews",
                "default_symbol": "700",
                "probe_market": "HK",
                "status": "reachability_probe",
            }
        ],
    },
    "US": {
        "fundamentals": [
            {
                "probe_id": "sec_companyfacts",
                "source_id": "sec_data_api",
                "default_symbol": "AAPL",
                "probe_market": "US",
                "status": "read_only_probe",
            },
            {
                "probe_id": "yfinance_basic",
                "source_id": "yfinance_global",
                "default_symbol": "AAPL",
                "probe_market": "US",
                "status": "read_only_probe",
            },
        ],
        "derivatives": [
            {
                "probe_id": "yfinance_options",
                "source_id": "yfinance_global",
                "default_symbol": "AAPL",
                "probe_market": "US",
                "status": "read_only_probe",
            }
        ],
        "filings": [
            {
                "probe_id": "sec_filings",
                "source_id": "sec_data_api",
                "default_symbol": "AAPL",
                "probe_market": "US",
                "status": "read_only_probe",
            }
        ],
    },
}


_CAPABILITIES: dict[str, dict[str, dict[str, object]]] = {
    "CN": {
        "quote": {
            "status": "production",
            "stage": "provider_chain",
            "providers": ["akshare_sina_cn", "efinance_cn", "eastmoney_cn", "akshare_em_cn", "tushare_qfq_cn"],
            "signal_impact": "price_inputs",
            "notes": ["A-share quote/daily providers are governed by the existing fallback chain."],
        },
        "kline": {
            "status": "production",
            "stage": "provider_chain",
            "providers": ["akshare_sina_cn", "efinance_cn", "eastmoney_cn", "akshare_em_cn", "tushare_qfq_cn"],
            "signal_impact": "technical_inputs",
            "notes": ["qfq-compatible daily OHLCV remains the production adjustment policy."],
        },
        "fundamentals": {
            "status": "production",
            "stage": "normalized_db",
            "providers": ["akshare_financial_abstract", "akshare_financial_indicator"],
            "signal_impact": "long_term_research_inputs",
            "notes": ["FinancialMetric stores PIT-aware disclosure dates when available."],
        },
        "capital_flow": {
            "status": "observe_only",
            "stage": "evidence",
            "providers": ["qfii_holdings", "ifind_mcp_candidate", "a_stock_data_candidate"],
            "signal_impact": "none",
            "notes": ["Use as evidence until health and PIT gates are measured."],
        },
        "derivatives": {
            "status": "planned",
            "stage": "not_connected",
            "providers": [],
            "signal_impact": "none",
            "notes": ["Not a core A-share production input yet."],
        },
        "filings": {
            "status": "production",
            "stage": "normalized_db",
            "providers": ["akshare_stock_report_disclosure"],
            "signal_impact": "freshness_and_pit_guard",
            "notes": ["Disclosure dates are used for no-look-ahead financial context."],
        },
        "tools_fallback": {
            "status": "production",
            "stage": "provider_observability",
            "providers": ["provider_fallback_chains", "cache_policy", "data_coverage"],
            "signal_impact": "governance",
            "notes": ["Provider health, cooldown, cache policy, and freshness contracts are observable."],
        },
    },
    "HK": {
        "quote": {
            "status": "seeded",
            "stage": "daily_price_bridge",
            "providers": ["yfinance_hk"],
            "signal_impact": "none",
            "notes": ["Daily OHLCV is available; realtime quote parity is not promoted."],
        },
        "kline": {
            "status": "seeded",
            "stage": "daily_price_bridge",
            "providers": ["yfinance_hk"],
            "signal_impact": "observe_only_price_context",
            "notes": ["Uses Yahoo Finance .HK mapping and auto-adjusted daily bars."],
        },
        "fundamentals": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["hkex_candidate", "yfinance_candidate"],
            "signal_impact": "none",
            "notes": ["Needs field normalization, disclosure timing, and provider health before scoring."],
        },
        "capital_flow": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["southbound_flow_candidate", "hkex_candidate"],
            "signal_impact": "none",
            "notes": ["HK liquidity/capital definitions differ from A-share northbound/QFII evidence."],
        },
        "derivatives": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["hkex_options_candidate"],
            "signal_impact": "none",
            "notes": ["Options data must remain read-only until schema and quota risks are known."],
        },
        "filings": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["hkexnews_candidate"],
            "signal_impact": "none",
            "notes": ["HKEX filings are high-value for research but not normalized yet."],
        },
        "tools_fallback": {
            "status": "seeded",
            "stage": "provider_observability",
            "providers": ["provider_fallback_chains", "hk_yfinance_ticker"],
            "signal_impact": "governance",
            "notes": ["Symbol mapping and provider health are observable for the daily bridge."],
        },
    },
    "US": {
        "quote": {
            "status": "seeded",
            "stage": "daily_price_bridge",
            "providers": ["yfinance_us"],
            "signal_impact": "none",
            "notes": ["Daily OHLCV is available; realtime quote parity is not promoted."],
        },
        "kline": {
            "status": "seeded",
            "stage": "daily_price_bridge",
            "providers": ["yfinance_us"],
            "signal_impact": "observe_only_price_context",
            "notes": ["Uses Yahoo Finance auto-adjusted daily bars."],
        },
        "fundamentals": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["sec_companyfacts_candidate", "yfinance_candidate"],
            "signal_impact": "none",
            "notes": ["SEC XBRL/companyfacts should be normalized before research scoring."],
        },
        "capital_flow": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["institutional_holders_candidate"],
            "signal_impact": "none",
            "notes": ["US flow evidence needs a different schema from A-share capital metrics."],
        },
        "derivatives": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["options_chain_candidate"],
            "signal_impact": "none",
            "notes": ["Option chains are useful for research but must not affect position sizing yet."],
        },
        "filings": {
            "status": "planned",
            "stage": "candidate_probe",
            "providers": ["sec_filings_candidate"],
            "signal_impact": "none",
            "notes": ["SEC filings are the next high-value read-only US layer."],
        },
        "tools_fallback": {
            "status": "seeded",
            "stage": "provider_observability",
            "providers": ["provider_fallback_chains"],
            "signal_impact": "governance",
            "notes": ["Provider health is observable for the daily bridge."],
        },
    },
}


def _probe_links_for(market: str, layer_id: str) -> list[dict[str, object]]:
    links = PROBE_LINKS.get(market, {}).get(layer_id, [])
    rows: list[dict[str, object]] = []
    for link in links:
        row = {
            **deepcopy(link),
            "write_policy": "no_database_writes",
            "signal_impact": "none",
        }
        if row.get("source_id") == "ifind_mcp":
            row.update({
                "enabled": bool(settings.ifind_mcp_enabled),
                "configured": bool(settings.ifind_mcp_token),
                "qps_limit": float(settings.ifind_mcp_qps_limit),
                "role": "stable read-only evidence source for news, notices, fundamentals, and filings",
            })
        rows.append(row)
    return rows


def build_market_probe_links() -> dict:
    """Return market/layer probe link metadata without running probes."""
    return {
        market: {
            layer["id"]: _probe_links_for(market, str(layer["id"]))
            for layer in CAPABILITY_LAYERS
        }
        for market in SUPPORTED_MARKETS
    }


def _market_status(layer_rows: list[dict]) -> str:
    statuses = {row["status"] for row in layer_rows}
    if "blocked" in statuses:
        return "blocked"
    if "planned" in statuses:
        return "partial"
    if "observe_only" in statuses:
        return "partial"
    if "seeded" in statuses:
        return "seeded"
    return "production"


def build_market_capability_catalog() -> dict:
    """Return the MingCang 7-layer capability catalog for CN/HK/US."""
    markets: dict[str, dict[str, object]] = {}
    for market in SUPPORTED_MARKETS:
        layers: list[dict[str, object]] = []
        for layer in CAPABILITY_LAYERS:
            layer_id = str(layer["id"])
            capability = deepcopy(_CAPABILITIES[market][layer_id])
            capability.update({
                "id": layer_id,
                "label": layer["label"],
                "intent": layer["intent"],
                "required_fields": list(layer["required_fields"]),
                "probe_links": _probe_links_for(market, layer_id),
            })
            layers.append(capability)
        markets[market] = {
            "status": _market_status(layers),
            "layers": layers,
            "provider_fallback": provider_fallback_chains(market),
        }

    return {
        "version": "mingcang_market_data_skill_v1",
        "source": "M41 global market data skill bridge",
        "markets": list(SUPPORTED_MARKETS),
        "layers": [
            {
                "id": layer["id"],
                "label": layer["label"],
                "intent": layer["intent"],
                "required_fields": list(layer["required_fields"]),
            }
            for layer in CAPABILITY_LAYERS
        ],
        "policy": {
            "probe_mode": "metadata_only_by_default",
            "write_policy": "no_database_writes",
            "production_signal_rule": (
                "Only CN production-ready layers are eligible for current signal inputs; "
                "HK/US non-price layers stay observe-only/planned until field, PIT, "
                "freshness, and provider-health gates pass."
            ),
        },
        "agent_facade": {
            "routing_keys": [layer["intent"] for layer in CAPABILITY_LAYERS],
            "required_output_fields": ["market", "symbol", "layer", "source", "fetched_at", "freshness_status"],
            "fallback_rule": "route by market + intent, then report unavailable instead of fabricating data",
        },
        "probe_links": build_market_probe_links(),
        "markets_detail": markets,
    }
