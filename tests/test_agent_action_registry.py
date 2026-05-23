from __future__ import annotations

import pytest


def test_action_registry_exposes_metadata_for_known_actions():
    from backend.agent.action_registry import get_action_definition

    definition = get_action_definition("watchlist.add")

    assert definition.name == "watchlist.add"
    assert definition.risk_level == "medium"
    assert definition.requires_confirmation is True
    assert "local" in definition.allowed_modes
    assert definition.input_schema["type"] == "object"


def test_pending_action_includes_registry_metadata(test_db):
    from backend.api.routes.ai import _pending

    pending = _pending(
        "watchlist.add",
        {"symbol": "600519", "name": "贵州茅台", "market": "CN"},
        "添加自选 600519",
        test_db,
    )

    assert pending["risk_level"] == "medium"
    assert pending["requires_confirmation"] is True
    assert pending["schema_version"] == 1


def test_execute_action_uses_registry_handler(test_db):
    from backend.api.routes.ai import _execute_action
    from backend.data.database import Stock

    result = _execute_action(
        "watchlist.add",
        {"symbol": "600519", "name": "贵州茅台", "market": "CN"},
        test_db,
    )

    assert result["active"] is True
    assert test_db.query(Stock).filter(Stock.symbol == "600519", Stock.active).count() == 1


def test_execute_unknown_action_is_rejected(test_db):
    from fastapi import HTTPException

    from backend.api.routes.ai import _execute_action

    with pytest.raises(HTTPException) as exc:
        _execute_action("unknown.action", {}, test_db)

    assert exc.value.status_code == 400


def test_remote_write_requires_action_allowlist():
    from backend.agent.security import AgentSecurityError, require_agent_access

    env = {
        "STOCKSAGE_AGENT_MODE": "remote",
        "STOCKSAGE_AGENT_API_KEY": "secret",
        "STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED": "true",
        "STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS": "watchlist.add",
    }

    require_agent_access("write", env=env, api_key="secret", action="watchlist.add")
    with pytest.raises(AgentSecurityError):
        require_agent_access("write", env=env, api_key="secret", action="config.update")


def test_agent_security_reads_settings_when_env_not_in_os(monkeypatch):
    from backend.agent.security import require_agent_access
    from backend.config import settings

    monkeypatch.delenv("STOCKSAGE_AGENT_MODE", raising=False)
    monkeypatch.delenv("STOCKSAGE_AGENT_API_KEY", raising=False)
    monkeypatch.setattr(settings, "stocksage_agent_mode", "remote")
    monkeypatch.setattr(settings, "stocksage_agent_api_key", "secret")
    monkeypatch.setattr(settings, "stocksage_agent_remote_write_enabled", True)
    monkeypatch.setattr(settings, "stocksage_agent_remote_write_actions", "watchlist.add")

    require_agent_access("write", api_key="secret", action="watchlist.add")


def test_execute_action_validates_payload_before_handler(test_db):
    from fastapi import HTTPException

    from backend.agent.action_registry import execute_registered_action

    with pytest.raises(HTTPException) as exc:
        execute_registered_action("watchlist.add", {}, test_db)

    assert exc.value.status_code == 400
    assert "symbol" in exc.value.detail


def test_execute_action_enforces_allowed_modes(monkeypatch, test_db):
    from fastapi import HTTPException

    from backend.agent import action_registry
    from backend.agent.action_registry import ActionDefinition, execute_registered_action

    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setitem(
        action_registry._ACTIONS,
        "local.only",
        ActionDefinition(
            name="local.only",
            input_schema={"type": "object", "required": [], "properties": {}},
            risk_level="low",
            requires_confirmation=False,
            allowed_modes=("local",),
            handler=lambda payload, db: {"ok": True},
        ),
    )

    with pytest.raises(HTTPException) as exc:
        execute_registered_action("local.only", {}, test_db)

    assert exc.value.status_code == 403
