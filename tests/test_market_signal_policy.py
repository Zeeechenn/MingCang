import pytest


def test_postmarket_batch_skips_hk_us_even_when_active(test_db, monkeypatch):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Stock

    monkeypatch.setattr(settings, "multimarket_gray_enabled", False)

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


def test_save_signal_refuses_known_hk_us_official_signal(test_db, monkeypatch):
    from backend.config import settings
    from backend.data.database import Stock
    from backend.decision.aggregator import save_signal

    monkeypatch.setattr(settings, "multimarket_gray_enabled", False)

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


def test_allowlisted_hk_signal_is_persisted_as_gray(test_db, monkeypatch):
    from backend.config import settings
    from backend.data.database import Signal, Stock
    from backend.decision.aggregator import save_signal
    from backend.decision.market_policy import is_signal_eligible_stock, signal_scope_for

    stock = Stock(symbol="700", name="腾讯控股", market="HK", active=True, lot_size=100)
    test_db.add(stock)
    test_db.commit()
    monkeypatch.setattr(settings, "multimarket_gray_enabled", True)
    monkeypatch.setattr(settings, "multimarket_gray_symbols", "HK:00700")

    assert signal_scope_for("HK", "700") == "gray"
    assert is_signal_eligible_stock(stock)
    save_signal(
        "700",
        "2026-07-14",
        {
            "breakdown": {"quant": 0, "technical": 12, "sentiment": 3},
            "composite_score": 9,
            "recommendation": "观望",
            "confidence": "中",
            "stop_loss": None,
            "take_profit": None,
        },
        test_db,
    )

    row = test_db.query(Signal).one()
    assert row.market == "HK"
    assert row.asset_key == "HK:00700"
    assert row.signal_scope == "gray"


def test_gray_allowlist_rejects_bad_market_keys(monkeypatch):
    from backend.config import settings

    with pytest.raises(ValueError, match="HK:<symbol>/US:<symbol>"):
        monkeypatch.setattr(settings, "multimarket_gray_symbols", "CN:600519")


def test_us_gray_analysis_clips_partial_bar_and_neutralizes_cn_model(monkeypatch):
    from types import SimpleNamespace

    import pandas as pd

    from backend import scheduler

    dates = pd.date_range("2026-03-01", periods=70, freq="D").strftime("%Y-%m-%d")
    frame = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1000},
        index=dates,
    )
    expected = dates[-2]
    monkeypatch.setattr("backend.data.market.load_price_df", lambda *args, **kwargs: frame)
    monkeypatch.setattr(
        "backend.analysis.qlib_engine.qlib_score",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CN model must not run")),
    )
    monkeypatch.setattr(scheduler, "_postmarket_news_sentiment", lambda *args, **kwargs: {"sentiment": 0.0})
    monkeypatch.setattr(
        "backend.analysis.technical.technical_score",
        lambda clipped, **kwargs: {
            "score": 0.0,
            "latest": {"close": 1.5, "atr14": 0.1},
            "latest_date": clipped.index[-1],
        },
    )
    monkeypatch.setattr(
        "backend.decision.aggregator.aggregate",
        lambda **kwargs: {
            "composite_score": 0.0,
            "recommendation": "观望",
            "confidence": "低",
            "stop_loss": 1.0,
            "take_profit": 2.0,
            "position_pct": 0.1,
            "breakdown": {"quant": 0.0, "technical": 0.0, "sentiment": 0.0},
            "rule_version": "test",
        },
    )

    stock = SimpleNamespace(symbol="AAPL", name="Apple", market="US", asset_key="US:AAPL")
    analysis = scheduler._analyze_postmarket_stock(
        stock,
        db=object(),
        context={
            "long_term_labels": {},
            "require_fresh_close": True,
            "expected_session": {"date": expected, "calendar_source": "test"},
        },
    )

    assert analysis["date"] == expected
    assert analysis["quant_result"] == {
        "score": 0.0,
        "model": "us_gray_neutral_quant_m67",
        "reason": "market_model_not_promoted",
    }
    assert analysis["result"]["execution_mode"] == "gray_shadow_only"
