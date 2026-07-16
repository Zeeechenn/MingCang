"""run_premarket 新鲜度门接线：CN 市场应把 expected_trade_date() 结果传给
backfill_if_needed(expected_latest=...)；expected_trade_date 失败时不阻塞盘前任务。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def cn_stock(test_db):
    from backend.data.database import Stock

    stock = Stock(symbol="600519", name="贵州茅台", market="CN", industry="食品饮料", active=True)
    test_db.add(stock)
    test_db.commit()
    return stock


def _stub_side_effects(monkeypatch):
    """把新闻/基本面/指数同步都短路掉，只关注 backfill_if_needed 的调用参数。"""
    monkeypatch.setattr("backend.data.news.fetch_stock_news", lambda *a, **kw: [])
    monkeypatch.setattr("backend.data.news.save_news_to_db", lambda *a, **kw: 0)
    monkeypatch.setattr(
        "backend.data.fundamentals.sync_financial_metrics_for_market", lambda *a, **kw: 0
    )
    monkeypatch.setattr("backend.data.market.sync_market_index_to_db", lambda *a, **kw: 0)


def test_cn_passes_expected_latest_to_backfill(monkeypatch, test_db, cn_stock):
    from backend.jobs import premarket

    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    _stub_side_effects(monkeypatch)
    monkeypatch.setattr(
        "backend.data.freshness.expected_trade_date", lambda db, **kw: ("2026-07-16", "anchor")
    )

    calls = []

    def _fake_backfill(symbol, market, db, **kwargs):
        calls.append((symbol, market, kwargs))
        return 0

    monkeypatch.setattr("backend.data.market.backfill_if_needed", _fake_backfill)

    result = premarket.run_premarket(market="CN")

    assert len(calls) == 1
    symbol, market, kwargs = calls[0]
    assert symbol == "600519"
    assert market == "CN"
    assert kwargs["expected_latest"] == "2026-07-16"
    assert kwargs["refresh_today"] is True
    assert result["errors"] == 0


def test_expected_trade_date_failure_does_not_block(monkeypatch, test_db, cn_stock):
    from backend.jobs import premarket

    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    _stub_side_effects(monkeypatch)

    def _boom(db, **kw):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("backend.data.freshness.expected_trade_date", _boom)

    calls = []

    def _fake_backfill(symbol, market, db, **kwargs):
        calls.append((symbol, market, kwargs))
        return 0

    monkeypatch.setattr("backend.data.market.backfill_if_needed", _fake_backfill)

    result = premarket.run_premarket(market="CN")

    assert len(calls) == 1
    symbol, market, kwargs = calls[0]
    assert kwargs.get("expected_latest") is None
    assert result["errors"] == 0
