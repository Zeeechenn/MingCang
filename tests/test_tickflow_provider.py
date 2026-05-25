import pandas as pd


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_tickflow_symbol_maps_supported_markets():
    from backend.data.tickflow import tickflow_symbol

    assert tickflow_symbol("600519", "CN") == "600519.SH"
    assert tickflow_symbol("300308", "CN") == "300308.SZ"
    assert tickflow_symbol("920662", "CN") == "920662.BJ"
    assert tickflow_symbol("AAPL", "US") == "AAPL.US"
    assert tickflow_symbol("700", "HK") == "00700.HK"
    assert tickflow_symbol("00700.HK", "HK") == "00700.HK"


def test_fetch_tickflow_daily_normalizes_columnar_kline_payload(monkeypatch):
    from backend.data import tickflow

    calls = {}

    def fake_get(url, *, headers, params, timeout):
        calls.update({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return _FakeResponse({
            "data": {
                "timestamp": [1775088000000, 1779638400000],
                "open": [10.0, 10.5],
                "high": [11.0, 11.5],
                "low": [9.5, 10.1],
                "close": [10.8, 11.2],
                "volume": [1000, 1200],
                "amount": [10800, 13440],
            }
        })

    monkeypatch.setattr(tickflow.requests, "get", fake_get)

    df = tickflow.fetch_tickflow_daily(
        "600519",
        "CN",
        days=30,
        api_key="unit-key",
        base_url="https://api.tickflow.test",
    )

    assert calls["url"] == "https://api.tickflow.test/v1/klines"
    assert calls["headers"] == {"x-api-key": "unit-key"}
    assert calls["params"]["symbol"] == "600519.SH"
    assert calls["params"]["period"] == "1d"
    assert calls["params"]["adjust"] == "forward_additive"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tolist() == ["2026-04-02", "2026-05-25"]
    assert float(df.loc["2026-05-25", "close"]) == 11.2


def test_probe_tickflow_daily_is_disabled_by_default(monkeypatch):
    from backend.config import settings
    from backend.data import tickflow

    def fail_fetch(*args, **kwargs):
        raise AssertionError("probe should not call TickFlow unless enabled")

    monkeypatch.setattr(settings, "tickflow_enabled", False)
    monkeypatch.setattr(tickflow, "fetch_tickflow_daily", fail_fetch)

    result = tickflow.probe_tickflow_daily(symbol="600519", market="CN")

    assert result["ok"] is False
    assert result["enabled"] is False
    assert result["error"] == "TICKFLOW_ENABLED=false"


def test_probe_tickflow_daily_reports_success(monkeypatch):
    from backend.config import settings
    from backend.data import tickflow

    monkeypatch.setattr(settings, "tickflow_enabled", True)
    monkeypatch.setattr(settings, "tickflow_api_key", "unit-key")
    monkeypatch.setattr(settings, "tickflow_base_url", "https://api.tickflow.test")
    monkeypatch.setattr(
        tickflow,
        "fetch_tickflow_daily",
        lambda *args, **kwargs: pd.DataFrame(
            [{"open": 1, "high": 2, "low": 1, "close": 2, "volume": 100}],
            index=["2026-05-22"],
        ),
    )

    result = tickflow.probe_tickflow_daily(symbol="600519", market="CN")

    assert result["ok"] is True
    assert result["symbol"] == "600519"
    assert result["tickflow_symbol"] == "600519.SH"
    assert result["rows"] == 1
    assert result["latest_date"] == "2026-05-22"
