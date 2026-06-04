from __future__ import annotations

import pytest
from fastapi import HTTPException


class FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


def test_http_agent_write_guard_rejects_remote_without_key(monkeypatch):
    from backend.agent.http_guard import agent_write_guard

    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")

    guard = agent_write_guard("config.update")
    with pytest.raises(HTTPException) as exc:
        guard(FakeRequest({}))

    assert exc.value.status_code == 401


def test_http_agent_write_guard_honors_allowlist(monkeypatch):
    from backend.agent.http_guard import agent_write_guard

    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS", "watchlist.add")

    agent_write_guard("watchlist.add")(FakeRequest({"x-stocksage-agent-api-key": "secret"}))
    with pytest.raises(HTTPException) as exc:
        agent_write_guard("config.update")(FakeRequest({"x-stocksage-agent-api-key": "secret"}))

    assert exc.value.status_code == 403


def test_sensitive_write_routes_are_registered_with_agent_guard():
    from fastapi.routing import APIRoute

    from backend.api.routes import router

    expected = {
        ("/system/kill-switch/trigger", "POST"),
        ("/system/kill-switch/reset", "POST"),
        ("/model/train", "POST"),
        ("/system/initialize", "POST"),
        ("/ai/chat", "POST"),
        ("/ai/chat/stream", "POST"),
        ("/ai/sessions", "POST"),
        ("/ai/sessions/{session_id}/archive", "POST"),
        ("/research/{symbol}/review", "POST"),
        ("/memory/l0/atoms/{atom_id}/promote", "POST"),
        ("/memory/l0/atoms/{atom_id}/refute", "POST"),
    }
    routes = {
        (route.path, method): route
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    for key in expected:
        route = routes[key]
        assert any(
            getattr(dep.call, "__qualname__", "").startswith("agent_write_guard.")
            for dep in route.dependant.dependencies
        ), f"{key} missing agent_write_guard dependency"
