"""Anspire is disabled by default (2026-07-20) but its interface is preserved.

Background: the live Anspire key stopped authenticating, so every signal run
emitted one 401 per stock (82 in the 2026-07-20 batch) for zero usable news.
Rather than delete the integration we gated it behind ``settings.anspire_enabled``
so it can be restored by config alone.

These tests pin both halves of that contract: no network by default, and the
adapter/registry surface still intact.
"""
from __future__ import annotations

import backend.data.news as news_module


def test_anspire_disabled_by_default():
    from backend.config import settings

    assert settings.anspire_enabled is False


def test_fetch_returns_empty_without_touching_network(monkeypatch):
    """Disabled means we never even build a request."""
    called = {"n": 0}

    def _boom(*a, **kw):  # pragma: no cover - must never run
        called["n"] += 1
        raise AssertionError("Anspire must not issue a request while disabled")

    import requests

    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(news_module, "_anspire_disabled_warned", False, raising=False)

    assert news_module.fetch_stock_news_anspire("600900", "长江电力") == []
    assert called["n"] == 0


def test_disabled_notice_is_logged_once_per_process(monkeypatch, caplog):
    """The old behaviour logged one warning per stock; that was the actual damage."""
    monkeypatch.setattr(news_module, "_anspire_disabled_warned", False, raising=False)

    with caplog.at_level("INFO", logger="backend.data.news"):
        for symbol in ("600900", "601899", "600547", "300558"):
            news_module.fetch_stock_news_anspire(symbol, symbol)

    notices = [r for r in caplog.records if "Anspire 新闻源已停用" in r.getMessage()]
    assert len(notices) == 1


def test_enabling_flag_restores_the_call_path(monkeypatch):
    """Interface preserved: flipping the flag puts the fetcher back in play."""
    from backend.config import settings

    monkeypatch.setattr(settings, "anspire_enabled", True)
    monkeypatch.setattr(settings, "anspire_api_key", "")

    # Still empty here, but for the *key* reason rather than the kill-switch —
    # i.e. execution proceeded past the gate.
    assert news_module.fetch_stock_news_anspire("600900", "长江电力") == []


def test_adapter_and_registry_surface_preserved():
    from backend.data.news_adapters import AnspireAdapter
    from backend.data.news_adapters.registry import registered_adapter_names

    assert "anspire" in registered_adapter_names()
    assert AnspireAdapter.name == "anspire"
    assert AnspireAdapter.requires_key is True
