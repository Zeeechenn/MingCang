import pandas as pd


def test_validation_panel_uses_training_feature_pipeline(test_db):
    from backend.backtest.alphalens_qlib import load_panel
    from backend.data.database import FinancialMetric, Price, Stock

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True))
    test_db.add(FinancialMetric(symbol="600519", report_date="2026-03-31", roe=24.0, revenue_yoy=22.5))
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

    panel = load_panel(test_db)

    assert not panel.empty
    assert "roe" in panel.columns
    assert panel["roe"].max() == 24.0
