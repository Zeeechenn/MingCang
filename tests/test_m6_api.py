def test_data_coverage_api_returns_report(test_db):
    from backend.api.routes import data_coverage
    from backend.data.database import Price, Stock

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", active=True))
    test_db.add(Price(symbol="600519", date="2026-01-01", open=1, high=1, low=1, close=1, volume=1))
    test_db.commit()

    report = data_coverage(db=test_db)

    assert report["summary"]["active_stocks"] == 1
    assert report["stocks"][0]["symbol"] == "600519"
