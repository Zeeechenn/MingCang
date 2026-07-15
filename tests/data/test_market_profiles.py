from datetime import UTC, date, datetime

import pytest


def test_market_profiles_keep_microstructure_distinct():
    from backend.data.market_profiles import get_market_profile

    cn = get_market_profile("CN")
    hk = get_market_profile("HK")
    us = get_market_profile("US")

    assert cn.currency == "CNY" and not cn.same_day_sell_allowed and cn.default_lot_size == 100
    assert hk.currency == "HKD" and hk.settlement_days == 2 and hk.default_lot_size is None
    assert us.currency == "USD" and us.settlement_days == 1 and us.fractional_supported
    assert len({cn.price_limit_model, hk.price_limit_model, us.price_limit_model}) == 3
    assert len({cn.costs.percentage_round_trip, hk.costs.percentage_round_trip, us.costs.percentage_round_trip}) == 3


@pytest.mark.parametrize(
    ("market", "raw", "expected", "key"),
    [
        ("CN", "600519.SH", "600519", "CN:600519"),
        ("HK", "700", "00700", "HK:00700"),
        ("HK", "0700.HK", "00700", "HK:00700"),
        ("US", "aapl.o", "AAPL", "US:AAPL"),
    ],
)
def test_symbol_identity_is_market_scoped(market, raw, expected, key):
    from backend.data.market_profiles import instrument_key, normalize_symbol

    assert normalize_symbol(raw, market) == expected
    assert instrument_key(market, raw) == key


def test_completed_session_uses_each_market_clock():
    from backend.data.market_profiles import expected_completed_session

    instant = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    cn = expected_completed_session("CN", instant)
    hk = expected_completed_session("HK", instant)
    us = expected_completed_session("US", instant)

    assert cn["date"] == "2026-07-15"
    assert hk["date"] == "2026-07-14"
    assert us["date"] == "2026-07-14"
    assert {cn["timezone"], hk["timezone"], us["timezone"]} == {
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "America/New_York",
    }


def test_weekend_is_not_a_session_even_without_optional_calendar():
    from backend.data.market_profiles import is_scheduled_session

    assert is_scheduled_session("CN", date(2026, 7, 18))[0] is False
    assert is_scheduled_session("HK", date(2026, 7, 18))[0] is False
    assert is_scheduled_session("US", date(2026, 7, 18))[0] is False


def test_backtest_costs_are_selected_by_market():
    from backend.backtest.costs import market_round_trip_cost, net_return_for_market

    costs = {market: market_round_trip_cost(market) for market in ("CN", "HK", "US")}
    assert costs["HK"] > costs["CN"] > costs["US"]
    assert net_return_for_market(0.05, "HK") == pytest.approx(0.05 - costs["HK"])
