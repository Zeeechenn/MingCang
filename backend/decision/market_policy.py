"""Market eligibility policy for official StockSage signal workflows."""
from __future__ import annotations

PRODUCTION_SIGNAL_MARKETS = frozenset({"CN"})


def is_production_signal_market(market: str | None) -> bool:
    """Return whether a market is eligible for official signal generation."""
    return str(market or "").upper() in PRODUCTION_SIGNAL_MARKETS


def is_production_signal_eligible_stock(stock) -> bool:
    """Return whether a Stock-like object can enter official signal workflows."""
    return bool(getattr(stock, "active", False)) and is_production_signal_market(getattr(stock, "market", None))


def production_signal_policy_payload() -> dict:
    """Return a small API/report payload describing the current signal boundary."""
    return {
        "production_signal_markets": sorted(PRODUCTION_SIGNAL_MARKETS),
        "observe_only_markets": ["HK", "US"],
        "rule": "HK/US data may be used for read-only research context, but official signals remain CN-only.",
    }
