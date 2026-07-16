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


def test_dashboard_summary_dedupes_same_day_timestamp_batches(monkeypatch, tmp_path, test_db):
    """同一信号日内多个时间戳批次（test2/live 常见）不应被误判成不同信号日，
    也不应把同一支股票的旧批次和新批次一起返回。"""
    from backend.api.routes import dashboard_summary
    from backend.data.database import Price, Signal, Stock

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", industry="通信设备", active=True))
    test_db.add(Stock(symbol="603986", name="兆易创新", market="CN", industry="半导体", active=True))
    test_db.add(Price(symbol="300308", date="2026-07-16", open=100, high=110, low=99, close=108, volume=1))
    test_db.add(Price(symbol="603986", date="2026-07-16", open=100, high=104, low=96, close=102, volume=1))
    # 300308 当日两批：早盘 00:17 旧分 + 16:25 深评新分（同支同日多批，靠时间戳区分）
    test_db.add(
        Signal(
            symbol="300308",
            date="2026-07-16T00:17+08:00",
            composite_score=10.0,
            recommendation="观望",
            confidence="中",
            created_at=datetime(2026, 7, 16, 0, 17),
        )
    )
    test_db.add(
        Signal(
            symbol="300308",
            date="2026-07-16T16:25+08:00",
            composite_score=50.0,
            recommendation="买入",
            confidence="高",
            created_at=datetime(2026, 7, 16, 16, 25),
        )
    )
    # 603986 老式纯日期批次（生产日任务风格）
    test_db.add(
        Signal(
            symbol="603986",
            date="2026-07-16",
            composite_score=20.0,
            recommendation="观望",
            confidence="中",
            created_at=datetime(2026, 7, 16, 15, 0),
        )
    )
    test_db.commit()

    summary = dashboard_summary(as_of="2026-07-17", db=test_db)

    assert summary["signals"]["latest_date"] == "2026-07-16"
    symbols_returned = [row["symbol"] for row in summary["signals"]["latest"]]
    assert symbols_returned.count("300308") == 1
    top = summary["signals"]["latest"][0]
    assert top["symbol"] == "300308"
    assert top["composite_score"] == 50.0
    assert summary["signals"]["entry_count"] == 1
