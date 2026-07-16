"""tickflow 限速配置化 + 429 自适应退避：不碰网络，monkeypatch time/requests。"""
from __future__ import annotations

import pytest

from backend.data import tickflow


@pytest.fixture(autouse=True)
def _reset_throttle_state(monkeypatch):
    """每个用例前重置模块级限速状态，避免用例间相互污染。"""
    monkeypatch.setattr(tickflow, "_last_request_at", 0.0)
    monkeypatch.setattr(tickflow, "_consecutive_429", 0)
    yield


def test_base_interval_reads_settings(monkeypatch):
    monkeypatch.delenv("TICKFLOW_MIN_REQUEST_INTERVAL", raising=False)
    monkeypatch.setattr(tickflow.settings, "tickflow_min_request_interval", 1.25)
    assert tickflow._min_request_interval_base() == 1.25


def test_env_var_overrides_settings(monkeypatch):
    monkeypatch.setattr(tickflow.settings, "tickflow_min_request_interval", 1.25)
    monkeypatch.setenv("TICKFLOW_MIN_REQUEST_INTERVAL", "0.1")
    assert tickflow._min_request_interval_base() == 0.1


def test_effective_interval_no_backoff_when_no_429(monkeypatch):
    monkeypatch.delenv("TICKFLOW_MIN_REQUEST_INTERVAL", raising=False)
    monkeypatch.setattr(tickflow.settings, "tickflow_min_request_interval", 0.5)
    assert tickflow._effective_request_interval() == 0.5


def test_429_doubles_effective_interval_up_to_cap(monkeypatch):
    monkeypatch.delenv("TICKFLOW_MIN_REQUEST_INTERVAL", raising=False)
    monkeypatch.setattr(tickflow.settings, "tickflow_min_request_interval", 0.5)

    tickflow._note_response_status(429)
    assert tickflow._effective_request_interval() == pytest.approx(1.0)

    tickflow._note_response_status(429)
    assert tickflow._effective_request_interval() == pytest.approx(2.0)

    tickflow._note_response_status(429)
    assert tickflow._effective_request_interval() == pytest.approx(4.0)

    # 第4次及以后应封顶在 4.0（base*2**3 = 4.0，与 cap 相等；确认不会继续翻倍到 8.0）
    tickflow._note_response_status(429)
    assert tickflow._effective_request_interval() == pytest.approx(4.0)


def test_success_resets_429_counter(monkeypatch):
    monkeypatch.delenv("TICKFLOW_MIN_REQUEST_INTERVAL", raising=False)
    monkeypatch.setattr(tickflow.settings, "tickflow_min_request_interval", 0.5)

    tickflow._note_response_status(429)
    tickflow._note_response_status(429)
    assert tickflow._effective_request_interval() == pytest.approx(2.0)

    tickflow._note_response_status(200)
    assert tickflow._effective_request_interval() == pytest.approx(0.5)


def test_zero_base_disables_throttle_even_after_429(monkeypatch):
    monkeypatch.delenv("TICKFLOW_MIN_REQUEST_INTERVAL", raising=False)
    monkeypatch.setattr(tickflow.settings, "tickflow_min_request_interval", 0.0)
    tickflow._note_response_status(429)
    assert tickflow._effective_request_interval() == 0.0


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tickflow.requests.HTTPError(f"status={self.status_code}")


def test_fetch_tickflow_daily_notes_429_then_raises(monkeypatch):
    monkeypatch.setattr(tickflow, "_throttle", lambda: None)
    monkeypatch.setattr(
        tickflow.requests, "get", lambda *a, **kw: _FakeResponse(429, {})
    )
    with pytest.raises(tickflow.requests.HTTPError):
        tickflow.fetch_tickflow_daily("600519", "CN", days=5)
    assert tickflow._consecutive_429 == 1


def test_fetch_tickflow_daily_success_resets_counter(monkeypatch):
    monkeypatch.setattr(tickflow, "_consecutive_429", 2)
    monkeypatch.setattr(tickflow, "_throttle", lambda: None)
    empty_payload = {"data": {"timestamp": []}}
    monkeypatch.setattr(
        tickflow.requests, "get", lambda *a, **kw: _FakeResponse(200, empty_payload)
    )
    tickflow.fetch_tickflow_daily("600519", "CN", days=5)
    assert tickflow._consecutive_429 == 0
