"""Market/news data provider registry with fallback and short cooldowns."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import time

import pandas as pd

logger = logging.getLogger(__name__)

DailyFetcher = Callable[[str, int], pd.DataFrame]
IndexFetcher = Callable[[str, int], pd.DataFrame]


@dataclass(frozen=True)
class DailyProvider:
    name: str
    markets: set[str]
    fetch: DailyFetcher
    priority: int = 100
    cooldown_seconds: int = 0
    data_type: str = "daily_price"
    observe_only: bool = False


@dataclass(frozen=True)
class IndexProvider:
    name: str
    fetch: IndexFetcher
    markets: set[str]
    priority: int = 100
    cooldown_seconds: int = 0
    data_type: str = "index_price"
    observe_only: bool = False


_DAILY_PROVIDERS: list[DailyProvider] = []
_INDEX_PROVIDERS: list[IndexProvider] = []
_PROVIDER_HEALTH: dict[str, dict] = {}


def _default_health() -> dict:
    return {"successes": 0, "failures": 0, "skipped": 0, "last_error": None, "cooldown_until": None}


def _health(name: str) -> dict:
    return _PROVIDER_HEALTH.setdefault(name, _default_health())


def register_daily_provider(
    name: str,
    markets: set[str],
    fetch: DailyFetcher,
    *,
    priority: int = 100,
    cooldown_seconds: int = 0,
    data_type: str = "daily_price",
    observe_only: bool = False,
) -> None:
    """Register or replace a daily OHLCV provider."""
    global _DAILY_PROVIDERS
    _DAILY_PROVIDERS = [p for p in _DAILY_PROVIDERS if p.name != name]
    _DAILY_PROVIDERS.append(DailyProvider(
        name=name,
        markets=markets,
        fetch=fetch,
        priority=priority,
        cooldown_seconds=cooldown_seconds,
        data_type=data_type,
        observe_only=observe_only,
    ))
    _DAILY_PROVIDERS.sort(key=lambda p: p.priority)
    _health(name)


def register_index_provider(
    name: str,
    fetch: IndexFetcher,
    *,
    markets: set[str] | None = None,
    priority: int = 100,
    cooldown_seconds: int = 0,
    data_type: str = "index_price",
    observe_only: bool = False,
) -> None:
    """Register or replace an index OHLC provider."""
    global _INDEX_PROVIDERS
    _INDEX_PROVIDERS = [p for p in _INDEX_PROVIDERS if p.name != name]
    _INDEX_PROVIDERS.append(IndexProvider(
        name=name,
        fetch=fetch,
        markets=set(markets or {"CN"}),
        priority=priority,
        cooldown_seconds=cooldown_seconds,
        data_type=data_type,
        observe_only=observe_only,
    ))
    _INDEX_PROVIDERS.sort(key=lambda p: p.priority)
    _health(name)


def reset_provider_health() -> None:
    """Clear in-process provider health counters."""
    _PROVIDER_HEALTH.clear()


def reset_provider_registry() -> None:
    """Clear registered providers and health counters for deterministic tests."""
    _DAILY_PROVIDERS.clear()
    _INDEX_PROVIDERS.clear()
    _PROVIDER_HEALTH.clear()


def get_provider_health() -> dict[str, dict]:
    """Return provider success/failure counters."""
    return {name: dict(stats) for name, stats in _PROVIDER_HEALTH.items()}


def _record_provider_success(name: str) -> None:
    stats = _health(name)
    stats["successes"] += 1
    stats["last_error"] = None
    stats["cooldown_until"] = None


def _record_provider_failure(name: str, error: str, cooldown_seconds: int = 0) -> None:
    stats = _health(name)
    stats["failures"] += 1
    stats["last_error"] = error
    if cooldown_seconds > 0:
        stats["cooldown_until"] = time() + cooldown_seconds


def _provider_in_cooldown(name: str) -> bool:
    cooldown_until = _health(name).get("cooldown_until")
    if cooldown_until is None:
        return False
    if float(cooldown_until) <= time():
        _health(name)["cooldown_until"] = None
        return False
    _health(name)["skipped"] += 1
    return True


def list_daily_providers(market: str | None = None) -> list[str]:
    """List provider names, optionally filtered by market."""
    if market is None:
        return [p.name for p in _DAILY_PROVIDERS]
    return [p.name for p in _DAILY_PROVIDERS if "ALL" in p.markets or market in p.markets]


def list_index_providers() -> list[str]:
    """List registered index provider names."""
    return [p.name for p in _INDEX_PROVIDERS]


def daily_provider_chain(market: str | None = None) -> list[dict]:
    """Return ordered daily provider metadata for status and audits."""
    providers = _DAILY_PROVIDERS
    if market is not None:
        providers = [p for p in providers if "ALL" in p.markets or market in p.markets]
    return [
        {
            "name": provider.name,
            "markets": sorted(provider.markets),
            "priority": provider.priority,
            "cooldown_seconds": provider.cooldown_seconds,
            "data_type": provider.data_type,
            "observe_only": provider.observe_only,
            "health": dict(_health(provider.name)),
        }
        for provider in providers
    ]


def index_provider_chain(market: str | None = None) -> list[dict]:
    """Return ordered index provider metadata for status and audits."""
    providers = _INDEX_PROVIDERS
    if market is not None:
        providers = [p for p in providers if "ALL" in p.markets or market in p.markets]
    return [
        {
            "name": provider.name,
            "markets": sorted(provider.markets),
            "priority": provider.priority,
            "cooldown_seconds": provider.cooldown_seconds,
            "data_type": provider.data_type,
            "observe_only": provider.observe_only,
            "health": dict(_health(provider.name)),
        }
        for provider in providers
    ]


def provider_fallback_chains(market: str = "CN") -> dict:
    """Return M31 observable provider fallback chains."""
    return {
        "daily": daily_provider_chain(market),
        "index": index_provider_chain(market),
        "selection_rule": "lowest priority value first; observe-only and cooling providers are skipped",
    }


def _latest_bar_date(df: pd.DataFrame) -> str | None:
    """Return the newest bar date in a fetched frame as an ISO YYYY-MM-DD string."""
    if df is None or df.empty:
        return None
    latest = df.index.max()
    if hasattr(latest, "date"):
        return latest.date().isoformat()
    return str(latest)[:10]


def fetch_daily_with_fallback(
    symbol: str,
    market: str,
    days: int,
    *,
    expected_latest: str | None = None,
    strict: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Fetch daily bars from the first provider covering market that succeeds.

    expected_latest（ISO 日期）给定时启用新鲜度门：provider 返回非空但最新 bar
    早于该日期的结果视为「陈旧」，继续尝试下一家（不罚 cooldown——源没坏、只是
    滞后，这是有意为之：陈旧仍计入 provider success）。只有拿到 >= expected_latest
    的 bar 才立即采用。全链走完都陈旧时：strict=False（默认）fail-open，返回其中
    最新的一份并打显式 WARNING，绝不静默；strict=True 则 fail-closed，抛
    RuntimeError，供信号/实盘等不容忍陈旧数据的路径使用。

    expected_latest 给定时，无论走新鲜还是 fail-open 分支，都会在返回的 df 上
    附加 df.attrs["freshness"] = {"stale", "expected", "latest", "provider"}，
    让下游可以编程判断新鲜度而不必只靠日志。
    """
    errors: list[str] = []
    stale_best: tuple[pd.DataFrame, str, str] | None = None  # (df, provider, latest_date)
    for provider in _DAILY_PROVIDERS:
        if "ALL" not in provider.markets and market not in provider.markets:
            continue
        if provider.observe_only:
            _health(provider.name)["skipped"] += 1
            errors.append(f"{provider.name}: observe_only")
            continue
        if _provider_in_cooldown(provider.name):
            errors.append(f"{provider.name}: cooling")
            continue
        try:
            df = provider.fetch(symbol, days)
            if df is not None and not df.empty:
                _record_provider_success(provider.name)
                if expected_latest is None:
                    return df, provider.name
                latest = _latest_bar_date(df)
                if latest is not None and latest >= expected_latest:
                    df.attrs["freshness"] = {
                        "stale": False,
                        "expected": expected_latest,
                        "latest": latest,
                        "provider": provider.name,
                    }
                    return df, provider.name
                errors.append(f"{provider.name}: stale(latest={latest})")
                if stale_best is None or (latest or "") > stale_best[2]:
                    stale_best = (df, provider.name, latest or "")
                continue
            errors.append(f"{provider.name}: empty")
            _record_provider_failure(provider.name, "empty", provider.cooldown_seconds)
        except Exception as e:
            errors.append(f"{provider.name}: {e}")
            _record_provider_failure(provider.name, str(e), provider.cooldown_seconds)
    if stale_best is not None:
        df, name, latest = stale_best
        if strict:
            raise RuntimeError(
                f"daily freshness gate (strict): {symbol} 全部可用源均无 {expected_latest} bar "
                f"(best provider={name} latest={latest})"
            )
        logger.warning(
            "daily freshness gate: %s 全部可用源均无 %s bar，fail-open 返回最新可得 "
            "(provider=%s latest=%s)。下游不得把该数据当作当日 bar 使用。",
            symbol, expected_latest, name, latest,
        )
        df.attrs["freshness"] = {
            "stale": True,
            "expected": expected_latest,
            "latest": latest,
            "provider": name,
        }
        return df, name
    detail = "; ".join(errors) or f"no provider for market={market}"
    raise RuntimeError(f"daily data unavailable for {symbol}: {detail}")


def fetch_index_with_fallback(index_symbol: str, days: int, market: str = "CN") -> tuple[pd.DataFrame, str]:
    """Fetch index bars from the first index provider that succeeds."""
    errors: list[str] = []
    for provider in _INDEX_PROVIDERS:
        if "ALL" not in provider.markets and market not in provider.markets:
            continue
        if provider.observe_only:
            _health(provider.name)["skipped"] += 1
            errors.append(f"{provider.name}: observe_only")
            continue
        if _provider_in_cooldown(provider.name):
            errors.append(f"{provider.name}: cooling")
            continue
        try:
            df = provider.fetch(index_symbol, days)
            if df is not None and not df.empty:
                _record_provider_success(provider.name)
                return df, provider.name
            errors.append(f"{provider.name}: empty")
            _record_provider_failure(provider.name, "empty", provider.cooldown_seconds)
        except Exception as e:
            errors.append(f"{provider.name}: {e}")
            _record_provider_failure(provider.name, str(e), provider.cooldown_seconds)
    detail = "; ".join(errors) or f"no index provider for market={market}"
    raise RuntimeError(f"index data unavailable for {index_symbol}: {detail}")
