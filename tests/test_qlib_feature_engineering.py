from datetime import datetime

import pandas as pd


def test_qlib_features_include_liquidity_and_reversal():
    from backend.data.qlib_data import FEATURE_COLS, _build_features

    df = pd.DataFrame({
        "open": range(1, 101),
        "high": range(2, 102),
        "low": range(0, 100),
        "close": range(1, 101),
        "volume": [1000 + i for i in range(100)],
    })
    features = _build_features(df)

    assert "rev_10" in FEATURE_COLS
    assert "amihud_20" in FEATURE_COLS
    assert "volatility_20" in features.columns
    assert features[FEATURE_COLS].iloc[-1].notna().all()


def test_neutralize_by_date_industry():
    from backend.data.qlib_data import neutralize_by_date_industry

    df = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-01", "2026-01-01"],
        "industry": ["电子", "电子", "银行"],
        "mom_5": [1.0, 3.0, 10.0],
    })

    out = neutralize_by_date_industry(df, factor_cols=["mom_5"])

    assert out.loc[0, "mom_5"] == -1.0
    assert out.loc[1, "mom_5"] == 1.0
    assert out.loc[2, "mom_5"] == 0.0


def test_build_training_data_does_not_auto_neutralize(test_db):
    import importlib

    import backend.data.qlib_data as qlib_data
    from backend.data.database import Price, Stock

    qlib_data = importlib.reload(qlib_data)
    fetched_at = datetime(2026, 5, 31, 12, 0, 0)

    for symbol, industry, base in [("600519", "食品饮料", 10), ("300308", "电子", 20)]:
        test_db.add(Stock(symbol=symbol, name=symbol, market="CN", industry=industry, active=True))
        for i in range(130):
            price = base + i
            test_db.add(Price(
                symbol=symbol,
                date=(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000 + i,
                source="unit_provider",
                fetched_at=fetched_at,
                adjustment="qfq",
            ))
    test_db.commit()

    df = qlib_data.build_training_data(test_db)

    assert not df.empty
    assert df["mom_5"].abs().sum() > 0
    assert set(["_price_source", "_price_fetched_at", "_price_adjustment"]).issubset(df.columns)
    assert df["_price_source"].eq("unit_provider").all()
    assert df["_price_adjustment"].eq("qfq").all()


def test_build_training_data_adds_point_in_time_fundamental_features(test_db):
    import importlib

    import backend.data.qlib_data as qlib_data
    from backend.data.database import FinancialMetric, Price, Stock

    qlib_data = importlib.reload(qlib_data)

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True))
    test_db.add(FinancialMetric(
        symbol="600519",
        report_date="2025-12-31",
        revenue_yoy=12.5,
        net_profit_yoy=18.0,
        gross_margin=52.0,
        roe=20.0,
        asset_turnover=0.8,
    ))
    test_db.add(FinancialMetric(
        symbol="600519",
        report_date="2026-03-31",
        revenue_yoy=22.5,
        net_profit_yoy=28.0,
        gross_margin=55.0,
        roe=24.0,
        asset_turnover=0.9,
    ))
    for i in range(150):
        price = 100 + i
        test_db.add(Price(
            symbol="600519",
            date=(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=1000 + i,
        ))
    test_db.commit()

    df = qlib_data.build_training_data(test_db)

    assert {"roe", "revenue_yoy", "net_profit_yoy", "gross_margin", "asset_turnover"} <= set(qlib_data.FEATURE_COLS)
    before_q1 = df[df["date"] < "2026-03-31"].iloc[-1]
    after_q1 = df[df["date"] >= "2026-03-31"].iloc[0]
    assert before_q1["roe"] == 20.0
    assert before_q1["revenue_yoy"] == 12.5
    assert after_q1["roe"] == 24.0
    assert after_q1["revenue_yoy"] == 22.5


def test_build_inference_features_can_attach_latest_fundamentals(test_db):
    import importlib

    import backend.data.qlib_data as qlib_data
    from backend.data.database import FinancialMetric

    qlib_data = importlib.reload(qlib_data)
    test_db.add(FinancialMetric(
        symbol="600519",
        report_date="2026-03-31",
        revenue_yoy=22.5,
        net_profit_yoy=28.0,
        gross_margin=55.0,
        roe=24.0,
        asset_turnover=0.9,
    ))
    test_db.commit()
    df = pd.DataFrame({
        "date": [(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(130)],
        "open": range(1, 131),
        "high": range(2, 132),
        "low": range(0, 130),
        "close": range(1, 131),
        "volume": [1000 + i for i in range(130)],
    }).set_index("date")

    feats = qlib_data.build_inference_features(df, symbol="600519", db=test_db)

    assert feats["roe"] == 24.0
    assert feats["revenue_yoy"] == 22.5


def test_training_data_uses_disclosure_date_when_available(test_db):
    import importlib

    import backend.data.qlib_data as qlib_data
    from backend.data.database import FinancialMetric, Price, Stock

    qlib_data = importlib.reload(qlib_data)
    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True))
    test_db.add(FinancialMetric(
        symbol="600519",
        report_date="2026-03-31",
        disclosure_date="2026-04-30",
        roe=30.0,
        revenue_yoy=30.0,
    ))
    for i in range(160):
        price = 100 + i
        test_db.add(Price(
            symbol="600519",
            date=(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
            open=price,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=1000 + i,
        ))
    test_db.commit()

    df = qlib_data.build_training_data(test_db)

    assert df[df["date"] < "2026-04-30"]["roe"].max() == 0.0
    assert df[df["date"] >= "2026-04-30"]["roe"].max() == 30.0
