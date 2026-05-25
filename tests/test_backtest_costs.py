import math

from backend.backtest.costs import (
    A_SHARE_ROUND_TRIP_COST,
    annualized_sharpe,
    net_return,
    net_return_from_prices,
)


def test_net_return_applies_standard_a_share_round_trip_cost():
    assert A_SHARE_ROUND_TRIP_COST == 0.004
    assert net_return(0.05) == 0.046
    assert round(net_return_from_prices(100, 105), 6) == 0.046


def test_annualized_sharpe_uses_average_hold_days():
    returns = [0.05, -0.01, 0.03]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    expected = mean / math.sqrt(variance) * math.sqrt(252 / 5)

    assert round(annualized_sharpe(returns, avg_hold_days=5), 10) == round(expected, 10)
