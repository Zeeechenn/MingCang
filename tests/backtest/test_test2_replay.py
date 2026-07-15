from backend.backtest.test2_models import Framework, PriceBar, Signal
from backend.backtest.test2_replay import replay, result_summary


def test_replay_uses_next_fillable_open_and_preserves_test2_position_contract():
    framework = Framework("C", "C", 0.0, 0.6, 0.4, 25.0)
    signals = [
        Signal("AAA", "A", "2026-07-16", 0, 60, 60, 90, 150),
        Signal("BBB", "B", "2026-07-16", 0, 55, 55, 90, 150),
        Signal("CCC", "C", "2026-07-16", 0, 50, 50, 90, 150),
    ]
    prices = {
        (symbol, "2026-07-17"): PriceBar(symbol, "2026-07-17", 100, 101, 99, 100)
        for symbol in ("AAA", "BBB", "CCC")
    }
    prices.update(
        {
            (symbol, "2026-07-20"): PriceBar(symbol, "2026-07-20", 101, 103, 100, 102)
            for symbol in ("AAA", "BBB", "CCC")
        }
    )

    result = replay(
        signals,
        prices,
        {"AAA", "BBB", "CCC"},
        frameworks={"C": framework},
        sectors={"AAA": "same", "BBB": "same", "CCC": "same"},
    )["C"]

    assert [holding.symbol for holding in result.open_holdings] == ["AAA", "BBB"]
    assert all(holding.entry_date == "2026-07-17" for holding in result.open_holdings)
    assert result_summary(result, prices)["open"] == 2


def test_neutral_recorded_day_advances_stop_loss_without_creating_entry():
    framework = Framework("C", "C", 0.0, 0.6, 0.4, 25.0)
    signals = [
        Signal("AAA", "A", "2026-07-16", 0, 100, 100, 95, 150),
        Signal("AAA", "A", "2026-07-20", 0, 0, 0, 95, 150),
    ]
    prices = {
        ("AAA", "2026-07-17"): PriceBar("AAA", "2026-07-17", 100, 101, 99, 100),
        ("AAA", "2026-07-20"): PriceBar("AAA", "2026-07-20", 96, 98, 94, 96),
    }

    result = replay(
        signals,
        prices,
        {"AAA"},
        frameworks={"C": framework},
    )["C"]

    assert not result.open_holdings
    assert result.closed_trades[0].exit_reason == "stop_loss"
    assert result.closed_trades[0].exit_price == 95
