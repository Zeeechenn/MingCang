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
        "source_verified": True,
        "source_verified_by": "tester",
        "thesis_ref": "ateacher-2026-06-05-optical",
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


def test_m45_falsification_scoreboard_candidate_summary_creates_only_pending_candidate(test_db):
    from backend.data.database import MemoryAtom, MemoryPromotionCandidate, StockMemoryItem
    from backend.tools.m45_falsification_scoreboard import (
        execute_scoreboard,
        normalize_item,
    )

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


def test_m45_falsification_scoreboard_rejects_invalid_lane():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="invalid lane"):
        normalize_item(_item(lane="alpha_oracle"))


def test_m45_falsification_scoreboard_rejects_invalid_result():
    from backend.tools.m45_falsification_scoreboard import normalize_item

    with pytest.raises(ValueError, match="invalid result"):
        normalize_item(_item(result="strong_buy"))
