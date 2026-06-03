import pytest


def test_postmarket_batch_skips_hk_us_even_when_active(test_db, monkeypatch):
    from backend import scheduler
    from backend.data.database import Stock

    for stock in [
        Stock(symbol="600519", name="贵州茅台", market="CN", active=True),
        Stock(symbol="700", name="腾讯控股", market="HK", active=True),
        Stock(symbol="AAPL", name="Apple", market="US", active=True),
    ]:
        test_db.add(stock)
    test_db.commit()

    analyzed = []
    persisted = []

    def fake_analyze(stock, db, context):
        analyzed.append(stock.symbol)
        return {
            "date": "2026-06-01",
            "result": {
                "recommendation": "观望",
                "confidence": "中",
                "composite_score": 10,
                "position_pct": 0,
                "breakdown": {"quant": 0, "technical": 10, "sentiment": 0},
                "stop_loss": None,
                "take_profit": None,
            },
            "quant_result": {"score": 0, "model": "fake"},
            "technical_result": {"score": 10},
            "sentiment_result": {"sentiment": 0},
        }

    monkeypatch.setattr(scheduler, "_load_postmarket_context", lambda db, stocks: {})
    monkeypatch.setattr(scheduler, "_analyze_postmarket_stock", fake_analyze)
    monkeypatch.setattr(scheduler, "_apply_portfolio_decision", lambda batch_items, db: 0)
    monkeypatch.setattr(
        scheduler,
        "_persist_postmarket_stock",
        lambda stock, analysis, db: persisted.append(stock.symbol),
    )
    monkeypatch.setattr(scheduler, "_maybe_send_postmarket_alert", lambda stock, result: False)
    monkeypatch.setattr(scheduler, "_run_kill_switch_checks", lambda db: None)

    stats = scheduler.run_postmarket_batch(test_db)

    assert analyzed == ["600519"]
    assert persisted == ["600519"]
    assert stats["input_stocks"] == 3
    assert stats["stocks"] == 1
    assert stats["market_skipped"] == 2


def test_save_signal_refuses_known_hk_us_official_signal(test_db):
    from backend.data.database import Stock
    from backend.decision.aggregator import save_signal

    test_db.add(Stock(symbol="700", name="腾讯控股", market="HK", active=True))
    test_db.commit()

    result = {
        "breakdown": {"quant": 0, "technical": 10, "sentiment": 0},
        "composite_score": 10,
        "recommendation": "观望",
        "confidence": "中",
        "stop_loss": None,
        "take_profit": None,
    }

    with pytest.raises(ValueError) as exc:
        save_signal("700", "2026-06-01", result, test_db)

    assert "CN-only" in str(exc.value)


def test_portfolio_weights_ignore_hk_us_observe_only_positions(test_db, monkeypatch):
    from backend import scheduler
    from backend.data.database import Position, Price, Stock

    for stock in [
        Stock(symbol="600519", name="贵州茅台", market="CN", active=True),
        Stock(symbol="700", name="腾讯控股", market="HK", active=True),
        Stock(symbol="AAPL", name="Apple", market="US", active=True),
    ]:
        test_db.add(stock)
    for symbol, close in [("600519", 100), ("700", 300), ("AAPL", 200)]:
        test_db.add(
            Price(symbol=symbol, date="2026-06-01", open=close, high=close, low=close, close=close, volume=1)
        )
    test_db.add(
        Position(
            symbol="600519",
            name="贵州茅台",
            market="CN",
            quantity=10,
            avg_cost=100,
            opened_at="2026-06-01",
            status="open",
        )
    )
    test_db.add(
        Position(
            symbol="700",
            name="腾讯控股",
            market="HK",
            quantity=100,
            avg_cost=300,
            opened_at="2026-06-01",
            status="open",
        )
    )
    test_db.add(
        Position(
            symbol="AAPL",
            name="Apple",
            market="US",
            quantity=100,
            avg_cost=200,
            opened_at="2026-06-01",
            status="open",
        )
    )
    test_db.commit()

    monkeypatch.setattr(scheduler.settings, "max_total_equity_pct", 0.8)

    weights = scheduler._open_position_weights(test_db)

    assert weights == {"600519": 0.8}
