from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import text


def _seed_mined_candidate(db) -> int:
    from backend.memory.evolution_miner import run_miner
    from backend.memory.evolution_trace import NAMESPACE_RESEARCH_THESIS, record_trace

    record_trace(
        db,
        trace_type="research.note",
        namespace=NAMESPACE_RESEARCH_THESIS,
        subject="300308",
        symbols=["300308"],
        themes=["CPO"],
        content="光模块 CPO 订单兑现需要跟踪毛利率",
        event_time="2026-07-01T09:00:00",
    )
    record_trace(
        db,
        trace_type="review.note",
        namespace=NAMESPACE_RESEARCH_THESIS,
        subject="300308",
        symbols=["300308"],
        themes=["CPO"],
        content="光模块 CPO 订单兑现需要跟踪毛利率",
        event_time="2026-07-02T09:00:00",
    )
    run_miner(db, min_support=2)
    row = db.execute(
        text("SELECT id FROM memory_promotion_candidates WHERE source_trust = 'pending' LIMIT 1")
    ).first()
    assert row is not None
    return int(row.id)


def test_memory_evolution_candidate_detail_includes_source_events_and_diff(test_db, sample_stocks):
    from backend.api.routes.research import get_memory_evolution_candidate_detail

    candidate_id = _seed_mined_candidate(test_db)

    detail = get_memory_evolution_candidate_detail(candidate_id=candidate_id, db=test_db)

    assert detail["candidate"]["id"] == candidate_id
    assert detail["source_events"]
    assert detail["diff"]["candidate"]
    assert detail["diff"]["existing"] == []
    assert all("payload_json" not in event for event in detail["source_events"])


def test_memory_evolution_reject_requires_reason_and_writes_trace(test_db, sample_stocks):
    from backend.api.routes.research import reject_memory_evolution_candidate
    from backend.api.schemas import MemoryRejectRequest

    candidate_id = _seed_mined_candidate(test_db)

    with pytest.raises(HTTPException) as exc:
        reject_memory_evolution_candidate(
            candidate_id=candidate_id,
            request=MemoryRejectRequest(confirmed_by="leader", note=None),
            db=test_db,
        )
    assert exc.value.status_code == 400

    result = reject_memory_evolution_candidate(
        candidate_id=candidate_id,
        request=MemoryRejectRequest(confirmed_by="leader", note="证据不足"),
        db=test_db,
    )
    assert result["source_trust"] == "rejected"

    trace = test_db.execute(
        text("SELECT content, payload_json FROM evolution_traces WHERE trace_type='memory_evolution.reject'")
    ).mappings().one()
    assert "证据不足" in trace["content"]
    assert json.loads(trace["payload_json"])["candidate_id"] == candidate_id


def test_memory_evolution_archive_writes_audit_and_keeps_no_trusted(test_db, sample_stocks):
    from backend.api.routes.research import archive_memory_evolution_candidate
    from backend.api.schemas import MemoryArchiveRequest

    candidate_id = _seed_mined_candidate(test_db)

    result = archive_memory_evolution_candidate(
        candidate_id=candidate_id,
        request=MemoryArchiveRequest(confirmed_by="leader", reason="暂不采用"),
        db=test_db,
    )

    assert result["source_trust"] == "archived"
    assert test_db.execute(
        text("SELECT count(*) FROM memory_atoms WHERE trust_state = 'trusted'")
    ).scalar_one() == 0
    audit_count = test_db.execute(
        text("SELECT count(*) FROM audit_log_fts WHERE event_type='memory_evolution.archive'")
    ).scalar_one()
    assert audit_count == 1
