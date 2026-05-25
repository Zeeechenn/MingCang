import pandas as pd


def test_cn_daily_registry_excludes_unadjusted_tushare(monkeypatch):
    from backend.data import market, providers

    providers.reset_provider_registry()
    monkeypatch.setattr(market.settings, "tushare_token", "fake-token")
    monkeypatch.setattr(
        market,
        "fetch_daily_with_fallback",
        lambda symbol, market_name, days: (
            pd.DataFrame(
                {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
                index=pd.Index(["2026-01-01"], name="date"),
            ),
            "efinance_cn",
        ),
    )

    market.fetch_daily("600519", "CN", days=5)

    assert "tushare_cn" not in providers.list_daily_providers("CN")


def test_cn_daily_registry_excludes_hfq_yfinance(monkeypatch):
    from backend.data import market, providers

    providers.reset_provider_registry()
    monkeypatch.setattr(
        market,
        "fetch_daily_with_fallback",
        lambda symbol, market_name, days: (
            pd.DataFrame(
                {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
                index=pd.Index(["2026-01-01"], name="date"),
            ),
            "efinance_cn",
        ),
    )

    market.fetch_daily("600519", "CN", days=5)

    assert "yfinance_cn" not in providers.list_daily_providers("CN")


def test_cn_daily_registry_prioritizes_tickflow_when_enabled(monkeypatch):
    from backend.data import market, providers

    providers.reset_provider_registry()
    monkeypatch.setattr(market.settings, "tickflow_enabled", True)
    monkeypatch.setattr(market.settings, "tickflow_api_key", "fake-key")
    monkeypatch.setattr(
        market,
        "fetch_daily_with_fallback",
        lambda symbol, market_name, days: (
            pd.DataFrame(
                {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
                index=pd.Index(["2026-01-01"], name="date"),
            ),
            "tickflow_cn",
        ),
    )

    market.fetch_daily("600519", "CN", days=5)

    providers_for_cn = providers.list_daily_providers("CN")
    assert "tickflow_cn" in providers_for_cn
    assert providers_for_cn.index("tickflow_cn") < providers_for_cn.index("efinance_cn")
