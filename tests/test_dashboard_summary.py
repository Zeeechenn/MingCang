from datetime import datetime


def test_dashboard_summary_returns_operational_snapshot(monkeypatch, tmp_path, test_db):
    from backend.api.routes import dashboard_summary
    from backend.data.database import Price, Signal, Stock

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", industry="通信设备", active=True))
    test_db.add(Stock(symbol="603986", name="兆易创新", market="CN", industry="半导体", active=True))
    test_db.add(Price(symbol="300308", date="2026-05-15", open=100, high=110, low=99, close=108, volume=1))
    test_db.add(Price(symbol="603986", date="2026-05-15", open=100, high=104, low=96, close=102, volume=1))
    test_db.add(
        Signal(
            symbol="300308",
            date="2026-05-15",
            quant_score=-7.7,
            technical_score=22.5,
            sentiment_score=0.75,
            composite_score=28.5,
            recommendation="买入",
            confidence="中",
            stop_loss=990.15,
            take_profit=1262.49,
            rule_version="test1_legacy_qlib",
            created_at=datetime(2026, 5, 15, 16, 0),
        )
    )
    test_db.commit()

    summary = dashboard_summary(as_of="2026-05-16", db=test_db)

    assert "paper_trading" not in summary
    assert summary["coverage"]["summary"]["active_stocks"] == 2
    assert summary["signals"]["latest_date"] == "2026-05-15"
    assert summary["signals"]["entry_count"] == 1
    assert summary["signals"]["latest"][0]["symbol"] == "300308"
    assert summary["system"]["database_ok"] is True
