"""Shared backtest cost and metric helpers."""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

A_SHARE_BUY_COMMISSION = 0.0005
A_SHARE_SELL_COMMISSION = 0.0005
A_SHARE_STAMP_TAX = 0.001
A_SHARE_SLIPPAGE_PER_SIDE = 0.001

A_SHARE_ROUND_TRIP_COST = (
    A_SHARE_BUY_COMMISSION
    + A_SHARE_SELL_COMMISSION
    + A_SHARE_STAMP_TAX
    + A_SHARE_SLIPPAGE_PER_SIDE * 2
)


def net_return(gross_return: float, *, round_trip_cost: float = A_SHARE_ROUND_TRIP_COST) -> float:
    """Convert a gross trade return to an approximate net return after A-share round-trip costs."""
    return gross_return - round_trip_cost


def gross_return(entry_price: float, exit_price: float) -> float:
    """Return simple gross percentage return from entry to exit."""
    return (exit_price - entry_price) / entry_price if entry_price else 0.0


def net_return_from_prices(entry_price: float, exit_price: float) -> float:
    """Return net trade return from entry/exit prices using the project standard A-share cost model."""
    return net_return(gross_return(entry_price, exit_price))


def annualized_sharpe(returns: Sequence[float], *, avg_hold_days: float) -> float:
    """Annualize per-trade returns by average holding days."""
    if not returns:
        return 0.0
    stdev = statistics.pstdev(returns)
    if stdev <= 0:
        return 0.0
    mean = statistics.mean(returns)
    return mean / stdev * math.sqrt(252 / max(avg_hold_days, 1))
