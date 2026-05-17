"""Market/news data provider registry with simple fallback semantics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


DailyFetcher = Callable[[str, int], pd.DataFrame]


@dataclass(frozen=True)
class DailyProvider:
    name: str
    markets: set[str]
    fetch: DailyFetcher


_DAILY_PROVIDERS: list[DailyProvider] = []
_PROVIDER_HEALTH: dict[str, dict] = {}


def register_daily_provider(name: str, markets: set[str], fetch: DailyFetcher) -> None:
    """Register or replace a daily OHLCV provider."""
    global _DAILY_PROVIDERS
    _DAILY_PROVIDERS = [p for p in _DAILY_PROVIDERS if p.name != name]
    _DAILY_PROVIDERS.append(DailyProvider(name=name, markets=markets, fetch=fetch))
    _PROVIDER_HEALTH.setdefault(name, {"successes": 0, "failures": 0, "last_error": None})


def reset_provider_health() -> None:
    """Clear in-process provider health counters."""
    _PROVIDER_HEALTH.clear()


def get_provider_health() -> dict[str, dict]:
    """Return provider success/failure counters."""
    return {name: dict(stats) for name, stats in _PROVIDER_HEALTH.items()}


def _record_provider_success(name: str) -> None:
    stats = _PROVIDER_HEALTH.setdefault(name, {"successes": 0, "failures": 0, "last_error": None})
    stats["successes"] += 1
    stats["last_error"] = None


def _record_provider_failure(name: str, error: str) -> None:
    stats = _PROVIDER_HEALTH.setdefault(name, {"successes": 0, "failures": 0, "last_error": None})
    stats["failures"] += 1
    stats["last_error"] = error


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
        try:
            df = provider.fetch(symbol, days)
            if df is not None and not df.empty:
                _record_provider_success(provider.name)
                return df, provider.name
            errors.append(f"{provider.name}: empty")
            _record_provider_failure(provider.name, "empty")
        except Exception as e:
            errors.append(f"{provider.name}: {e}")
            _record_provider_failure(provider.name, str(e))
    detail = "; ".join(errors) or f"no provider for market={market}"
    raise RuntimeError(f"daily data unavailable for {symbol}: {detail}")
