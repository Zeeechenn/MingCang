import pandas as pd


def test_market_snapshot_point_in_time_join(test_db):
    from backend.data.database import MarketSnapshot
    from backend.data.market_features import attach_market_features

    test_db.add(MarketSnapshot(
        symbol="600519",
        date="2026-01-02",
        market_cap=1000.0,
        float_market_cap=800.0,
        shares_outstanding=100.0,
        north_net_buy=5.0,
        margin_balance=20.0,
        large_order_net_inflow=3.0,
    ))
    test_db.add(MarketSnapshot(
        symbol="600519",
        date="2026-01-05",
        market_cap=1200.0,
        float_market_cap=900.0,
        shares_outstanding=100.0,
        north_net_buy=-1.0,
        margin_balance=25.0,
        large_order_net_inflow=-2.0,
    ))
    test_db.commit()

    df = pd.DataFrame({"date": ["2026-01-03", "2026-01-06"], "close": [10.0, 12.0]})
    out = attach_market_features(df, "600519", test_db)

    assert out.loc[0, "market_cap"] == 1000.0
    assert out.loc[0, "north_net_buy"] == 5.0
    assert out.loc[1, "market_cap"] == 1200.0
    assert out.loc[1, "large_order_net_inflow"] == -2.0


def test_qlib_features_include_market_and_flow_columns():
    from backend.data.qlib_data import FEATURE_COLS

    assert "log_market_cap" in FEATURE_COLS
    assert "north_net_buy" in FEATURE_COLS
    assert "margin_balance" in FEATURE_COLS
    assert "large_order_net_inflow" in FEATURE_COLS
