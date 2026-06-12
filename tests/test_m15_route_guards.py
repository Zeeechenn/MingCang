"""M15.1: research and skill write routes are gated by the agent write guard.

These routes call the runtime LLM, deep-research providers, or write report
files, so in remote agent mode they must require an API key and a write-action
allowlist entry — the same contract the memory/position/watchlist routes use.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


def _route_guards(router, path: str, method: str = "POST"):
    """Return the decorator-level guard dependency callables for a route."""
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return [dep.dependency for dep in route.dependencies]
    raise AssertionError(f"route not found: {method} {path}")


_GUARDED_ROUTES = [
    ("backend.api.routes.research", "/research/{symbol}/copilot", "research.copilot"),
    ("backend.api.routes.research", "/research/deep/run", "research.deep.run"),
    ("backend.api.routes.skills", "/skills/daily-review/run", "skill.daily_review.run"),
]


@pytest.mark.parametrize("module, path, action", _GUARDED_ROUTES)
def test_write_route_rejects_remote_call_without_key(monkeypatch, module, path, action):
    router = importlib.import_module(module).router
    guards = _route_guards(router, path)
    assert guards, f"{path} is missing its agent write guard"

    monkeypatch.setenv("MINGCANG_AGENT_MODE", "remote")
    monkeypatch.setenv("MINGCANG_AGENT_API_KEY", "secret")
    monkeypatch.setenv("MINGCANG_AGENT_REMOTE_WRITE_ENABLED", "true")

    with pytest.raises(HTTPException) as exc:
        guards[0](_FakeRequest())
    assert exc.value.status_code == 401


@pytest.mark.parametrize("module, path, action", _GUARDED_ROUTES)
def test_write_route_honors_action_allowlist(monkeypatch, module, path, action):
    router = importlib.import_module(module).router
    guards = _route_guards(router, path)

    monkeypatch.setenv("MINGCANG_AGENT_MODE", "remote")
    monkeypatch.setenv("MINGCANG_AGENT_API_KEY", "secret")
    monkeypatch.setenv("MINGCANG_AGENT_REMOTE_WRITE_ENABLED", "true")
    monkeypatch.setenv("MINGCANG_AGENT_REMOTE_WRITE_ACTIONS", "watchlist.add")

    headers = {"x-mingcang-agent-api-key": "secret"}
    with pytest.raises(HTTPException) as exc:
        guards[0](_FakeRequest(headers))
    assert exc.value.status_code == 403

    # The route's own action on the allowlist is accepted.
    monkeypatch.setenv("MINGCANG_AGENT_REMOTE_WRITE_ACTIONS", action)
    guards[0](_FakeRequest(headers))
    guards[0](_FakeRequest({"x-mingcang-agent-api-key": "secret"}))
    guards[0](_FakeRequest({"authorization": "Bearer secret"}))


@pytest.mark.parametrize("module, path, action", _GUARDED_ROUTES)
def test_write_route_passes_in_trusted_local_mode(monkeypatch, module, path, action):
    monkeypatch.setenv("MINGCANG_AGENT_MODE", "local")
    router = importlib.import_module(module).router
    guards = _route_guards(router, path)
    # Local development mode is trusted: the guard must pass without any key.
    guards[0](_FakeRequest())
