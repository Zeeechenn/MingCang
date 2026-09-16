from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from backend.evidence.decision_desk_readiness import (
    CARD_TYPES,
    build_readiness_report,
    select_evaluation_memory,
)

DAY = "2026-09-16"


def inputs():
    return {
        "as_of": DAY,
        "continuity": {"status": "complete", "days": [{
            "date": DAY, "status": "complete", "run_id": "run-1", "checks": {
                "artifact_panel": "complete", "batch_envelope_match": "matched",
                "run_envelope": "complete", "signal_batch_identity": "unique",
                "signal_run": "complete",
            },
        }]},
        "panel": {"as_of": DAY, "ledger_commit_state": "committed",
                  "artifact_contract": {"close_confirmed": True, "source_job_run_id": "run-1"},
                  "cards": [{"card_type": k, "status": "ready"} for k in CARD_TYPES]},
        "nav_evidence": {"snapshot": {"sha256_before": "a" * 64, "sha256_after": "a" * 64},
                         "lineage": {"price_basis_issues": [], "price_window": {"end": DAY},
                                     "corporate_actions": {"status": "authoritative"}}},
    }


def test_twenty_complete_days_do_not_certify_output_quality_or_returns():
    value = inputs()
    value["panel"]["cards"][3]["status"] = "missing"
    before = deepcopy(value)
    result = build_readiness_report(**value)
    assert result["gates"]["operational"]["status"] == "passed"
    assert result["gates"]["output_quality"]["blockers"] == ["event_risk:missing"]
    assert result["gates"]["economic"]["status"] == "blocked"
    assert result["certifies_returns"] is False
    assert value == before


@pytest.mark.parametrize("field,bad", [("as_of", "2026-09-15"), ("ledger_commit_state", "pending")])
def test_wrong_date_or_uncommitted_panel_cannot_pass(field, bad):
    value = inputs()
    value["panel"][field] = bad
    assert build_readiness_report(**value)["gates"]["output_quality"]["status"] == "blocked"


@pytest.mark.parametrize("status,lifecycle,reason,passes", [
    ("ready_zero", "stable", "no_candidates", True),
    ("ready_zero", "stable", "", False),
    ("not_applicable", "shadow", "zero_llm_policy", True),
    ("not_applicable", "stable", "producer_missing", False),
    ("missing", "shadow", "no_source", False),
])
def test_zero_and_shadow_states_require_explicit_reason(status, lifecycle, reason, passes):
    value = inputs()
    value["panel"]["cards"][3].update(status=status, lifecycle=lifecycle, payload={"reason": reason})
    result = build_readiness_report(**value)
    assert (result["gates"]["output_quality"]["status"] == "passed") is passes


def test_duplicate_cards_and_wrong_run_are_rejected():
    value = inputs()
    value["panel"]["cards"][1] = value["panel"]["cards"][0]
    value["panel"]["artifact_contract"]["source_job_run_id"] = "other"
    blockers = build_readiness_report(**value)["gates"]["output_quality"]["blockers"]
    assert "card_identity_order_or_count" in blockers
    assert "panel_run_mismatch_or_missing" in blockers


def test_old_complete_window_cannot_substitute_for_current_day():
    value = inputs()
    value["continuity"]["days"][0]["date"] = "2026-09-15"
    assert "requested_day_not_complete" in build_readiness_report(**value)["gates"]["operational"]["blockers"]


def test_price_issues_missing_actions_or_changed_hash_block_data():
    value = inputs()
    value["nav_evidence"]["snapshot"]["sha256_after"] = "b" * 64
    value["nav_evidence"]["lineage"]["corporate_actions"] = {"status": "not_available"}
    value["nav_evidence"]["lineage"]["price_basis_issues"] = [{"symbol": "AAA"}]
    blockers = build_readiness_report(**value)["gates"]["data"]["blockers"]
    assert set(blockers) == {"snapshot_hash_missing_or_changed", "price_basis_issues", "authoritative_corporate_actions_unavailable"}


def test_missing_evidence_is_not_a_green_gate():
    report = build_readiness_report(as_of=DAY, continuity={}, panel={}, nav_evidence={})
    assert all(g["status"] == "blocked" for g in report["gates"].values())


def memory():
    return {"id": "m-1", "arm_id": "desk", "status": "validated", "memory_type": "lesson",
            "created_at": "2026-09-15T10:00:00+08:00", "updated_at": "2026-09-15T12:00:00+08:00",
            "outcome_available_at": "2026-09-15T15:00:00+08:00"}


@pytest.mark.parametrize("change,reason", [
    ({"arm_id": "raw"}, "cross_arm_or_unscoped"),
    ({"status": "pending"}, "not_validated"),
    ({"updated_at": "2026-09-17T00:00:00+08:00"}, "updated_at_unknown_or_future"),
    ({"outcome_available_at": None}, "outcome_available_at_unknown_or_future"),
    ({"created_at": "2026-09-15T00:00:00"}, "created_at_unknown_or_future"),
    ({"expires_at": "2026-09-16T00:00:00+08:00"}, "expired_or_unknown_expiry"),
])
def test_evaluation_memory_excludes_leakage(change, reason):
    item = memory()
    item.update(change)
    result = select_evaluation_memory([item], arm_id="desk", cutoff=datetime.fromisoformat(DAY + "T00:00:00+08:00"))
    assert not result["accepted"]
    assert reason in result["excluded"][0]["reasons"]


def test_memory_valid_at_cutoff_is_kept_without_mutating_input():
    item = memory()
    before = deepcopy(item)
    result = select_evaluation_memory([item], arm_id="desk", cutoff=datetime.fromisoformat(DAY + "T00:00:00+08:00"))
    assert result["accepted"] == [item]
    assert not result["excluded"]
    assert item == before


def test_naive_cutoff_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        select_evaluation_memory([], arm_id="raw", cutoff=datetime(2026, 9, 16))
