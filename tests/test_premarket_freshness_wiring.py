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
    assert "strict_basis_write_guard" not in kwargs
    assert "factor_warmup_rows" not in kwargs
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


def test_protected_price_refresh_is_opt_in_and_uses_fixed_cutoff_with_warmup(
    monkeypatch, test_db, cn_stock
):
    from backend.jobs import premarket

    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    _stub_side_effects(monkeypatch)
    monkeypatch.setattr(
        "backend.data.freshness.expected_trade_date", lambda db, **kw: ("2026-07-16", "anchor")
    )
    calls = []

    def _fake_backfill(symbol, market, db, **kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr("backend.data.market.backfill_if_needed", _fake_backfill)

    result = premarket.run_premarket(market="CN", protected_price_refresh=True)

    assert result["errors"] == 0
    assert calls == [
        {
            "refresh_today": True,
            "expected_latest": "2026-07-16",
            "strict_basis_write_guard": True,
            "factor_warmup_rows": 240,
        }
    ]
    assert result["protected_price_refresh"] == {
        "status": "complete",
        "rows_written": 0,
        "completed_symbols": 1,
        "blocked_symbols": [],
    }


def test_protected_price_refresh_reports_blocked_symbol_without_false_success(
    monkeypatch, test_db, cn_stock
):
    from backend.data.market_persistence import PriceBasisWriteBlocked
    from backend.jobs import premarket

    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    _stub_side_effects(monkeypatch)
    monkeypatch.setattr(
        "backend.data.freshness.expected_trade_date", lambda db, **kw: ("2026-07-16", "anchor")
    )

    def blocked(*args, **kwargs):
        raise PriceBasisWriteBlocked("mixed stored provenance")

    monkeypatch.setattr("backend.data.market.backfill_if_needed", blocked)
    result = premarket.run_premarket(market="CN", protected_price_refresh=True)

    assert result["errors"] == 1
    assert result["protected_price_refresh"] == {
        "status": "blocked",
        "rows_written": 0,
        "completed_symbols": 0,
        "blocked_symbols": [
            {"symbol": "600519", "reason": "mixed stored provenance"}
        ],
    }


def test_protected_price_refresh_reports_partial_success_explicitly(
    monkeypatch, test_db, cn_stock
):
    from backend.data.database import Stock
    from backend.data.market_persistence import PriceBasisWriteBlocked
    from backend.jobs import premarket

    test_db.add(
        Stock(symbol="000001", name="平安银行", market="CN", industry="银行", active=True)
    )
    test_db.commit()
    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    _stub_side_effects(monkeypatch)
    monkeypatch.setattr(
        "backend.data.freshness.expected_trade_date", lambda db, **kw: ("2026-07-16", "anchor")
    )

    def one_succeeds_one_blocks(symbol, *_args, **_kwargs):
        if symbol == "600519":
            return 4
        raise PriceBasisWriteBlocked("mixed stored provenance")

    monkeypatch.setattr("backend.data.market.backfill_if_needed", one_succeeds_one_blocks)
    result = premarket.run_premarket(market="CN", protected_price_refresh=True)

    assert result["protected_price_refresh"]["status"] == "partial"
    assert result["protected_price_refresh"]["rows_written"] == 4
    assert result["protected_price_refresh"]["completed_symbols"] == 1
    assert result["protected_price_refresh"]["blocked_symbols"] == [
        {"symbol": "000001", "reason": "mixed stored provenance"}
    ]


def test_protected_price_refresh_stops_before_backfill_without_cutoff(
    monkeypatch, test_db, cn_stock
):
    from backend.jobs import premarket

    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    _stub_side_effects(monkeypatch)
    monkeypatch.setattr(
        "backend.data.freshness.expected_trade_date", lambda db, **kw: (None, "unavailable")
    )
    calls = []
    monkeypatch.setattr(
        "backend.data.market.backfill_if_needed",
        lambda *args, **kwargs: calls.append(kwargs) or 0,
    )

    with pytest.raises(RuntimeError, match="fixed expected_trade_date"):
        premarket.run_premarket(market="CN", protected_price_refresh=True)

    assert calls == []


def test_protected_price_refresh_rejects_non_cn_market(monkeypatch):
    from backend.jobs import premarket

    with pytest.raises(ValueError, match="CN only"):
        premarket.run_premarket(market="US", protected_price_refresh=True)


@pytest.mark.parametrize("market,symbol", [("HK", "00700"), ("US", "AAPL")])
def test_unprotected_global_market_refresh_keeps_legacy_kwargs(
    monkeypatch, test_db, market, symbol
):
    from backend.data.database import Stock
    from backend.jobs import premarket

    stock = Stock(symbol=symbol, name=symbol, market=market, industry="test", active=True)
    test_db.add(stock)
    test_db.commit()
    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    monkeypatch.setattr("backend.decision.market_policy.is_signal_eligible_stock", lambda _stock: True)
    _stub_side_effects(monkeypatch)
    monkeypatch.setattr("backend.data.global_disclosures.sync_global_disclosures", lambda *a, **kw: 0)
    calls = []

    def _fake_backfill(stock_symbol, stock_market, db, **kwargs):
        calls.append((stock_symbol, stock_market, kwargs))
        return 0

    monkeypatch.setattr("backend.data.market.backfill_if_needed", _fake_backfill)

    result = premarket.run_premarket(market=market)

    assert calls == [(symbol, market, {"refresh_today": True})]
    assert result["errors"] == 0
