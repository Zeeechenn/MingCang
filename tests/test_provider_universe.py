import sys
import types

import pandas as pd


def test_provider_registry_fallback():
    from backend.data.providers import (
        fetch_daily_with_fallback,
        list_daily_providers,
        register_daily_provider,
        reset_provider_registry,
    )

    reset_provider_registry()

    def broken(symbol, days):
        raise RuntimeError("down")

    def ok(symbol, days):
        return pd.DataFrame([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    register_daily_provider("test_broken", {"T"}, broken)
    register_daily_provider("test_ok", {"T"}, ok)

    df, provider = fetch_daily_with_fallback("X", "T", 1)

    assert provider == "test_ok"
    assert len(df) == 1
    assert "test_ok" in list_daily_providers("T")


def test_provider_registry_skips_cooling_provider():
    from backend.data.providers import (
        fetch_daily_with_fallback,
        get_provider_health,
        register_daily_provider,
        reset_provider_registry,
    )

    reset_provider_registry()
    calls = {"bad": 0, "ok": 0}

    def bad(symbol, days):
        calls["bad"] += 1
        raise RuntimeError("network down")

    def ok(symbol, days):
        calls["ok"] += 1
        return pd.DataFrame([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    register_daily_provider("bad", {"CN"}, bad, cooldown_seconds=60)
    register_daily_provider("ok", {"CN"}, ok)

    _, provider1 = fetch_daily_with_fallback("600519", "CN", 30)
    _, provider2 = fetch_daily_with_fallback("600519", "CN", 30)

    assert provider1 == "ok"
    assert provider2 == "ok"
    assert calls == {"bad": 1, "ok": 2}
    assert get_provider_health()["bad"]["cooldown_until"] is not None


def test_fetch_daily_registers_cn_multi_source_chain(monkeypatch):
    from backend.data import market
    from backend.data.providers import list_daily_providers, reset_provider_registry

    reset_provider_registry()

    def fake_fetch(symbol, market_name, days):
        return pd.DataFrame([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]), "efinance_cn"

    monkeypatch.setattr(market.settings, "tickflow_enabled", False)
    monkeypatch.setattr(market.settings, "tickflow_api_key", "")
    monkeypatch.setattr(market, "fetch_daily_with_fallback", fake_fetch)

    df = market.fetch_daily("600519", "CN", days=30)

    assert not df.empty
    assert list_daily_providers("CN") == [
        "efinance_cn",
        "eastmoney_cn",
        "akshare_em_cn",
        "akshare_sina_cn",
        "akshare_tx_cn",
    ]


def test_fetch_daily_does_not_register_unadjusted_tushare_when_token_configured(monkeypatch):
    from backend.config import settings
    from backend.data import market
    from backend.data.providers import list_daily_providers, reset_provider_registry

    reset_provider_registry()
    monkeypatch.setattr(settings, "tushare_token", "unit-token")

    def fake_fetch(symbol, market_name, days):
        return pd.DataFrame([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]), "efinance_cn"

    monkeypatch.setattr(market, "fetch_daily_with_fallback", fake_fetch)

    df = market.fetch_daily("600519", "CN", days=30)

    assert not df.empty
    assert "tushare_cn" not in list_daily_providers("CN")


def test_fetch_cn_daily_tushare_normalizes_daily_bars(monkeypatch):
    from backend.config import settings
    from backend.data import market

    calls = {}

    class FakePro:
        def daily(self, **kwargs):
            calls.update(kwargs)
            return pd.DataFrame([
                {
                    "trade_date": "20260522",
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "vol": 1234,
                }
            ])

    def fake_pro_api(token):
        calls["token"] = token
        return FakePro()

    fake_tushare = types.SimpleNamespace(pro_api=fake_pro_api)
    monkeypatch.setitem(sys.modules, "tushare", fake_tushare)
    monkeypatch.setattr(settings, "tushare_token", "unit-token")

    df = market.fetch_cn_daily_tushare("600519", days=10)

    assert calls["token"] == "unit-token"
    assert calls["ts_code"] == "600519.SH"
    assert calls["fields"] == "trade_date,open,high,low,close,vol"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tolist() == ["2026-05-22"]
    assert float(df.loc["2026-05-22", "volume"]) == 1234.0


def test_fetch_cn_index_uses_index_provider_fallback(monkeypatch):
    from backend.data import market
    from backend.data.providers import reset_provider_registry

    reset_provider_registry()
    calls = []

    def broken(index_symbol, days):
        calls.append("broken")
        raise RuntimeError("index source down")

    def ok(index_symbol, days):
        calls.append("ok")
        return pd.DataFrame(
            [{"date": "2026-05-18", "close": 4000.0, "change_pct": 1.2}]
        ).set_index("date")

    monkeypatch.setattr(market, "fetch_cn_index_akshare", broken)
    monkeypatch.setattr(market, "fetch_cn_index_eastmoney", ok)

    df = market.fetch_cn_index("sh000300", days=30)

    assert calls == ["broken", "ok"]
    assert float(df.loc["2026-05-18", "close"]) == 4000.0


def test_universe_upsert_deduplicates(test_db):
    from backend.data.database import Stock
    from backend.data.universe import UniverseCandidate, merge_candidates, upsert_universe

    candidates = merge_candidates(
        [UniverseCandidate("600519", "贵州茅台")],
        [UniverseCandidate("600519", "贵州茅台"), UniverseCandidate("300308", "中际旭创")],
    )

    inserted = upsert_universe(test_db, candidates)

    assert inserted == 2
    assert test_db.query(Stock).count() == 2


def test_filter_universe_by_liquidity_and_market_cap():
    from backend.data.universe import UniverseCandidate, filter_universe

    candidates = [
        UniverseCandidate("600519", "贵州茅台"),
        UniverseCandidate("000001", "平安银行"),
        UniverseCandidate("300001", "低流动性样本"),
    ]
    stats = {
        "600519": {"market_cap": 100e9, "avg_daily_amount": 2e9},
        "000001": {"market_cap": 30e9, "avg_daily_amount": 800e6},
        "300001": {"market_cap": 80e9, "avg_daily_amount": 20e6},
    }

    out = filter_universe(
        candidates,
        stats=stats,
        min_market_cap=50e9,
        min_daily_amount=100e6,
    )

    assert [c.symbol for c in out] == ["600519"]


def test_cn_yfinance_ticker_suffix_mapping():
    from backend.data.market import cn_yfinance_ticker

    assert cn_yfinance_ticker("000002") == "000002.SZ"
    assert cn_yfinance_ticker("300308") == "300308.SZ"
    assert cn_yfinance_ticker("600519") == "600519.SS"
    assert cn_yfinance_ticker("688008") == "688008.SS"
