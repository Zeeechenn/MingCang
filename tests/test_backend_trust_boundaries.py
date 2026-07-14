from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def test_system_health_is_read_only_and_hides_absolute_database_path(test_db, monkeypatch):
    from backend.api.routes.system import system_health
    from backend.config import settings
    from backend.memory.audit_log import audit_write

    calls = {"bark": 0}
    audit_write(test_db, "baseline", "health trust-boundary baseline")
    baseline_audit_count = test_db.execute(text("SELECT count(*) FROM audit_log_fts")).scalar()
    monkeypatch.setattr(settings, "database_url", "sqlite:////tmp/private/mingcang.sqlite")
    monkeypatch.setattr(
        "backend.ops.llm_usage.check_daily_budget_alert",
        lambda **kwargs: {"alert": True, "today_cny": 2.0, "budget_cny": 1.0},
    )
    monkeypatch.setattr(
        "backend.notification.bark.send_result",
        lambda **kwargs: calls.__setitem__("bark", calls["bark"] + 1),
    )
    payload = system_health(db=test_db)

    assert payload["llm_budget_alert"]["alert"] is True
    assert calls == {"bark": 0}
    assert test_db.execute(text("SELECT count(*) FROM audit_log_fts")).scalar() == baseline_audit_count
    assert not Path(payload["db_path"]).is_absolute()


@pytest.mark.parametrize(
    ("handler_name", "args", "kwargs"),
    [
        ("mingcang_project_context", (), {"symbol": "300308"}),
        ("mingcang_memory_snapshot", (), {}),
        ("mingcang_memory_context", ("300308",), {}),
        ("mingcang_stock_context", ("300308",), {}),
        ("mingcang_health", (), {}),
    ],
)
def test_mcp_read_handlers_do_not_record_memory_usage(
    test_db, sample_stocks, monkeypatch, handler_name, args, kwargs
):
    from backend.agent import mcp_server
    from backend.memory.stock_memory import create_stock_memory

    row = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="MCP read-only recall boundary",
        source_type="test",
        source_ref=f"mcp-read-only-{handler_name}",
    )
    baseline_last_used = test_db.execute(
        text("SELECT last_used_at FROM stock_memory_items WHERE id = :id"), {"id": row["id"]}
    ).scalar()
    baseline_audit_count = test_db.execute(text("SELECT count(*) FROM audit_log_fts")).scalar()
    monkeypatch.setattr(mcp_server, "SessionLocal", lambda: test_db)

    getattr(mcp_server, handler_name)(*args, **kwargs)

    assert test_db.execute(
        text("SELECT last_used_at FROM stock_memory_items WHERE id = :id"), {"id": row["id"]}
    ).scalar() == baseline_last_used
    assert test_db.execute(text("SELECT count(*) FROM audit_log_fts")).scalar() == baseline_audit_count


@pytest.mark.parametrize(
    "lifecycle_payload",
    [
        {"status": "closed"},
        {"status": "open"},
        {"closed_at": "2026-07-14"},
        {"close_price": 105},
    ],
)
def test_general_position_patch_rejects_lifecycle_fields(test_db, lifecycle_payload):
    from backend.api.routes.positions import create_position
    from backend.api.schemas import PositionCreate
    from backend.data.database import Position, get_db
    from backend.main import app

    created = create_position(
        PositionCreate(symbol="600519", quantity=1, avg_cost=100), db=test_db
    )

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).patch(
            f"/api/positions/{created.id}", json=lifecycle_payload
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    assert test_db.query(Position).filter(Position.id == created.id).one().status == "open"


def test_dedicated_close_endpoint_keeps_close_payload_compatible(test_db):
    from backend.api.routes.positions import create_position
    from backend.api.schemas import PositionCreate
    from backend.data.database import get_db
    from backend.main import app

    created = create_position(
        PositionCreate(symbol="600519", quantity=2, avg_cost=100), db=test_db
    )

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).patch(
            f"/api/positions/{created.id}/close",
            json={
                "status": "closed",
                "close_price": 110,
                "closed_at": "2026-07-14",
                "note": "dedicated close",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["close_price"] == 110
    assert response.json()["realized_pnl"] == 20
