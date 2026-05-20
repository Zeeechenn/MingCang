import json
import urllib.error


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"code": 200}).encode()


def test_bark_send_result_retries_transient_network_error(monkeypatch):
    from backend.config import settings
    from backend.notification import bark

    monkeypatch.setattr(settings, "bark_key", "unit-key")
    monkeypatch.setattr(settings, "bark_server", "https://bark.example")
    calls = {"count": 0}

    def fake_urlopen(req, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("temporary")
        return _Resp()

    monkeypatch.setattr(bark.urllib.request, "urlopen", fake_urlopen)
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
