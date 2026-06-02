"""M31 cache-layer and freshness policy contracts.

The module is intentionally declarative: production fetchers keep their
existing behavior, while CLI/status/benchmark surfaces can expose one shared
contract for when remote data is allowed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CacheLayer:
    id: str
    name: str
    source: str
    network_allowed: bool
    write_allowed: bool
    typical_use: str


@dataclass(frozen=True)
class FreshnessContract:
    data_type: str
    refresh_frequency: str
    stale_after: str
    remote_refresh_window: str
    intraday_policy: str


CACHE_LAYERS: tuple[CacheLayer, ...] = (
    CacheLayer(
        id="L1",
        name="process_memory",
        source="in-process caches and provider health counters",
        network_allowed=False,
        write_allowed=False,
        typical_use="fast status, policy checks, repeated request-local reads",
    ),
    CacheLayer(
        id="L2",
        name="local_sqlite",
        source="stock-sage.db persisted prices, signals, reviews, memories",
        network_allowed=False,
        write_allowed=False,
        typical_use="intraday analysis, dashboards, exports, stop-loss checks",
    ),
    CacheLayer(
        id="L3",
        name="remote_api_incremental",
        source="AkShare/eastmoney/iFinD/Tavily/Tushare/TickFlow/yfinance providers",
        network_allowed=True,
        write_allowed=True,
        typical_use="premarket and postmarket refresh or explicit maintenance backfills",
    ),
)


FRESHNESS_CONTRACTS: tuple[FreshnessContract, ...] = (
    FreshnessContract(
        data_type="daily_price",
        refresh_frequency="trading_day",
        stale_after="T+1 trading day",
        remote_refresh_window="premarket_or_postmarket",
        intraday_policy="read_L1_L2_only",
    ),
    FreshnessContract(
        data_type="index_price",
        refresh_frequency="trading_day",
        stale_after="T+1 trading day",
        remote_refresh_window="premarket_or_postmarket",
        intraday_policy="read_L1_L2_only",
    ),
    FreshnessContract(
        data_type="realtime_or_intraday_quote",
        refresh_frequency="seconds_to_minutes",
        stale_after="same_session",
        remote_refresh_window="explicit_intraday_probe_only",
        intraday_policy="observe_only_until_realtime_pipeline_exists",
    ),
    FreshnessContract(
        data_type="stock_news",
        refresh_frequency="daily_or_event_driven",
        stale_after="24h",
        remote_refresh_window="premarket_or_postmarket",
        intraday_policy="read_cached_news_only",
    ),
    FreshnessContract(
        data_type="capital_flow",
        refresh_frequency="T+1",
        stale_after="2 trading days",
        remote_refresh_window="postmarket_incremental",
        intraday_policy="read_L1_L2_only",
    ),
    FreshnessContract(
        data_type="fundamentals",
        refresh_frequency="quarterly",
        stale_after="next_disclosure_cycle",
        remote_refresh_window="scheduled_maintenance",
        intraday_policy="read_L1_L2_only",
    ),
    FreshnessContract(
        data_type="sector_or_industry",
        refresh_frequency="quarterly_or_manual",
        stale_after="quarterly_review",
        remote_refresh_window="scheduled_maintenance",
        intraday_policy="read_L1_L2_only",
    ),
)


REMOTE_REFRESH_PHASES = {"premarket", "postmarket", "maintenance"}


def cache_layers_payload() -> list[dict]:
    """Return the stable L1/L2/L3 cache-layer contract."""
    return [asdict(layer) for layer in CACHE_LAYERS]


def freshness_contracts_payload() -> dict[str, dict]:
    """Return freshness contracts keyed by data type."""
    return {contract.data_type: asdict(contract) for contract in FRESHNESS_CONTRACTS}


def remote_fetch_allowed(phase: str) -> bool:
    """Return whether L3 remote API refresh is allowed for a workflow phase."""
    return phase in REMOTE_REFRESH_PHASES


def workflow_cache_policy(phase: str) -> dict:
    """Return cache policy for premarket/intraday/postmarket/maintenance workflows."""
    allow_remote = remote_fetch_allowed(phase)
    return {
        "phase": phase,
        "allowed_layers": ["L1", "L2", "L3"] if allow_remote else ["L1", "L2"],
        "remote_fetch_allowed": allow_remote,
        "writes_db_allowed": allow_remote,
        "zero_network_intraday": phase == "intraday",
    }


def intraday_zero_network_policy() -> dict:
    """Return the explicit intraday zero-network guarantee used by M31."""
    return {
        "guarantee": "intraday analysis reads L1/L2 only",
        "remote_layer": "L3",
        "remote_fetch_allowed": False,
        "allowed_layers": ["L1", "L2"],
        "allowed_entrypoints": [
            "backend.data.market.load_price_df",
            "backend.data.quality.build_data_coverage_snapshot",
            "backend.scheduler.job_stoploss_check",
        ],
        "blocked_by_default": [
            "backend.data.market.backfill_if_needed",
            "backend.data.market.fetch_daily",
            "backend.data.news.fetch_stock_news_cn",
            "backend.scheduler.job_premarket",
            "backend.scheduler.job_postmarket",
        ],
    }


def cache_policy_payload() -> dict:
    """Return the full M31 cache and freshness policy payload."""
    return {
        "cache_layers": cache_layers_payload(),
        "workflow_policies": {
            phase: workflow_cache_policy(phase)
            for phase in ("premarket", "intraday", "postmarket", "maintenance")
        },
        "intraday_zero_network_policy": intraday_zero_network_policy(),
        "freshness_contracts": freshness_contracts_payload(),
    }
