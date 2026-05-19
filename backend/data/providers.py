"""Market/news data provider registry with fallback and short cooldowns."""
from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Callable

import pandas as pd


DailyFetcher = Callable[[str, int], pd.DataFrame]
IndexFetcher = Callable[[str, int], pd.DataFrame]


@dataclass(frozen=True)
class DailyProvider:
    name: str
    markets: set[str]
    fetch: DailyFetcher
    priority: int = 100
    cooldown_seconds: int = 0


@dataclass(frozen=True)
class IndexProvider:
    name: str
    fetch: IndexFetcher
    priority: int = 100
    cooldown_seconds: int = 0


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
    ))
    _DAILY_PROVIDERS.sort(key=lambda p: p.priority)
    _health(name)


def register_index_provider(
    name: str,
    fetch: IndexFetcher,
    *,
    priority: int = 100,
    cooldown_seconds: int = 0,
) -> None:
    """Register or replace an index OHLC provider."""
    global _INDEX_PROVIDERS
    _INDEX_PROVIDERS = [p for p in _INDEX_PROVIDERS if p.name != name]
    _INDEX_PROVIDERS.append(IndexProvider(
        name=name,
        fetch=fetch,
        priority=priority,
        cooldown_seconds=cooldown_seconds,
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


def fetch_daily_with_fallback(symbol: str, market: str, days: int) -> tuple[pd.DataFrame, str]:
    """Fetch daily bars from the first provider covering market that succeeds."""
    errors: list[str] = []
    for provider in _DAILY_PROVIDERS:
        if "ALL" not in provider.markets and market not in provider.markets:
            continue
        if _provider_in_cooldown(provider.name):
            errors.append(f"{provider.name}: cooling")
            continue
        try:
            df = provider.fetch(symbol, days)
            if df is not None and not df.empty:
                _record_provider_success(provider.name)
                return df, provider.name
            errors.append(f"{provider.name}: empty")
            _record_provider_failure(provider.name, "empty", provider.cooldown_seconds)
        except Exception as e:
            errors.append(f"{provider.name}: {e}")
            _record_provider_failure(provider.name, str(e), provider.cooldown_seconds)
    detail = "; ".join(errors) or f"no provider for market={market}"
    raise RuntimeError(f"daily data unavailable for {symbol}: {detail}")


def fetch_index_with_fallback(index_symbol: str, days: int) -> tuple[pd.DataFrame, str]:
    """Fetch index bars from the first index provider that succeeds."""
    errors: list[str] = []
    for provider in _INDEX_PROVIDERS:
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
    detail = "; ".join(errors) or "no index provider"
    raise RuntimeError(f"index data unavailable for {index_symbol}: {detail}")
