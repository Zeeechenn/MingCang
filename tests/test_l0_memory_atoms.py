"""L0 Memory / Knowledge Base contract tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text


def test_create_memory_atom_clamps_and_upserts_by_source_ref(test_db):
    from backend.memory.l0_memory import create_memory_atom, list_memory_atoms

    first = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="thesis",
        summary="光模块订单兑现是核心变量",
        source_type="test",
        source_ref="l0-test-1",
        trust_state="pending",
        importance=99,
        confidence=2.0,
    )
    second = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="risk",
        summary="海外客户资本开支下修会破坏 thesis",
        source_type="test",
        source_ref="l0-test-1",
        trust_state="raw",
        importance=-3,
        confidence=-1.0,
    )

    assert first["id"] == second["id"]
    assert second["importance"] == 1
    assert second["confidence"] == 0.0
    rows = list_memory_atoms(test_db, scope_type="stock", scope_key="300308")
    assert len(rows) == 1
    assert rows[0]["summary"] == "海外客户资本开支下修会破坏 thesis"


def test_create_memory_atom_cannot_create_trusted_or_refuted(test_db):
    from backend.memory.l0_memory import create_memory_atom

    with pytest.raises(ValueError, match="cannot create 'trusted'"):
        create_memory_atom(
            test_db,
            scope_type="stock",
            scope_key="300308",
            memory_type="lesson",
            summary="trusted must be gated",
            source_type="test",
            trust_state="trusted",
        )
    with pytest.raises(ValueError, match="cannot create 'refuted'"):
        create_memory_atom(
            test_db,
            scope_type="stock",
            scope_key="300308",
            memory_type="lesson",
            summary="refuted must be gated",
            source_type="test",
            trust_state="refuted",
        )


def test_create_memory_atom_cannot_downgrade_promoted_atom_by_source_ref(test_db):
    from backend.memory.l0_memory import create_memory_atom, list_memory_atoms, promote_atom

    atom = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="lesson",
        summary="需要人工确认后才可信",
        source_type="test",
        source_ref="protected-ref",
        trust_state="pending",
    )
    promote_atom(test_db, atom["id"], confirmed_by="tester")

    with pytest.raises(ValueError, match="use promote/refute gates"):
        create_memory_atom(
            test_db,
            scope_type="stock",
            scope_key="300308",
            memory_type="lesson",
            summary="试图降级",
            source_type="test",
            source_ref="protected-ref",
            trust_state="pending",
        )

    rows = list_memory_atoms(test_db, scope_type="stock", scope_key="300308")
    assert rows[0]["trust_state"] == "trusted"
    assert rows[0]["summary"] == "需要人工确认后才可信"


def test_create_memory_atom_cannot_overwrite_refuted_atom_by_source_ref(test_db):
    from backend.memory.l0_memory import create_memory_atom, list_memory_atoms, refute_atom

    atom = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="risk",
        summary="待否定风险",
        source_type="test",
        source_ref="refuted-ref",
        trust_state="pending",
    )
    refute_atom(test_db, atom["id"], confirmed_by="tester", reason="证据不支持")

    with pytest.raises(ValueError, match="use promote/refute gates"):
        create_memory_atom(
            test_db,
            scope_type="stock",
            scope_key="300308",
            memory_type="risk",
            summary="试图恢复 pending",
            source_type="test",
            source_ref="refuted-ref",
            trust_state="pending",
        )

    rows = list_memory_atoms(
        test_db,
        scope_type="stock",
        scope_key="300308",
        trust_state="refuted",
    )
    assert rows[0]["summary"] == "待否定风险"


def test_list_memory_atoms_filters_query_before_limit(test_db):
    from backend.memory.l0_memory import create_memory_atom, list_memory_atoms

    for i in range(25):
        create_memory_atom(
            test_db,
            scope_type="stock",
            scope_key="300308",
            memory_type="risk",
            summary=f"普通风险 {i}",
            source_type="test",
            source_ref=f"ordinary-{i}",
            trust_state="pending",
            importance=5,
        )
    match = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="lesson",
        summary="稀有关键词：光模块订单验证",
        source_type="test",
        source_ref="rare-match",
        trust_state="pending",
        importance=1,
    )

    rows = list_memory_atoms(
        test_db,
        scope_type="stock",
        scope_key="300308",
        q="光模块订单",
        limit=3,
    )

    assert [row["id"] for row in rows] == [match["id"]]


def test_build_l0_context_separates_trusted_pending_and_legacy(test_db):
    from backend.memory.ai_memory import remember
    from backend.memory.l0_memory import build_l0_context, create_memory_atom, promote_atom
    from backend.memory.stock_memory import create_stock_memory

    trusted = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="thesis",
        summary="可信 thesis：订单兑现改善",
        source_type="test",
        source_ref="trusted-atom",
        trust_state="pending",
    )
    promote_atom(test_db, trusted["id"], confirmed_by="tester")
    create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="risk",
        summary="待确认风险：客户砍单",
        source_type="test",
        source_ref="pending-atom",
        trust_state="pending",
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="event",
        summary="旧 stock memory 事件",
        source_type="test",
    )
    remember(test_db, "pref:risk", "用户偏好：不追高", category="preference")

    ctx = build_l0_context(
        test_db,
        scope_type="stock",
        scope_key="300308",
        limit=5,
        include_legacy=True,
    )

    assert ctx["trusted_memory"][0]["summary"] == "可信 thesis：订单兑现改善"
    assert ctx["pending_memory"][0]["summary"] == "待确认风险：客户砍单"
    assert any(row["trust_state"] == "legacy_import_pending" for row in ctx["legacy_memory"])
    assert "【L0 trusted memory】" in ctx["text"]
    assert "【L0 pending/raw memory】" in ctx["text"]
    assert "【L0 legacy memory" in ctx["text"]


def test_build_l0_context_filters_archived_refuted_expired_and_marks_usage(test_db):
    from backend.memory.l0_memory import (
        build_l0_context,
        create_memory_atom,
        promote_atom,
        refute_atom,
    )

    kept = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="lesson",
        summary="可信教训",
        source_type="test",
        source_ref="kept",
        trust_state="pending",
    )
    promote_atom(test_db, kept["id"], confirmed_by="tester")
    refuted = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="risk",
        summary="已经被否定",
        source_type="test",
        source_ref="refuted",
        trust_state="pending",
    )
    refute_atom(test_db, refuted["id"], confirmed_by="tester")
    archived = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="event",
        summary="已经归档",
        source_type="test",
        source_ref="archived",
        trust_state="pending",
    )
    test_db.execute(
        text("UPDATE memory_atoms SET trust_state='archived' WHERE id=:id"),
        {"id": archived["id"]},
    )
    expired = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="event",
        summary="已经过期",
        source_type="test",
        source_ref="expired",
        trust_state="pending",
        ttl_days=1,
    )
    old = (datetime.utcnow() - timedelta(days=3)).isoformat(timespec="seconds")
    test_db.execute(
        text("UPDATE memory_atoms SET updated_at=:old WHERE id=:id"),
        {"old": old, "id": expired["id"]},
    )
    test_db.commit()

    ctx = build_l0_context(test_db, scope_type="stock", scope_key="300308", limit=5)

    assert [row["id"] for row in ctx["trusted_memory"]] == [kept["id"]]
    assert ctx["pending_memory"] == []
    assert "已经被否定" not in ctx["text"]
    assert "已经归档" not in ctx["text"]
    assert "已经过期" not in ctx["text"]
    used = test_db.execute(
        text("SELECT last_used_at FROM memory_atoms WHERE id=:id"),
        {"id": kept["id"]},
    ).scalar()
    assert used is not None


def test_build_l0_context_can_be_read_only(test_db):
    from backend.memory.l0_memory import build_l0_context, create_memory_atom, promote_atom

    atom = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="thesis",
        summary="只读召回",
        source_type="test",
        source_ref="readonly",
        trust_state="pending",
    )
    promote_atom(test_db, atom["id"], confirmed_by="tester")

    ctx = build_l0_context(
        test_db,
        scope_type="stock",
        scope_key="300308",
        record_usage=False,
    )

    used = test_db.execute(
        text("SELECT last_used_at FROM memory_atoms WHERE id=:id"),
        {"id": atom["id"]},
    ).scalar()
    audit_count = test_db.execute(
        text("SELECT count(*) FROM audit_log_fts WHERE event_type='l0_memory.recall'")
    ).scalar()
    assert ctx["used_memory_atom_ids"] == [atom["id"]]
    assert used is None
    assert audit_count == 0
