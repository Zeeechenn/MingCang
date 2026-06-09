def test_demo_seed_populates_first_screen_data(monkeypatch, test_db):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from scripts import demo_seed

    from backend.api.routes.dashboard import dashboard_summary
    from backend.api.routes.watchlist import get_watchlist
    from backend.data.database import IndexPrice, Position, Price, Signal

    demo_seed._upsert_stocks(test_db)
    demo_seed._upsert_demo_market_rows(test_db)
    demo_seed._upsert_demo_position(test_db)
    demo_seed._upsert_demo_market_rows(test_db)
    demo_seed._upsert_demo_position(test_db)

    assert test_db.query(Price).count() == 12
    assert test_db.query(IndexPrice).count() == 4
    assert test_db.query(Signal).count() == 3
    assert test_db.query(Position).count() == 1

    summary = dashboard_summary(db=test_db)
    assert summary["signals"]["latest_date"] == "2026-06-03"
    assert len(summary["signals"]["latest"]) == 3
    assert summary["market_overview"]["available"] is True
    assert summary["positions"]["count"] == 1
    assert summary["positions"]["items"][0]["latest_price"] == 126.8

    watchlist = get_watchlist(db=test_db)
    assert {item.symbol for item in watchlist} == {"600519", "300308", "601318"}
    assert all(item.latest_signal is not None for item in watchlist)
