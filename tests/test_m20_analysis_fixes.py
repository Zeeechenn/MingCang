import pandas as pd


def test_latest_rsrs_z_returns_none_for_synthetic_collinear_ohlc():
    from backend.analysis.timing.rsrs import latest_rsrs_z

    close = pd.Series([3000 + i * 3 for i in range(140)], dtype=float)
    df = pd.DataFrame({
        "close": close,
        "high": close * 1.005,
        "low": close * 0.995,
    })

    assert latest_rsrs_z(df, window=18, zscore_lookback=80) is None


def test_check_limit_status_uses_board_specific_thresholds():
    from backend.analysis.technical import check_limit_status

    up_12 = pd.DataFrame({"close": [100.0, 112.0]})
    down_12 = pd.DataFrame({"close": [100.0, 88.0]})
    up_10 = pd.DataFrame({"close": [100.0, 110.0]})

    assert check_limit_status(up_12, symbol="300750")["limit_up"] is False
    assert check_limit_status(down_12, symbol="688981")["limit_down"] is False
    assert check_limit_status(up_10, symbol="600519")["limit_up"] is True
