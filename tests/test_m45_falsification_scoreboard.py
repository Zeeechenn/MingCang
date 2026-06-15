"""M45 falsification scoreboard contract tests.

The scoreboard is dry-run-first. Execute may write/update ReviewCase rows and
pending MemoryPromotionCandidate rows only; it must not touch official signals,
decision runs, positions, or trusted memory surfaces.
"""
from __future__ import annotations

import json

import pytest


def _item(**overrides):
    base = {
        "symbol": "300308",
        "as_of": "2026-06-05",
        "lane": "falsification",
        "result": "hit",
        "source_ref": "m45-scoreboard-300308-2026-06-05-falsification",
        "source_url": "local://m45/falsification-scoreboard/2026-06-05",
        "source_kind": "direct_source",
        "source_tier": "filing",
        "evidence_level": "verified",
        "source_verified": True,
        "source_verified_by": "tester",
        "thesis_ref": "track-2026-06-05-optical",
        "evidence_summary": (
            "Invalidation alarm fired before the loss threshold materialized."
        ),
        "review_payload": {
            "alarm_fired_at": "2026-06-05",
            "loss_materialized_at": None,
            "max_drawdown_pct": -1.2,
        },
    }
    base.update(overrides)
    return base


def _protected_counts(db):
    from backend.data.database import (
        DecisionRun,
        MemoryAtom,
        MemoryPromotionCandidate,
        Position,
        ReviewCase,
        Signal,
        StockMemoryItem,
    )

    return {
        "review_cases": db.query(ReviewCase).count(),
        "memory_candidates": db.query(MemoryPromotionCandidate).count(),
        "memory_atoms": db.query(MemoryAtom).count(),
        "stock_memory_items": db.query(StockMemoryItem).count(),
        "signals": db.query(Signal).count(),
        "decision_runs": db.query(DecisionRun).count(),
        "positions": db.query(Position).count(),
    }


def _seed_forward_thesis(db, *, symbol="300308", source_ref="track-2026-06-05-optical"):
    from backend.research.forward_thesis import create_forward_thesis

    return create_forward_thesis(
        db,
        symbol=symbol,
        statement=f"{symbol} imported thesis",
        horizon_date="2026-12-31",
        status="draft",
        evidence_manifest=[{
            "kind": "ledger_snapshot",
            "ref": source_ref,
            "as_of": "2026-06-05",
            "summary": "seeded direct-source thesis",
        }],
        invalidation_conditions=["source thesis is refuted"],
        follow_up_metrics=["review outcome"],
        next_review_date="2026-06-19",
        review_cadence_days=14,
    )


def test_m45_falsification_scoreboard_dry_run_does_not_write(test_db):
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    result = execute_scoreboard(test_db, [normalize_item(_item())], execute=False)

    assert result["mode"] == "dry_run"
    assert result["production_impact"] == "none"
    assert result["safety"]["writes_db"] is False
    assert result["safety"]["touches_official_signal"] is False
    assert result["safety"]["touches_decision_run"] is False
    assert result["safety"]["touches_position"] is False
    assert result["safety"]["writes_trusted_memory"] is False
    assert result["count"] == 1
    assert result["planned"][0]["scoreboard_key"] == {
        "source_ref": "m45-scoreboard-300308-2026-06-05-falsification",
        "lane": "falsification",
        "as_of": "2026-06-05",
    }
    assert result["planned"][0]["review_case"]["symbol"] == "300308"
    assert result["planned"][0]["review_case"]["as_of"] == "2026-06-05"
    assert _protected_counts(test_db) == {
        "review_cases": 0,
        "memory_candidates": 0,
        "memory_atoms": 0,
        "stock_memory_items": 0,
        "signals": 0,
        "decision_runs": 0,
        "positions": 0,
    }


def test_m45_falsification_scoreboard_execute_writes_review_case_only_for_core_row(test_db):
    from backend.data.database import DecisionRun, Position, ReviewCase, Signal
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)
    test_db.add(Signal(
        symbol="300308",
        date="2026-06-05",
        composite_score=10.0,
        recommendation="观望",
        confidence="低",
    ))
    test_db.add(DecisionRun(run_id="m45-scoreboard-side-effect-guard", run_type="test", symbol="300308"))
    test_db.add(Position(
        symbol="300308",
        quantity=100,
        avg_cost=10,
        opened_at="2026-06-05",
    ))
    test_db.commit()

    result = execute_scoreboard(test_db, [normalize_item(_item())], execute=True)

    assert result["mode"] == "execute"
    assert result["production_impact"] == "none"
    assert result["safety"]["writes_db"] is True
    assert result["safety"]["touches_official_signal"] is False
    assert result["safety"]["touches_decision_run"] is False
    assert result["safety"]["touches_position"] is False
    assert result["safety"]["writes_trusted_memory"] is False
    assert result["writes"][0]["review_case_id"] is not None

    review = test_db.query(ReviewCase).one()
    payload = json.loads(review.review_payload_json)
    assert review.symbol == "300308"
    assert review.as_of == "2026-06-05"
    assert payload["m45_scoreboard"]["lane"] == "falsification"
    assert payload["m45_scoreboard"]["result"] == "hit"
    assert payload["m45_scoreboard"]["source_ref"] == "m45-scoreboard-300308-2026-06-05-falsification"
    assert test_db.query(Signal).count() == 1
    assert test_db.query(DecisionRun).count() == 1
    assert test_db.query(Position).count() == 1


def test_m45_falsification_scoreboard_same_source_lane_as_of_is_idempotent_and_updates(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)
    first = execute_scoreboard(test_db, [normalize_item(_item(result="miss"))], execute=True)
    second = execute_scoreboard(
        test_db,
        [normalize_item(_item(
            result="hit",
            evidence_summary="Updated after confirming the alarm preceded the drawdown.",
            review_payload={"max_drawdown_pct": -4.8},
        ))],
        execute=True,
    )

    assert first["writes"][0]["review_case_id"] == second["writes"][0]["review_case_id"]
    assert test_db.query(ReviewCase).count() == 1
    review = test_db.query(ReviewCase).one()
    payload = json.loads(review.review_payload_json)
    assert payload["m45_scoreboard"]["result"] == "hit"
    assert payload["m45_scoreboard"]["evidence_summary"] == (
        "Updated after confirming the alarm preceded the drawdown."
    )
    assert payload["m45_scoreboard"]["review_payload"] == {"max_drawdown_pct": -4.8}
    assert len(payload["m45_scoreboard_events"]) == 1
    assert payload["m45_scoreboard_events"][0]["result"] == "hit"


def test_m45_falsification_scoreboard_different_lane_same_symbol_date_appends_event(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)
    execute_scoreboard(test_db, [normalize_item(_item())], execute=True)
    execute_scoreboard(
        test_db,
        [normalize_item(_item(
            lane="defensive_value",
            result="helped",
            source_ref="m45-scoreboard-300308-2026-06-05-defensive",
            review_payload={
                "system_on_drawdown_pct": -2.0,
                "system_off_drawdown_pct": -5.0,
                "sample_size": 1,
            },
        ))],
        execute=True,
    )

    assert test_db.query(ReviewCase).count() == 1
    payload = json.loads(test_db.query(ReviewCase).one().review_payload_json)
    assert [event["lane"] for event in payload["m45_scoreboard_events"]] == [
        "falsification",
        "defensive_value",
    ]
    assert payload["m45_scoreboard"]["lane"] == "defensive_value"


def test_m45_falsification_scoreboard_candidate_summary_creates_only_pending_candidate(test_db):
    from backend.data.database import MemoryAtom, MemoryPromotionCandidate, StockMemoryItem
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)
    raw = _item(
        candidate_summary={
            "summary": "Falsification alarms should be reviewed before loss thresholds materialize.",
            "memory_type": "lesson",
            "importance": 4,
            "confidence": 0.7,
        },
    )

    result = execute_scoreboard(test_db, [normalize_item(raw)], execute=True)

    assert result["writes"][0]["memory_candidate_id"] is not None
    candidate = test_db.query(MemoryPromotionCandidate).one()
    assert candidate.symbol == "300308"
    assert candidate.memory_type == "lesson"
    assert candidate.source_trust == "pending"
    assert candidate.promoted_at is None
    assert candidate.memory_atom_id is None
    assert candidate.stock_memory_item_id is None
    assert candidate.source_ref is not None
    assert "m45-scoreboard-300308-2026-06-05-falsification" in candidate.source_ref
    assert test_db.query(MemoryAtom).count() == 0
    assert test_db.query(StockMemoryItem).count() == 0


def test_m45_falsification_scoreboard_not_due_rejects_candidate_summary(test_db):
    from backend.data.database import MemoryPromotionCandidate, ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)
    raw = _item(
        result="not_due",
        candidate_summary={
            "summary": "Too early to learn from this thesis.",
            "memory_type": "lesson",
        },
    )

    with pytest.raises(ValueError, match="not_due events cannot create memory candidates"):
        execute_scoreboard(test_db, [normalize_item(raw)], execute=True)

    assert test_db.query(ReviewCase).count() == 0
    assert test_db.query(MemoryPromotionCandidate).count() == 0


def test_m45_falsification_scoreboard_execute_requires_forward_thesis(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    with pytest.raises(ValueError, match="forward_thesis_not_found"):
        execute_scoreboard(test_db, [normalize_item(_item())], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_requires_direct_verified_source(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="source_not_verified"):
        execute_scoreboard(test_db, [normalize_item(_item(source_verified=False))], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_requires_direct_source_kind(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="source_kind_not_direct_source"):
        execute_scoreboard(test_db, [normalize_item(_item(source_kind="handoff_context"))], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_rejects_derived_summary_source_kind(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="source_kind_not_direct_source"):
        execute_scoreboard(test_db, [normalize_item(_item(source_kind="derived_summary"))], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_rejects_social_only_source_tier(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="source_tier_social_only"):
        execute_scoreboard(test_db, [normalize_item(_item(source_tier="social_lead"))], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_rejects_needs_check_evidence_level(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="evidence_level_needs_check"):
        execute_scoreboard(test_db, [normalize_item(_item(evidence_level="needs_check"))], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_requires_source_verified_by(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="missing_source_verified_by"):
        execute_scoreboard(test_db, [normalize_item(_item(source_verified_by=None))], execute=True)

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_execute_requires_source_locator(test_db):
    from backend.data.database import ReviewCase
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

    _seed_forward_thesis(test_db)

    with pytest.raises(ValueError, match="missing_source_locator"):
        execute_scoreboard(
            test_db,
            [normalize_item(_item(source_url=None, evidence_ref=None))],
            execute=True,
        )

    assert test_db.query(ReviewCase).count() == 0


def test_m45_falsification_scoreboard_rejects_invalid_lane():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="invalid lane"):
        normalize_item(_item(lane="alpha_oracle"))


def test_m45_falsification_scoreboard_rejects_invalid_result():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="invalid result"):
        normalize_item(_item(result="strong_buy"))


def test_m45_falsification_scoreboard_invalidation_catch_requires_auditable_payload():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="review_payload missing required fields"):
        normalize_item(_item(
            lane="invalidation_catch",
            result="caught_before_loss",
            review_payload={"alarm_fired_at": "2026-06-05"},
        ))


def test_m45_falsification_scoreboard_defensive_value_requires_comparison_payload():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="review_payload missing required fields"):
        normalize_item(_item(
            lane="defensive_value",
            result="helped",
            review_payload={"system_on_drawdown_pct": -2.0},
        ))


def test_m45_falsification_scoreboard_breadth_hit_requires_adoption_payload():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="review_payload missing required fields"):
        normalize_item(_item(
            lane="breadth_hit",
            result="hit",
            review_payload={"surfaced_by": "ai"},
        ))


def test_m45_falsification_scoreboard_accepts_not_due_without_lane_payload():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    item = normalize_item(_item(
        lane="invalidation_catch",
        result="not_due",
        evidence_summary="Review cadence has not reached the due date.",
        review_payload=None,
    ))

    assert item.lane == "invalidation_catch"
    assert item.result == "not_due"


def test_m45_falsification_scoreboard_dry_run_surfaces_lane_contract():
    from backend.tools.m45_falsification_scoreboard import execute_scoreboard, normalize_item

    result = execute_scoreboard(
        None,
        [normalize_item(_item(
            lane="defensive_value",
            result="helped",
            review_payload={
                "system_on_drawdown_pct": -2.0,
                "system_off_drawdown_pct": -5.0,
                "sample_size": 1,
            },
        ))],
        execute=False,
    )

    payload = result["planned"][0]["review_case"]["review_payload"]["m45_scoreboard"]
    assert payload["ledger_contract"] == {
        "lane": "defensive_value",
        "required_fields": [
            "system_on_drawdown_pct",
            "system_off_drawdown_pct",
            "sample_size",
        ],
    }
