import json

import requests


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"code": 200}


def test_bark_send_result_retries_transient_network_error(monkeypatch):
    from backend.config import settings
    from backend.notification import bark

    monkeypatch.setattr(settings, "bark_key", "unit-key")
    monkeypatch.setattr(settings, "bark_server", "https://bark.example")
    calls = {"count": 0}

    def fake_post(url, data, headers, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.RequestException("temporary")
        assert url == "https://bark.example/push"
        assert json.loads(data.decode())["device_key"] == "unit-key"
        assert headers["Content-Type"] == "application/json; charset=utf-8"
        assert timeout == 10
        return _Resp()

    monkeypatch.setattr(bark.requests, "post", fake_post)
    monkeypatch.setattr(bark.time, "sleep", lambda _: None)

    result = bark.send_result("title", "body", retries=2, backoff_seconds=0)

    assert result["ok"] is True
    assert result["attempts"] == 2
    assert bark.send("title", "body", retries=0) is True


def test_bark_send_result_reports_missing_key(monkeypatch):
    from backend.config import settings
    from backend.notification import bark

    monkeypatch.setattr(settings, "bark_key", "")

    result = bark.send_result("title", "body")

    assert result == {"ok": False, "skipped": True, "reason": "missing_bark_key", "attempts": 0}
