from __future__ import annotations

import pytest

from backend.backtest.nav_replay import (
    DailyBar,
    ReplayConfig,
    ReplayCostModel,
    SignalIntent,
    run_nav_replay,
)

ZERO_COST = ReplayCostModel(0, 0, 0, 0, 0, 0, 0, 0, minimum_commission=0)


def _bar(
    symbol: str,
    day: str,
    open_: float,
    *,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
) -> DailyBar:
    return DailyBar(
        symbol,
        day,
        open_,
        high if high is not None else open_ + 1,
        low if low is not None else open_ - 1,
        close if close is not None else open_,
    )


def _config(**overrides) -> ReplayConfig:
    values = {
        "initial_cash": 100_000,
        "target_position_weight": 0.15,
        "max_sector_weight": 0.30,
        "max_total_weight": 0.80,
        "max_positions": 3,
        "lot_size": 100,
        "entry_ttl_sessions": 1,
    }
    values.update(overrides)
    return ReplayConfig(**values)


def test_signal_at_close_fills_next_session_open_and_builds_cash_nav() -> None:
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60)],
        [
            _bar("AAA", "2026-07-01", 9, close=9),
            _bar("AAA", "2026-07-02", 10, close=11),
        ],
        config=_config(),
        costs=ZERO_COST,
    )

    fill = result["fills"][0]
    assert fill["date"] == "2026-07-02"
    assert fill["side"] == "buy"
    assert fill["shares"] == 1500
    assert result["summary"]["ending_nav"] == 101_500
    assert result["summary"]["total_return_pct"] == 1.5


def test_entry_day_stop_is_not_sellable_under_t_plus_one() -> None:
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60, stop_loss=9.5)],
        [
            _bar("AAA", "2026-07-01", 10),
            _bar("AAA", "2026-07-02", 10, low=9, close=9.8),
            _bar("AAA", "2026-07-03", 10, low=9, close=9.2),
        ],
        config=_config(),
        costs=ZERO_COST,
    )

    assert [fill["side"] for fill in result["fills"]] == ["buy", "sell"]
    assert result["fills"][1]["date"] == "2026-07-03"
    assert result["fills"][1]["reason"] == "stop_loss"


def test_gap_through_stop_uses_open_not_unreachable_stop_price() -> None:
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60, stop_loss=9.5)],
        [
            _bar("AAA", "2026-07-01", 10),
            _bar("AAA", "2026-07-02", 10, close=10),
            _bar("AAA", "2026-07-03", 8.5, high=9, low=8, close=8.8),
        ],
        config=_config(),
        costs=ZERO_COST,
    )

    sell = result["fills"][1]
    assert sell["reference_price"] == 8.5
    assert sell["execution_price"] == 8.5


def test_same_bar_stop_and_target_is_conservative() -> None:
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60, stop_loss=9, take_profit=11)],
        [
            _bar("AAA", "2026-07-01", 10),
            _bar("AAA", "2026-07-02", 10, close=10),
            _bar("AAA", "2026-07-03", 10, high=12, low=8, close=11),
        ],
        config=_config(),
        costs=ZERO_COST,
    )

    assert result["trades"][0]["exit_reason"] == "stop_loss_conservative"
    assert result["fills"][1]["reference_price"] == 9


def test_one_price_locked_next_session_expires_order() -> None:
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60)],
        [
            _bar("AAA", "2026-07-01", 9),
            _bar("AAA", "2026-07-02", 10, high=10, low=10, close=10),
            _bar("AAA", "2026-07-03", 11),
        ],
        config=_config(entry_ttl_sessions=1),
        costs=ZERO_COST,
    )

    assert result["fills"] == []
    assert result["rejections"] == [{
        "signal_date": "2026-07-01",
        "date": "2026-07-02",
        "symbol": "AAA",
        "reason": "one_price_locked",
    }]


def test_sector_cap_limits_same_sector_to_two_positions() -> None:
    symbols = ["AAA", "BBB", "CCC"]
    signals = [SignalIntent(symbol, "2026-07-01", 70 - index) for index, symbol in enumerate(symbols)]
    bars = [
        *[_bar(symbol, "2026-07-01", 10) for symbol in symbols],
        *[_bar(symbol, "2026-07-02", 10) for symbol in symbols],
    ]

    result = run_nav_replay(
        signals,
        bars,
        sectors={symbol: "same" for symbol in symbols},
        config=_config(),
        costs=ZERO_COST,
    )

    assert [fill["symbol"] for fill in result["fills"]] == ["AAA", "BBB"]
    assert result["rejections"][-1]["reason"] == "cash_or_exposure_cap"


def test_reversal_signal_exits_at_following_open() -> None:
    result = run_nav_replay(
        [
            SignalIntent("AAA", "2026-07-01", 60),
            SignalIntent("AAA", "2026-07-03", -30),
        ],
        [
            _bar("AAA", "2026-07-01", 10),
            _bar("AAA", "2026-07-02", 10),
            _bar("AAA", "2026-07-03", 11),
            _bar("AAA", "2026-07-04", 12),
        ],
        config=_config(reversal_min_hold_sessions=1),
        costs=ZERO_COST,
    )

    assert result["fills"][1]["date"] == "2026-07-04"
    assert result["fills"][1]["reason"] == "signal_reversal_next_open"


def test_cost_model_applies_minimum_commission_stamp_tax_and_slippage() -> None:
    costs = ReplayCostModel(
        commission_buy=0.0005,
        commission_sell=0.0005,
        tax_buy=0,
        tax_sell=0.001,
        regulatory_buy=0,
        regulatory_sell=0,
        slippage_buy=0.001,
        slippage_sell=0.001,
        minimum_commission=5,
    )
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60, take_profit=11)],
        [
            _bar("AAA", "2026-07-01", 10),
            _bar("AAA", "2026-07-02", 10, close=10),
            _bar("AAA", "2026-07-03", 11, high=12, low=10, close=11),
        ],
        config=_config(),
        costs=costs,
    )

    buy, sell = result["fills"]
    assert buy["execution_price"] == pytest.approx(10.01)
    assert sell["execution_price"] == pytest.approx(10.989)
    assert buy["fees"]["commission"] >= 5
    assert sell["fees"]["tax"] > 0
    assert result["summary"]["total_fees"] > 0
    assert result["summary"]["total_slippage"] > 0


def test_locked_stop_defers_exit_to_next_open() -> None:
    result = run_nav_replay(
        [SignalIntent("AAA", "2026-07-01", 60, stop_loss=9.5)],
        [
            _bar("AAA", "2026-07-01", 10),
            _bar("AAA", "2026-07-02", 10),
            _bar("AAA", "2026-07-03", 9, high=9, low=9, close=9),
            _bar("AAA", "2026-07-04", 8.5, high=9, low=8, close=8.8),
        ],
        config=_config(),
        costs=ZERO_COST,
    )

    assert result["fills"][1]["date"] == "2026-07-04"
    assert result["fills"][1]["reason"] == "stop_loss_deferred_locked"


def test_duplicate_or_invalid_bars_fail_closed() -> None:
    bar = _bar("AAA", "2026-07-01", 10)
    with pytest.raises(ValueError, match="duplicate price bar"):
        run_nav_replay([], [bar, bar], costs=ZERO_COST)
    with pytest.raises(ValueError, match="high is invalid"):
        run_nav_replay([], [_bar("AAA", "2026-07-01", 10, high=8)], costs=ZERO_COST)
