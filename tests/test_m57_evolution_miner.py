from __future__ import annotations

import json

from sqlalchemy import text


def _trace(db, *, trace_type: str, content: str, subject: str | None = None, symbols=None, themes=None, payload=None):
    from backend.memory.evolution_trace import NAMESPACE_PERSONAL_PREFERENCE, record_trace

    return record_trace(
        db,
        trace_type=trace_type,
        namespace=NAMESPACE_PERSONAL_PREFERENCE,
        subject=subject,
        symbols=symbols or [],
        themes=themes or [],
        content=content,
        payload=payload,
        source_type="unit",
        source_ref=f"unit:{trace_type}:{content[:8]}",
        event_time="2026-07-01T09:00:00",
    )


def test_m57_miner_generates_stable_pending_candidates_with_source_events(test_db):
    from backend.memory.evolution_miner import run_miner

    first = _trace(test_db, trace_type="chat.user", content="我偏好短结论，不要长篇解释")
    second = _trace(test_db, trace_type="chat.user", content="我偏好短结论，不要长篇解释")
    _trace(test_db, trace_type="research.note", content="光模块 CPO 需要关注订单兑现", symbols=["300308"], themes=["CPO"])
    _trace(test_db, trace_type="review.note", content="光模块 CPO 需要关注订单兑现", symbols=["300308"], themes=["CPO"])

    result = run_miner(test_db, min_support=2, cooldown_days=7)
    again = run_miner(test_db, min_support=2, cooldown_days=7)

    assert result["created"] >= 2
    assert again["created"] == 0

    profile = test_db.execute(
        text("SELECT * FROM memory_profiles WHERE source_ref LIKE 'm57_miner:%' LIMIT 1")
    ).mappings().one()
    evidence = json.loads(profile["atom_ids_json"])
    assert profile["trust_state"] == "pending"
    assert {first["id"], second["id"]} <= set(evidence["source_event_ids"])

    trusted = test_db.execute(
        text("SELECT count(*) FROM memory_atoms WHERE trust_state = 'trusted'")
    ).scalar_one()
    assert trusted == 0


def test_m57_miner_does_not_generate_without_evidence(test_db):
    from backend.memory.evolution_miner import run_miner

    _trace(test_db, trace_type="chat.user", content="我偏好短结论，不要长篇解释")

    result = run_miner(test_db, min_support=2)

    assert result["created"] == 0
    assert test_db.execute(text("SELECT count(*) FROM memory_profiles")).scalar_one() == 0
    assert test_db.execute(text("SELECT count(*) FROM memory_atoms")).scalar_one() == 0


def test_m57_miner_repeated_risk_and_confirmed_action_route_to_pending_atoms(test_db):
    from backend.memory.evolution_miner import run_miner

    _trace(test_db, trace_type="chat.user", content="风险是不能追高，仓位要小", symbols=["600519"])
    _trace(test_db, trace_type="review.note", content="风险是不能追高，仓位要小", symbols=["600519"])
    _trace(
        test_db,
        trace_type="action.confirmed",
        content="确认加入观察池",
        symbols=["600519"],
        payload={"action": "watchlist.add"},
    )
    _trace(
        test_db,
        trace_type="action.confirmed",
        content="确认加入观察池",
        symbols=["300308"],
        payload={"action": "watchlist.add"},
    )

    result = run_miner(test_db, min_support=2)

    assert result["created"] >= 2
    atoms = test_db.execute(
        text("SELECT memory_type, trust_state, evidence_json FROM memory_atoms ORDER BY id")
    ).mappings().all()
    assert {row["memory_type"] for row in atoms} >= {"risk", "lesson"}
    assert {row["trust_state"] for row in atoms} == {"pending"}
    assert all(json.loads(row["evidence_json"])["source_event_ids"] for row in atoms)
