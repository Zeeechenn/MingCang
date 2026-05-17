from datetime import datetime, timedelta


def test_data_coverage_report_counts_core_tables(test_db):
    from backend.data.database import FinancialMetric, NewsItem, Price, Stock
    from backend.data.quality import build_data_coverage_report

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True))
    for i in range(3):
        test_db.add(Price(
            symbol="600519",
            date=f"2026-01-0{i + 1}",
            open=1,
            high=2,
            low=1,
            close=2,
            volume=1000,
        ))
    test_db.add(FinancialMetric(symbol="600519", report_date="2025-12-31", disclosure_date="2026-03-20"))
    test_db.add(NewsItem(
        symbol="600519",
        title="news",
        url="https://example.com/n",
        published_at=datetime.utcnow() - timedelta(hours=1),
        source="x",
    ))
    test_db.commit()

    report = build_data_coverage_report(test_db)

    assert report["summary"]["active_stocks"] == 1
    assert report["summary"]["price_covered"] == 1
    assert report["summary"]["financial_covered"] == 1
    assert report["summary"]["news_24h_covered"] == 1
    assert report["stocks"][0]["price_rows"] == 3
    assert report["stocks"][0]["latest_financial_report"] == "2025-12-31"


def test_provider_health_records_success_and_failure():
    from backend.data.providers import (
        fetch_daily_with_fallback,
        get_provider_health,
        register_daily_provider,
        reset_provider_health,
    )

    reset_provider_health()

    def bad(symbol, days):
        raise RuntimeError("down")

    def good(symbol, days):
        import pandas as pd
        return pd.DataFrame([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    register_daily_provider("m6_bad", {"M6"}, bad)
    register_daily_provider("m6_good", {"M6"}, good)

    _, provider = fetch_daily_with_fallback("X", "M6", 1)
    health = get_provider_health()

    assert provider == "m6_good"
    assert health["m6_bad"]["failures"] == 1
    assert health["m6_good"]["successes"] == 1
