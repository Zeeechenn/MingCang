"""
Example: minimal MingCang data provider plugin.

This file shows how to write a custom daily-price provider and register it
with MingCang's provider registry so it participates in the fallback chain.

The real registry interface lives in backend/data/providers.py.
Copy this file into your project, adjust the fetch logic, then call
register_daily_provider() before the backend starts fetching data.

Requirements for a DailyProvider fetch function:
    - Accepts (symbol: str, days: int) -> pd.DataFrame
    - Returns a DataFrame with at least these columns:
        date (str "YYYY-MM-DD"), open, high, low, close, volume
    - Returns an EMPTY DataFrame (not None, not an exception) when the symbol
      is not available from this source — the registry will then try the next
      provider in priority order.
    - Raises an exception only on hard errors (network failure, auth failure)
      that should be recorded as a provider failure and trigger the cooldown.

Priority: lower number = tried first.  Built-in providers typically use
priority 100.  Set a lower value (e.g. 50) to prefer your provider, or a
higher value (e.g. 200) to use it as a fallback of last resort.

The observe_only flag (default False) marks a provider as "never called in
production" — it participates in health reporting but is skipped during live
fallback resolution.  Useful for canary or experimental providers.
"""

from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------------------
# 1.  Write your fetch function.
# ---------------------------------------------------------------------------

def fetch_my_daily(symbol: str, days: int) -> pd.DataFrame:
    """
    Return the last `days` rows of daily OHLCV data for `symbol`.

    Replace this stub with a real data source: a local CSV, an internal API,
    a paid market-data vendor, etc.

    Must NOT call any live API in this example file — keep examples offline.
    """
    # Example: return a static stub row so this file is importable offline.
    # In a real provider, call your data source here and return real data.
    stub_rows = [
        {
            "date": "2026-06-03",
            "open": 120.0,
            "high": 127.5,
            "low": 119.8,
            "close": 126.8,
            "volume": 1_250_000,
        }
    ]
    # Return empty DataFrame if symbol not covered by this provider.
    if symbol not in {"300308"}:          # <-- adjust your coverage set
        return pd.DataFrame()

    return pd.DataFrame(stub_rows)


# ---------------------------------------------------------------------------
# 2.  Register your provider.
# ---------------------------------------------------------------------------
# Call this function once at application startup, before the backend begins
# processing requests.  A natural place is in your app's lifespan handler or
# in a plugin module that is imported during backend initialisation.
#
# In the MingCang codebase, built-in providers are registered in
# backend/data/market.py (for Tushare / TickFlow) and similar modules.

def register() -> None:
    """Register this provider with the MingCang provider registry."""
    from backend.data.providers import register_daily_provider  # noqa: PLC0415

    register_daily_provider(
        name="my_provider",
        markets={"CN"},           # set of market codes this provider covers
        fetch=fetch_my_daily,
        priority=150,             # tried after built-in providers (priority 100)
        cooldown_seconds=60,      # wait 60s after a failure before retrying
        data_type="daily_price",
        observe_only=False,       # set True to disable in live fallback chain
    )
    print("[my_provider] Registered as a daily provider (priority=150, markets={'CN'})")


# ---------------------------------------------------------------------------
# 3.  Verify standalone (no backend import needed).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    df = fetch_my_daily("300308", 5)
    print("Stub fetch result:")
    print(df.to_string(index=False))
    print()
    print("To register with MingCang, call my_provider.register() at startup.")
    print("See examples/provider_plugin/README.md for integration steps.")
