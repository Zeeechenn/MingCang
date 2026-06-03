"""M39 Forward Thesis Beta — hermetic isolated-sqlite tests.

All ORM/module imports are deferred inside test function bodies.
Uses the test_db fixture from conftest.py (in-memory SQLite + create_all).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_thesis(db, statement="storage cycle recovery is becoming trackable", horizon="2026-12-31", **kwargs):
    from backend.research.forward_thesis import create_forward_thesis
    return create_forward_thesis(db, statement=statement, horizon_date=horizon, **kwargs)


# ---------------------------------------------------------------------------
# create / get / list
# ---------------------------------------------------------------------------

def test_create_forward_thesis_returns_expected_keys(test_db):
    result = _make_thesis(test_db)
    expected_keys = {
        "id", "symbol", "statement", "status", "horizon_date",
        "confidence_low", "confidence_high",
        "evidence_manifest", "invalidation_conditions", "follow_up_metrics",
        "next_review_date", "review_cadence_days",
        "thesis_id", "theme_hypothesis_id", "universe_snapshot_id",
        "created_at", "updated_at",
    }
    assert expected_keys.issubset(set(result.keys())), (
        f"missing keys: {expected_keys - set(result.keys())}"
    )
    assert result["id"] is not None
    assert result["statement"] == "storage cycle recovery is becoming trackable"
    assert result["status"] == "draft"


def test_create_forward_thesis_idempotent_on_same_symbol_statement_horizon(test_db):
    r1 = _make_thesis(test_db, symbol="600519")
    r2 = _make_thesis(test_db, symbol="600519")
    assert r1["id"] == r2["id"]


def test_create_forward_thesis_symbol_is_part_of_idempotency_key(test_db):
    r1 = _make_thesis(test_db, symbol="600519")
    r2 = _make_thesis(test_db, symbol="300308")
    assert r1["id"] != r2["id"]


def test_create_forward_thesis_null_horizon_idempotent_per_symbol(test_db):
    r1 = _make_thesis(test_db, statement="null horizon thesis", horizon=None, symbol="600519")
    r2 = _make_thesis(test_db, statement="null horizon thesis", horizon=None, symbol="600519")
    r3 = _make_thesis(test_db, statement="null horizon thesis", horizon=None, symbol="300308")
    assert r1["id"] == r2["id"]
    assert r1["id"] != r3["id"]


def test_get_forward_thesis_returns_none_for_missing_id(test_db):
    from backend.research.forward_thesis import get_forward_thesis
    assert get_forward_thesis(test_db, 99999) is None


def test_list_forward_theses_filter_by_status(test_db):
    from backend.research.forward_thesis import create_forward_thesis, list_forward_theses

    create_forward_thesis(test_db, statement="stmt A", horizon_date="2026-01-01", status="draft")
    create_forward_thesis(test_db, statement="stmt B", horizon_date="2026-01-02", status="draft")
    create_forward_thesis(test_db, statement="stmt C", horizon_date="2026-01-03", status="active")

    drafts = list_forward_theses(test_db, status="draft")
    assert len(drafts) == 2
    actives = list_forward_theses(test_db, status="active")
    assert len(actives) == 1


# ---------------------------------------------------------------------------
# Confidence band
# ---------------------------------------------------------------------------

def test_confidence_band_low_must_not_exceed_high(test_db):
    from backend.research.forward_thesis import create_forward_thesis
    with pytest.raises(ValueError, match="must not exceed"):
        create_forward_thesis(
            test_db,
            statement="band test bad",
            horizon_date="2026-06-01",
            confidence_low=0.7,
            confidence_high=0.3,
        )


def test_confidence_band_valid_low_less_than_high(test_db):
    from backend.research.forward_thesis import create_forward_thesis
    result = create_forward_thesis(
        test_db,
        statement="band test good",
        horizon_date="2026-06-01",
        confidence_low=0.35,
        confidence_high=0.60,
    )
    assert result["confidence_low"] == pytest.approx(0.35)
    assert result["confidence_high"] == pytest.approx(0.60)


def test_confidence_band_equal_low_high_allowed(test_db):
    from backend.research.forward_thesis import create_forward_thesis
    result = create_forward_thesis(
        test_db,
        statement="band test equal",
        horizon_date="2026-06-01",
        confidence_low=0.5,
        confidence_high=0.5,
    )
    assert result["confidence_low"] == pytest.approx(0.5)
    assert result["confidence_high"] == pytest.approx(0.5)


def test_update_confidence_band_clamps_above_one(test_db):
    from backend.research.forward_thesis import update_confidence_band
    row = _make_thesis(test_db)
    result = update_confidence_band(
        test_db, row["id"], confidence_low=0.4, confidence_high=1.5, as_of="2026-01-01"
    )
    assert result["confidence_high"] == pytest.approx(1.0)


def test_update_confidence_band_clamps_below_zero(test_db):
    from backend.research.forward_thesis import update_confidence_band
    row = _make_thesis(test_db)
    result = update_confidence_band(
        test_db, row["id"], confidence_low=-0.1, confidence_high=0.5, as_of="2026-01-01"
    )
    assert result["confidence_low"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Evidence manifest
# ---------------------------------------------------------------------------

def test_evidence_manifest_round_trip(test_db):
    from backend.research.forward_thesis import create_forward_thesis
    manifest = [
        {"kind": "universe_snapshot", "ref": 1, "as_of": "2026-01-01", "summary": "test"},
        {"kind": "review_case", "ref": 42, "as_of": "2026-01-02", "summary": "rc"},
    ]
    result = create_forward_thesis(
        test_db,
        statement="manifest round trip",
        horizon_date="2026-07-01",
        evidence_manifest=manifest,
    )
    assert result["evidence_manifest"] == manifest


def test_evidence_manifest_pointer_only(test_db):
    """Only declared pointer fields (kind/ref/as_of/summary) survive round-trip if that's all we sent."""
    from backend.research.forward_thesis import create_forward_thesis
    manifest = [
        {"kind": "m29_ledger_entry", "ref": "abc123", "as_of": "2026-01-01", "summary": "entry"},
    ]
    result = create_forward_thesis(
        test_db,
        statement="manifest pointer only",
        horizon_date="2026-07-02",
        evidence_manifest=manifest,
    )
    item = result["evidence_manifest"][0]
    # Only the four pointer fields should be present
    assert set(item.keys()) == {"kind", "ref", "as_of", "summary"}


def test_attach_evidence_manifest_replaces_existing(test_db):
    from backend.research.forward_thesis import attach_evidence_manifest
    row = _make_thesis(test_db, statement="manifest replace", horizon="2026-08-01",
                       evidence_manifest=[{"kind": "review_case", "ref": 1, "as_of": None, "summary": "old"}])
    new_manifest = [{"kind": "universe_snapshot", "ref": 2, "as_of": "2026-06-01", "summary": "new"}]
    updated = attach_evidence_manifest(test_db, row["id"], manifest=new_manifest, as_of="2026-06-01")
    assert updated["evidence_manifest"] == new_manifest
    assert len(updated["evidence_manifest"]) == 1
    assert updated["evidence_manifest"][0]["summary"] == "new"


# ---------------------------------------------------------------------------
# Status state machine
# ---------------------------------------------------------------------------

def test_status_state_machine_draft_to_active(test_db):
    from backend.research.forward_thesis import update_forward_thesis_status
    row = _make_thesis(test_db, statement="sm draft active", horizon="2026-09-01")
    result = update_forward_thesis_status(test_db, row["id"], "active")
    assert result["status"] == "active"


def test_status_state_machine_active_to_superseded(test_db):
    from backend.research.forward_thesis import update_forward_thesis_status
    row = _make_thesis(test_db, statement="sm active superseded", horizon="2026-09-02")
    update_forward_thesis_status(test_db, row["id"], "active")
    result = update_forward_thesis_status(test_db, row["id"], "superseded")
    assert result["status"] == "superseded"


def test_status_state_machine_invalid_transition_raises(test_db):
    from backend.research.forward_thesis import update_forward_thesis_status
    row = _make_thesis(test_db, statement="sm invalid", horizon="2026-09-03")
    update_forward_thesis_status(test_db, row["id"], "active")
    update_forward_thesis_status(test_db, row["id"], "superseded")
    with pytest.raises(ValueError, match="not allowed"):
        update_forward_thesis_status(test_db, row["id"], "active")


# ---------------------------------------------------------------------------
# Config flag guard
# ---------------------------------------------------------------------------

def test_forward_thesis_disabled_when_flag_false(test_db):
    from backend.research.forward_thesis import create_forward_thesis
    with patch("backend.research.forward_thesis.settings") as mock_settings:
        mock_settings.forward_thesis_enabled = False
        result = create_forward_thesis(
            test_db, statement="disabled test", horizon_date="2026-01-01"
        )
    assert result == {}
    # Confirm no rows were written
    from backend.data.database import ForwardThesis
    count = test_db.query(ForwardThesis).count()
    assert count == 0


# ---------------------------------------------------------------------------
# Bare int cross-references
# ---------------------------------------------------------------------------

def test_link_ids_stored_as_bare_ints(test_db):
    from backend.research.forward_thesis import create_forward_thesis
    result = create_forward_thesis(
        test_db,
        statement="bare int refs",
        horizon_date="2026-10-01",
        thesis_id=99,
        theme_hypothesis_id=7,
        universe_snapshot_id=3,
    )
    assert result["thesis_id"] == 99
    assert result["theme_hypothesis_id"] == 7
    assert result["universe_snapshot_id"] == 3


# ---------------------------------------------------------------------------
# Bridge: attach_forward_evidence on ThemeHypothesis
# ---------------------------------------------------------------------------

def test_attach_forward_evidence_populates_hyp_column(test_db):
    from backend.research.theme_hypothesis_engine import (
        attach_forward_evidence,
        create_hypothesis,
        create_theme,
    )
    theme = create_theme(test_db, theme_name="光通信主题", description="desc")
    hyp = create_hypothesis(
        test_db,
        theme_id=theme["id"],
        statement="存储周期复苏是可追踪的",
    )
    payload = {
        "forward_thesis_id": 1,
        "universe_snapshot_id": 2,
        "attached_at": "2026-06-01T00:00:00",
        "schema_version": "m39.v1",
    }
    result = attach_forward_evidence(test_db, hyp["id"], evidence_payload=payload, as_of="2026-06-01")
    assert result["forward_evidence_ref"] == payload


def test_attach_forward_evidence_raises_for_missing_hypothesis(test_db):
    from backend.research.theme_hypothesis_engine import attach_forward_evidence
    with pytest.raises(ValueError, match="hypothesis 99999 not found"):
        attach_forward_evidence(
            test_db,
            99999,
            evidence_payload={"forward_thesis_id": 1, "schema_version": "m39.v1"},
            as_of="2026-06-01",
        )


# ---------------------------------------------------------------------------
# No forbidden fields in _row_to_dict output
# ---------------------------------------------------------------------------

def test_no_price_target_field_in_dict(test_db):
    result = _make_thesis(test_db, statement="no forbidden fields", horizon="2026-11-01")
    forbidden_substrings = {"price", "target", "direction", "buy_score", "recommendation",
                            "signal_score", "entry_signal", "predicted_move"}
    for key in result.keys():
        for bad in forbidden_substrings:
            assert bad not in key.lower(), (
                f"forbidden field found in dict: {key!r} (matches {bad!r})"
            )
