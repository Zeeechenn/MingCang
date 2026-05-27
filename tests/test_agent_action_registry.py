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
    config_definition = get_action_definition("config.update")
    assert "long_term_constraints_enabled" in config_definition.input_schema["properties"]


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
    from backend.memory.stock_memory import list_stock_memories

    result = _execute_action(
        "watchlist.add",
        {"symbol": "600519", "name": "贵州茅台", "market": "CN"},
        test_db,
    )

    assert result["active"] is True
    assert test_db.query(Stock).filter(Stock.symbol == "600519", Stock.active).count() == 1
    memories = list_stock_memories(test_db, symbol="600519", memory_type="user_preference")
    assert len(memories) == 1
    assert "主动关注" in memories[0]["summary"]


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


def test_stock_memory_write_action_persists_structured_memory(test_db):
    from backend.agent.action_registry import execute_registered_action
    from backend.memory.stock_memory import list_stock_memories

    result = execute_registered_action(
        "stock_memory.write",
        {
            "symbol": "300308",
            "memory_type": "risk",
            "summary": "300308 风险是海外订单兑现不及预期",
            "importance": 5,
            "confidence": 0.8,
            "status": "watching",
        },
        test_db,
    )

    rows = list_stock_memories(test_db, symbol="300308", memory_type="risk")
    assert result["persisted"] is True
    assert result["stock_memory_id"] == rows[0]["id"]
    assert rows[0]["summary"] == "300308 风险是海外订单兑现不及预期"
    assert rows[0]["status"] == "watching"


def test_stock_memory_write_rejects_invalid_type(test_db):
    from fastapi import HTTPException

    from backend.agent.action_registry import execute_registered_action

    with pytest.raises(HTTPException) as exc:
        execute_registered_action(
            "stock_memory.write",
            {"symbol": "300308", "memory_type": "note", "summary": "bad"},
            test_db,
        )

    assert exc.value.status_code == 400
    assert "memory_type" in exc.value.detail


def test_position_add_accepts_full_http_payload(test_db):
    from backend.agent.action_registry import execute_registered_action
    from backend.data.database import Position

    result = execute_registered_action(
        "position.add",
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "market": "CN",
            "quantity": 2,
            "avg_cost": 100,
            "opened_at": "2026-05-20",
            "stop_loss": 90,
            "take_profit": 130,
            "note": "agent add",
        },
        test_db,
    )

    assert result["stop_loss"] == 90
    stored = test_db.query(Position).filter(Position.symbol == "600519").one()
    assert stored.opened_at == "2026-05-20"
    assert stored.take_profit == 130
    assert stored.note == "agent add"


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "600519", "quantity": 1, "avg_cost": 100, "foo": "bar"},
        {"symbol": "600519", "quantity": 0, "avg_cost": 100},
        {"symbol": "600519", "quantity": 1, "avg_cost": -1},
    ],
)
def test_position_add_rejects_invalid_or_unknown_payload(payload, test_db):
    from fastapi import HTTPException

    from backend.agent.action_registry import execute_registered_action

    with pytest.raises(HTTPException) as exc:
        execute_registered_action("position.add", payload, test_db)

    assert exc.value.status_code == 400


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
