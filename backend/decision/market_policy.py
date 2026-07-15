"""Market eligibility policy for official MingCang signal workflows."""
from __future__ import annotations

PRODUCTION_SIGNAL_MARKETS = frozenset({"CN"})
OBSERVE_ONLY_MARKETS = frozenset({"HK", "US"})


def is_production_signal_market(market: str | None) -> bool:
    """Return whether a market is eligible for official signal generation."""
    return str(market or "").upper() in PRODUCTION_SIGNAL_MARKETS


def is_production_signal_eligible_stock(stock) -> bool:
    """Return whether a Stock-like object can enter official signal workflows."""
    return bool(getattr(stock, "active", False)) and is_production_signal_market(getattr(stock, "market", None))


def signal_scope_for(market: str | None, symbol: str | None = None) -> str:
    """Return production, gray, or observe_only for a market-scoped instrument."""
    normalized_market = str(market or "").upper()
    if normalized_market in PRODUCTION_SIGNAL_MARKETS:
        return "production"
    if normalized_market not in OBSERVE_ONLY_MARKETS or not symbol:
        return "observe_only"
    from backend.config import settings
    from backend.data.market_profiles import instrument_key

    key = instrument_key(normalized_market, symbol)
    if settings.multimarket_gray_enabled and key in settings.multimarket_gray_asset_keys:
        return "gray"
    return "observe_only"


def is_signal_eligible_stock(stock) -> bool:
    """Allow CN production plus explicitly allowlisted HK/US gray instruments."""
    return bool(getattr(stock, "active", False)) and signal_scope_for(
        getattr(stock, "market", None),
        getattr(stock, "symbol", None),
    ) in {"production", "gray"}


def production_signal_policy_payload() -> dict:
    """Return a small API/report payload describing the current signal boundary."""
    from backend.config import settings

    return {
        "production_signal_markets": sorted(PRODUCTION_SIGNAL_MARKETS),
        "observe_only_markets": sorted(OBSERVE_ONLY_MARKETS),
        "gray_enabled": settings.multimarket_gray_enabled,
        "gray_asset_keys": sorted(settings.multimarket_gray_asset_keys),
        "rule": "CN is production; HK/US require an explicit symbol allowlist and remain gray until promotion.",
    }
