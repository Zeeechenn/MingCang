"""M9.1 分层记忆迁 DB + 只读 API."""
from __future__ import annotations

from sqlalchemy import text


def test_save_medium_term_uses_db_as_canonical_store(test_db, tmp_path, monkeypatch):
    from backend.decision import memory_layered

    monkeypatch.setattr(memory_layered, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory_layered, "LONG_TERM_PATH", tmp_path / "long_term_reflection.md")
    memory_layered._SHORT_TERM.clear()

    signal = {
        "recommendation": "买入",
        "composite_score": 12,
        "position_pct": 0.05,
        "stop_loss": 9.5,
        "take_profit": 11.0,
        "risk_notes": [],
    }
    memory_layered.save_decision_layered("300308", "2026-05-19", signal, db=test_db)

    row = test_db.execute(text(
        "SELECT symbol, layer, content FROM decision_memory_layered "
        "WHERE symbol='300308' AND layer='medium'"
    )).first()
    assert row is not None
    assert "2026-05-19" in row.content
    assert "300308 中期决策记忆" in row.content
    assert not (tmp_path / "medium_300308.md").exists()


def test_layered_judgment_uses_data_timestamp_and_deduplicates_reruns(test_db):
    import json

    from backend.decision import memory_layered

    signal = {
        "recommendation": "可小仓试错",
        "composite_score": 32,
        "position_pct": 0.075,
        "stop_loss": 9.5,
        "take_profit": 11.0,
        "risk_notes": [],
        "data_timestamp": "2026-07-24",
    }

    memory_layered.save_decision_layered("300308", "2026-07-25", signal, db=test_db)
    memory_layered.save_decision_layered("300308", "2026-07-26", signal, db=test_db)

    rows = test_db.execute(text(
        "SELECT source_ref, evidence_json FROM stock_memory_items "
        "WHERE symbol='300308' AND memory_type='judgment'"
    )).all()
    assert len(rows) == 1
    evidence = json.loads(rows[0].evidence_json)
    assert rows[0].source_ref == "300308:2026-07-24"
    assert evidence["date"] == "2026-07-24"
    assert evidence["run_date"] == "2026-07-26"
    medium = test_db.execute(text(
        "SELECT content FROM decision_memory_layered "
        "WHERE symbol='300308' AND layer='medium'"
    )).scalar()
    assert medium.count("| 2026-07-24 |") == 1


def test_save_medium_term_keeps_recent_db_rows_only(test_db, tmp_path, monkeypatch):
    from backend.decision import memory_layered

    monkeypatch.setattr(memory_layered, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory_layered, "LONG_TERM_PATH", tmp_path / "long_term_reflection.md")
    monkeypatch.setattr(memory_layered, "_MAX_MEDIUM_TERM_ROWS", 3)

    signal = {
        "recommendation": "可关注",
        "composite_score": 12,
        "position_pct": 0.0,
        "stop_loss": 9.5,
        "take_profit": 11.0,
        "risk_notes": [],
    }
    for day in range(1, 6):
        memory_layered.save_medium_term("300308", f"2026-05-{day:02d}", signal, db=test_db)

    content = test_db.execute(text(
        "SELECT content FROM decision_memory_layered "
        "WHERE symbol='300308' AND layer='medium'"
    )).scalar()
    assert "2026-05-01" not in content
    assert "2026-05-02" not in content
    assert "2026-05-03" in content
    assert "2026-05-05" in content
    assert content.count("| 2026-05-") == 3
    assert not (tmp_path / "medium_300308.md").exists()


def test_save_medium_term_without_db_only_writes_file(test_db, tmp_path, monkeypatch):
    from backend.decision import memory_layered

    monkeypatch.setattr(memory_layered, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory_layered, "LONG_TERM_PATH", tmp_path / "long_term_reflection.md")

    signal = {
        "recommendation": "买入", "composite_score": 12, "position_pct": 0.05,
        "stop_loss": 9.5, "take_profit": 11.0, "risk_notes": [],
    }
    memory_layered.save_decision_layered("300308", "2026-05-19", signal)  # no db

    db_count = test_db.execute(text(
        "SELECT count(*) FROM decision_memory_layered"
    )).scalar()
    assert db_count == 0
    assert (tmp_path / "medium_300308.md").exists()


def test_get_long_term_context_prefers_db_over_file(test_db, tmp_path, monkeypatch):
    """If both DB row and file exist, DB wins."""
    from backend.decision import memory_layered

    monkeypatch.setattr(memory_layered, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory_layered, "LONG_TERM_PATH", tmp_path / "long_term_reflection.md")

    (tmp_path / "long_term_reflection.md").write_text(
        "# old file\n\n## 2024-W01\n\nstale content\n", encoding="utf-8"
    )
    memory_layered._upsert_layered_row(
        test_db, symbol=None, layer="long",
        content="# fresh db\n\n## 2026-W20\n\nfresh content from db\n",
    )

    ctx = memory_layered.get_long_term_context(db=test_db)
    assert "fresh content from db" in ctx
    assert "stale content" not in ctx


def test_get_long_term_context_falls_back_to_file_when_db_empty(test_db, tmp_path, monkeypatch):
    from backend.decision import memory_layered

    monkeypatch.setattr(memory_layered, "LONG_TERM_PATH", tmp_path / "long_term_reflection.md")
    (tmp_path / "long_term_reflection.md").write_text(
        "# x\n\n## 2026-W01\n\nfile-only content\n", encoding="utf-8"
    )

    ctx = memory_layered.get_long_term_context(db=test_db)
    assert "file-only content" in ctx


def test_migrate_layered_files_to_db_is_idempotent(test_db, tmp_path, monkeypatch):
    from backend.decision import memory_layered

    monkeypatch.setattr(memory_layered, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory_layered, "LONG_TERM_PATH", tmp_path / "long_term_reflection.md")

    (tmp_path / "medium_300308.md").write_text("# 300308\n\nrow A\n", encoding="utf-8")
    (tmp_path / "medium_600519.md").write_text("# 600519\n\nrow B\n", encoding="utf-8")
    (tmp_path / "long_term_reflection.md").write_text(
        "# long\n\n## 2026-W19\n\nreflection x\n", encoding="utf-8"
    )

    counts1 = memory_layered.migrate_layered_files_to_db(test_db)
    counts2 = memory_layered.migrate_layered_files_to_db(test_db)

    assert counts1 == counts2 == {"medium": 2, "long": 1}
    total = test_db.execute(text("SELECT count(*) FROM decision_memory_layered")).scalar()
    assert total == 3  # upsert, no duplication


# ── API endpoints (M9.1 read-only + M9.2 metadata edits) ──────────────────
# 这里直接调用路由函数（项目其他 API 测试也是这种模式），跳过 TestClient
# 以避免 dependency_overrides + lifespan 与真实 DB engine 的冲突。

def test_api_overview(test_db):
    from backend.api.routes.memory import memory_overview
    from backend.memory.ai_memory import remember

    remember(test_db, "rule:t1", "测试1 规则", category="rule", scope="test1")
    remember(test_db, "position:300308", "已买入 5%", category="position", scope="test1")

    data = memory_overview(db=test_db)
    assert data["total_active"] == 2
    assert data["by_scope"]["test1"] == 2
    assert data["by_category"]["rule"] == 1
    assert data["by_category"]["position"] == 1
    assert data["last_updated"] is not None


def test_api_list_with_filters(test_db):
    from backend.api.routes.memory import memory_list
    from backend.memory.ai_memory import remember

    remember(test_db, "rule:t1", "测试1 规则", category="rule", scope="test1")
    remember(test_db, "position:300308", "已买入 5%", category="position", scope="test1")

    res = memory_list(scope=None, category="rule", q=None, limit=100, db=test_db)
    assert len(res["rows"]) == 1 and res["rows"][0]["key"] == "rule:t1"

    res2 = memory_list(scope=None, category=None, q="300308", limit=100, db=test_db)
    assert any(r["key"] == "position:300308" for r in res2["rows"])


def test_api_audit_search(test_db):
    from backend.api.routes.memory import memory_audit
    from backend.memory.audit_log import audit_write

    audit_write(test_db, "memory.write", "key=foo scope=test", related_scope="test")
    res = memory_audit(q="foo", limit=50, db=test_db)
    assert any("foo" in r["content"] for r in res["rows"])


def test_api_delete_pin_patch(test_db):
    from backend.api.routes.memory import PatchPayload, memory_delete, memory_patch, memory_pin
    from backend.memory.ai_memory import remember

    remember(test_db, "rule:t1", "v1", category="rule", scope="test1", ttl_days=7)
    row_id = test_db.execute(text(
        "SELECT id FROM ai_memory WHERE key='rule:t1' AND scope='test1'"
    )).scalar()

    memory_patch(row_id, PatchPayload(ttl_days=30), db=test_db)
    memory_pin(row_id, db=test_db)
    ttl = test_db.execute(text(
        "SELECT ttl_days FROM ai_memory WHERE id = :id"
    ), {"id": row_id}).scalar()
    assert ttl is None

    memory_patch(row_id, PatchPayload(category="preference"), db=test_db)
    cat = test_db.execute(text(
        "SELECT category FROM ai_memory WHERE id = :id"
    ), {"id": row_id}).scalar()
    assert cat == "preference"

    memory_delete(row_id, db=test_db)
    gone = test_db.execute(text(
        "SELECT count(*) FROM ai_memory WHERE id = :id"
    ), {"id": row_id}).scalar()
    assert gone == 0


def test_api_patch_rejects_empty_payload(test_db):
    import pytest
    from fastapi import HTTPException

    from backend.api.routes.memory import PatchPayload, memory_patch
    from backend.memory.ai_memory import remember

    remember(test_db, "rule:t1", "v1", category="rule", scope="test1")
    row_id = test_db.execute(text("SELECT id FROM ai_memory")).scalar()

    with pytest.raises(HTTPException) as exc:
        memory_patch(row_id, PatchPayload(), db=test_db)
    assert exc.value.status_code == 400


def test_api_404_on_unknown_id(test_db):
    import pytest
    from fastapi import HTTPException

    from backend.api.routes.memory import memory_delete
    from backend.memory.ai_memory import _ensure_schema

    _ensure_schema(test_db)
    with pytest.raises(HTTPException) as exc:
        memory_delete(9999, db=test_db)
    assert exc.value.status_code == 404
