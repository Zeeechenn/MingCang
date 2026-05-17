import pandas as pd


def test_provider_registry_fallback():
    from backend.data.providers import (
        fetch_daily_with_fallback,
        list_daily_providers,
        register_daily_provider,
    )

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


def test_universe_upsert_deduplicates(test_db):
    from backend.data.universe import UniverseCandidate, merge_candidates, upsert_universe
    from backend.data.database import Stock

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
