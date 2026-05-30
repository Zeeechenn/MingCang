import pandas as pd
import pytest


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _ok_response(fields, items):
    return FakeResponse({"code": 0, "msg": None, "data": {"fields": fields, "items": items}})


def test_tushare_qfq_daily_can_be_monkeypatched_at_http_boundary(monkeypatch):
    from backend.config import settings
    from backend.data import tushare_qfq

    tushare_qfq.reset_tushare_qfq_cache()
    calls = []

    class FakeSession:
        trust_env = True

        def post(self, url, json, timeout):
            calls.append((url, json, timeout, self.trust_env))
            if json["api_name"] == "daily":
                return _ok_response(
                    ["ts_code", "trade_date", "open", "high", "low", "close", "vol"],
                    [["600519.SH", "20260529", 10.0, 12.0, 9.0, 11.0, 1000]],
                )
            return _ok_response(
                ["ts_code", "trade_date", "adj_factor"],
                [["600519.SH", "20260529", 2.0]],
            )

    monkeypatch.setattr(settings, "tushare_token", "unit-token")
    monkeypatch.setattr(settings, "tushare_http_base_url", "https://tushare.test")
    monkeypatch.setattr(settings, "tushare_timeout_seconds", 7.0)
    monkeypatch.setattr(settings, "tushare_adj_factor_min_interval_seconds", 0.0)
    monkeypatch.setattr(tushare_qfq.requests, "Session", FakeSession)

    df = tushare_qfq.fetch_tushare_qfq_daily("600519", days=30)

    assert [call[1]["api_name"] for call in calls] == ["daily", "adj_factor"]
    assert calls[0][0] == "https://tushare.test"
    assert calls[0][1]["token"] == "unit-token"
    assert calls[0][1]["params"]["ts_code"] == "600519.SH"
    assert calls[0][1]["fields"] == "ts_code,trade_date,open,high,low,close,vol"
    assert calls[1][1]["fields"] == "ts_code,trade_date,adj_factor"
    assert calls[0][3] is False
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tolist() == ["2026-05-29"]
    assert float(df.loc["2026-05-29", "close"]) == 11.0


def test_tushare_qfq_daily_uses_daily_and_adj_factor(monkeypatch):
    from backend.config import settings
    from backend.data import tushare_qfq

    tushare_qfq.reset_tushare_qfq_cache()
    calls = []

    def fake_call(api_name, params, fields, *, token, base_url, timeout_seconds):
        calls.append((api_name, params, fields, token, base_url, timeout_seconds))
        if api_name == "daily":
            return pd.DataFrame([
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20260529",
                    "open": 1270.6,
                    "high": 1329.0,
                    "low": 1270.0,
                    "close": 1326.0,
                    "vol": 76478,
                },
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20250530",
                    "open": 1500.0,
                    "high": 1530.0,
                    "low": 1490.0,
                    "close": 1522.0,
                    "vol": 31239,
                },
            ])
        return pd.DataFrame([
            {"ts_code": "600519.SH", "trade_date": "20260529", "adj_factor": 8.4464},
            {"ts_code": "600519.SH", "trade_date": "20250530", "adj_factor": 8.1454},
        ])

    monkeypatch.setattr(settings, "tushare_token", "unit-token")
    monkeypatch.setattr(settings, "tushare_http_base_url", "https://tushare.test")
    monkeypatch.setattr(settings, "tushare_timeout_seconds", 7.0)
    monkeypatch.setattr(settings, "tushare_adj_factor_min_interval_seconds", 65.0)
    monkeypatch.setattr(tushare_qfq, "_call_tushare", fake_call)
    monkeypatch.setattr(tushare_qfq.time, "monotonic", lambda: 1000.0)

    df = tushare_qfq.fetch_tushare_qfq_daily("600519", days=30)

    assert [call[0] for call in calls] == ["daily", "adj_factor"]
    assert calls[0][1]["ts_code"] == "600519.SH"
    assert calls[0][3] == "unit-token"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tolist() == ["2025-05-30", "2026-05-29"]
    expected_close = 1522.0 * 8.1454 / 8.4464
    assert float(df.loc["2025-05-30", "close"]) == pytest.approx(expected_close)
    assert float(df.loc["2026-05-29", "close"]) == pytest.approx(1326.0)


def test_tushare_http_client_bypasses_system_proxy(monkeypatch):
    from backend.data import tushare_qfq

    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"fields": ["trade_date"], "items": [["20260529"]]}}

    class FakeSession:
        trust_env = True

        def post(self, base_url, json, timeout):
            calls["trust_env"] = self.trust_env
            calls["base_url"] = base_url
            calls["json"] = json
            calls["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(tushare_qfq.requests, "Session", FakeSession)

    df = tushare_qfq._call_tushare(
        "daily",
        {"ts_code": "600519.SH"},
        "trade_date",
        token="unit-token",
        base_url="https://tushare.test",
        timeout_seconds=5,
    )

    assert df.to_dict("records") == [{"trade_date": "20260529"}]
    assert calls["trust_env"] is False
    assert calls["base_url"] == "https://tushare.test"


def test_tushare_qfq_reuses_adj_factor_cache(monkeypatch):
    from backend.config import settings
    from backend.data import tushare_qfq

    tushare_qfq.reset_tushare_qfq_cache()
    calls = {"daily": 0, "adj_factor": 0}

    def fake_call(api_name, params, fields, *, token, base_url, timeout_seconds):
        calls[api_name] += 1
        if api_name == "daily":
            return pd.DataFrame([{
                "ts_code": "000001.SZ",
                "trade_date": "20260529",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "vol": 100,
            }])
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260529", "adj_factor": 1.0}])

    monkeypatch.setattr(settings, "tushare_token", "unit-token")
    monkeypatch.setattr(tushare_qfq, "_call_tushare", fake_call)
    monkeypatch.setattr(tushare_qfq.time, "monotonic", lambda: 1000.0)

    first = tushare_qfq.fetch_tushare_qfq_daily("000001", days=30)
    second = tushare_qfq.fetch_tushare_qfq_daily("000001", days=30)

    assert not first.empty
    assert not second.empty
    assert calls == {"daily": 2, "adj_factor": 1}


def test_tushare_qfq_rate_limit_without_cache(monkeypatch):
    from backend.config import settings
    from backend.data import tushare_qfq

    tushare_qfq.reset_tushare_qfq_cache()

    def fake_call(api_name, params, fields, *, token, base_url, timeout_seconds):
        if api_name == "daily":
            return pd.DataFrame([{
                "ts_code": params["ts_code"],
                "trade_date": "20260529",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "vol": 1,
            }])
        return pd.DataFrame([{"ts_code": params["ts_code"], "trade_date": "20260529", "adj_factor": 1}])

    monkeypatch.setattr(settings, "tushare_token", "unit-token")
    monkeypatch.setattr(settings, "tushare_adj_factor_min_interval_seconds", 65.0)
    monkeypatch.setattr(tushare_qfq, "_call_tushare", fake_call)
    monkeypatch.setattr(tushare_qfq.time, "monotonic", lambda: 1000.0)
    tushare_qfq.fetch_tushare_qfq_daily("600519", days=30)
    monkeypatch.setattr(tushare_qfq.time, "monotonic", lambda: 1010.0)
    sleeps = []
    monkeypatch.setattr(tushare_qfq.time, "sleep", lambda seconds: sleeps.append(seconds))

    df = tushare_qfq.fetch_tushare_qfq_daily("300308", days=30)

    assert not df.empty
    assert sleeps == [pytest.approx(55.0)]


def test_tushare_qfq_surfaces_api_errors(monkeypatch):
    from backend.config import settings
    from backend.data import tushare_qfq

    tushare_qfq.reset_tushare_qfq_cache()

    class FakeSession:
        def post(self, url, json, timeout):
            return FakeResponse({"code": -2001, "msg": "权限不足", "data": None})

    monkeypatch.setattr(settings, "tushare_token", "unit-token")
    monkeypatch.setattr(tushare_qfq.requests, "Session", FakeSession)

    with pytest.raises(tushare_qfq.TushareQfqError, match="code=-2001 msg=权限不足"):
        tushare_qfq.fetch_tushare_qfq_daily("600519", days=30)


def test_probe_tushare_qfq_is_disabled_by_default(monkeypatch):
    from backend.config import settings
    from backend.data import tushare_qfq

    def fail_fetch(*args, **kwargs):
        raise AssertionError("disabled probe should not call Tushare")

    monkeypatch.setattr(settings, "tushare_qfq_enabled", False)
    monkeypatch.setattr(tushare_qfq, "fetch_tushare_qfq_daily", fail_fetch)

    result = tushare_qfq.probe_tushare_qfq_daily("600519")

    assert result["ok"] is False
    assert result["enabled"] is False
    assert result["adjustment"] == "qfq"


def test_market_registers_tushare_qfq_only_when_enabled(monkeypatch):
    from backend.data import market, providers

    providers.reset_provider_registry()
    monkeypatch.setattr(market.settings, "tushare_token", "unit-token")
    monkeypatch.setattr(market.settings, "tushare_qfq_enabled", True)
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

    providers_for_cn = providers.list_daily_providers("CN")
    assert "tushare_qfq_cn" in providers_for_cn
    assert "tushare_cn" not in providers_for_cn
