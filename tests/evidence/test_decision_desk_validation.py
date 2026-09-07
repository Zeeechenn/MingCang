from __future__ import annotations

import copy
import json

import pytest

from backend.evidence.decision_desk_validation import (
    BLOCKED,
    DIAGNOSTIC_ONLY,
    EVIDENCE_STRUCTURE_VALID,
    SMOKE_ONLY,
    canonical_sha256,
    main,
    validate_experiment_spec,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def complete_spec() -> dict:
    budgets = {
        "raw": {"max_model_calls": 3, "max_tool_calls": 10, "max_cost_cny": 100},
        "desk": {"max_model_calls": 3, "max_tool_calls": 10, "max_cost_cny": 100},
    }
    freeze = {
        "frozen_at": "2026-09-07T16:00:00+08:00",
        "information_cutoff": "2026-09-07T15:30:00+08:00",
        "inputs_hash": HASH_A,
        "policy_hash": HASH_B,
        "execution_hash": HASH_C,
        "baseline_hash": HASH_D,
        "budgets_hash": canonical_sha256(budgets),
        "price_basis": "unadjusted_authoritative",
        "planned_dates": ["2026-09-07", "2026-09-08", "2026-09-09"],
        "planned_dates_hash": canonical_sha256(["2026-09-07", "2026-09-08", "2026-09-09"]),
    }
    return {
        "schema_version": "decision_desk_experiment.v1",
        "problem": "same_model_raw_vs_desk",
        "first_decision_at": "2026-09-07T16:30:00+08:00",
        "freeze": freeze,
        "arms": [
            arm(
                arm_id="raw",
                workflow="raw",
                account_id="acct_raw",
                identity_root="identity_raw",
                state_root="state_raw",
                freeze=freeze,
                budget=budgets["raw"],
            ),
            arm(
                arm_id="desk",
                workflow="desk",
                account_id="acct_desk",
                identity_root="identity_desk",
                state_root="state_desk",
                freeze=freeze,
                budget=budgets["desk"],
            ),
        ],
        "coverage": {
            "min_valid_days": 2,
            "failed_days": 1,
            "days": [
                {"date": "2026-09-07", "status": "valid", "observation_hash": HASH_A},
                {"date": "2026-09-08", "status": "failed", "failure_reason": "model_timeout", "observation_hash": HASH_B},
                {"date": "2026-09-09", "status": "valid", "observation_hash": HASH_C},
            ],
        },
    }


def arm(
    *,
    arm_id: str,
    workflow: str,
    account_id: str,
    identity_root: str,
    state_root: str,
    freeze: dict,
    budget: dict,
    requested_model: str = "gpt-6",
    resolved_model: str = "gpt-6",
) -> dict:
    return {
        "arm_id": arm_id,
        "workflow": workflow,
        "workflow_version": workflow,
        "prompt_hash": HASH_E,
        "tool_contract_hash": HASH_F,
        "decision_policy_hash": HASH_C,
        "account_id": account_id,
        "identity_root": identity_root,
        "state_root": state_root,
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "model_receipt": {
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "request_receipt_hash": HASH_C,
            "response_receipt_hash": HASH_D,
        },
        "inputs_hash": freeze["inputs_hash"],
        "policy_hash": freeze["policy_hash"],
        "execution_hash": freeze["execution_hash"],
        "budget_hash": freeze["budgets_hash"],
        "visible_input_hashes": [{"date": "2026-09-07", "sha256": HASH_A}],
        "tool_return_hashes": [{"date": "2026-09-07", "sha256": HASH_B}],
        "budget": budget,
        "actual_usage": {"max_model_calls": 2, "max_tool_calls": 8, "max_cost_cny": 88},
    }


def test_complete_raw_vs_desk_spec_is_evidence_structure_valid() -> None:
    result = validate_experiment_spec(complete_spec())

    assert result["status"] == "passed"
    assert result["capability"] == EVIDENCE_STRUCTURE_VALID
    assert result["certifies_returns"] is False
    assert result["errors"] == []
    assert result["trust_boundary"] == {
        "pure_offline_validator": True,
        "os_isolation_proven": False,
        "production_db_read": False,
        "model_api_called": False,
        "scheduler_or_ui_changed": False,
    }


def test_arm_budgets_must_match_even_when_hash_is_recomputed() -> None:
    spec = complete_spec()
    spec["arms"][1]["budget"]["max_model_calls"] = 4
    digest = canonical_sha256({item["arm_id"]: item["budget"] for item in spec["arms"]})
    spec["freeze"]["budgets_hash"] = digest
    for item in spec["arms"]:
        item["budget_hash"] = digest
    result = validate_experiment_spec(spec)
    assert "matched_experiment_requires_equal_arm_budgets" in result["errors"]


def test_same_desk_model_comparison_accepts_distinct_models_with_same_desk_workflow() -> None:
    spec = complete_spec()
    spec["problem"] = "same_desk_model_comparison"
    spec["arms"][0].update(
        {
            "workflow": "desk",
            "workflow_version": "desk",
            "requested_model": "claude-sonnet-4",
            "resolved_model": "claude-sonnet-4",
            "model_receipt": {
                "requested_model": "claude-sonnet-4",
                "resolved_model": "claude-sonnet-4",
                "request_receipt_hash": HASH_C,
                "response_receipt_hash": HASH_D,
            },
        }
    )

    result = validate_experiment_spec(spec)

    assert result["status"] == "passed"
    assert result["capability"] == EVIDENCE_STRUCTURE_VALID


def test_same_model_workflow_improvement_requires_one_workflow_version_change() -> None:
    spec = complete_spec()
    spec["problem"] = "same_model_workflow_improvement"
    spec["arms"][0]["workflow"] = "desk"
    spec["arms"][0]["workflow_version"] = "desk_v1"
    spec["arms"][1]["workflow"] = "desk"
    spec["arms"][1]["workflow_version"] = "desk_v2"
    spec["changed_component"] = "prompt_hash"
    spec["arms"][1]["prompt_hash"] = HASH_A

    result = validate_experiment_spec(spec)

    assert result["status"] == "passed"
    assert result["capability"] == EVIDENCE_STRUCTURE_VALID


def test_workflow_improvement_cannot_change_two_components() -> None:
    spec = complete_spec()
    spec["problem"] = "same_model_workflow_improvement"
    spec["changed_component"] = "prompt_hash"
    spec["arms"][1].update({"prompt_hash": HASH_A, "tool_contract_hash": HASH_B})
    result = validate_experiment_spec(spec)
    assert "workflow_improvement_requires_one_declared_component_change" in result["errors"]


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda spec: spec["freeze"].update({"information_cutoff": "2026-09-07T17:00:00+08:00"}),
            "information_cutoff_must_precede_first_decision",
        ),
        (
            lambda spec: spec["freeze"].update({"frozen_at": "2026-09-07T17:00:00+08:00"}),
            "freeze_must_precede_first_decision",
        ),
        (
            lambda spec: spec["arms"][1].update({"account_id": spec["arms"][0]["account_id"]}),
            "arms_require_separate_accounts",
        ),
        (
            lambda spec: spec["arms"][1].update({"arm_id": spec["arms"][0]["arm_id"]}),
            "arms_require_unique_arm_ids",
        ),
        (
            lambda spec: spec["arms"][1].update({"policy_hash": HASH_F}),
            "desk.risk_policy_mismatch",
        ),
        (
            lambda spec: spec["arms"][0].update({"inputs_hash": HASH_F}),
            "raw.inputs_hash_mismatch",
        ),
        (
            lambda spec: spec["arms"][0].update({"visible_input_hashes": []}),
            "raw.visible_input_hashes_required",
        ),
        (
            lambda spec: spec["arms"][1]["actual_usage"].update({"max_cost_cny": 101}),
            "desk.max_cost_cny_exceeded",
        ),
        (
            lambda spec: spec["coverage"].update({"failed_days": 0}),
            "coverage.failed_days_must_match_preserved_failed_records",
        ),
        (
            lambda spec: spec["coverage"]["days"].pop(1),
            "coverage.dates_must_match_frozen_planned_dates",
        ),
        (
            lambda spec: spec["coverage"]["days"].append(spec["coverage"]["days"][0].copy()),
            "coverage.dates_must_be_unique",
        ),
    ],
)
def test_negative_controls_block_evidence_structure(mutate, expected_error: str) -> None:
    spec = complete_spec()
    mutate(spec)

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert result["capability"] == BLOCKED
    assert expected_error in result["errors"]
    assert result["certifies_returns"] is False


def test_non_dict_spec_returns_blocked_instead_of_crashing() -> None:
    result = validate_experiment_spec(["bad"])

    assert result["status"] == BLOCKED
    assert result["errors"] == ["spec_must_be_object"]


def test_unhashable_identity_returns_blocked_instead_of_crashing() -> None:
    spec = complete_spec()
    spec["arms"][0]["identity_root"] = ["not", "scalar"]

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert "arms_require_independent_identity_roots" in result["errors"]


def test_model_fallback_downgrades_to_diagnostic_without_claiming_return_certification() -> None:
    spec = complete_spec()
    spec["arms"][0]["resolved_model"] = "gpt-5"
    spec["arms"][0]["model_receipt"]["resolved_model"] = "gpt-5"

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert "same_model_raw_vs_desk_requires_same_resolved_model" in result["errors"]


def test_model_fallback_in_model_comparison_is_diagnostic_only() -> None:
    spec = complete_spec()
    spec["problem"] = "same_desk_model_comparison"
    spec["arms"][0].update(
        {
            "workflow": "desk",
            "workflow_version": "desk",
            "requested_model": "gpt-6",
            "resolved_model": "gpt-5",
            "model_receipt": {
                "requested_model": "gpt-6",
                "resolved_model": "gpt-5",
                "request_receipt_hash": HASH_C,
                "response_receipt_hash": HASH_D,
            },
        }
    )

    result = validate_experiment_spec(spec)

    assert result["status"] == "passed"
    assert result["capability"] == DIAGNOSTIC_ONLY
    assert "raw.model_fallback_or_alias_diagnostic_only" in result["warnings"]
    assert result["certifies_returns"] is False


def test_model_strings_are_not_valid_without_exact_receipt_hashes() -> None:
    spec = complete_spec()
    spec["arms"][0]["model_receipt"].pop("request_receipt_hash")

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert "raw.model_receipt.request_receipt_hash_required" in result["errors"]
    assert result["certifies_returns"] is False


def test_unrecognized_model_with_complete_receipt_is_smoke_only() -> None:
    spec = complete_spec()
    spec["problem"] = "same_desk_model_comparison"
    spec["arms"][0].update(
        {
            "workflow": "desk",
            "workflow_version": "desk",
            "requested_model": "future-model",
            "resolved_model": "future-model",
            "model_receipt": {
                "requested_model": "future-model",
                "resolved_model": "future-model",
                "request_receipt_hash": HASH_C,
                "response_receipt_hash": HASH_D,
            },
        }
    )

    result = validate_experiment_spec(spec)

    assert result["status"] == "passed"
    assert result["capability"] == SMOKE_ONLY
    assert "raw.unrecognized_model_identifier_smoke_only" in result["warnings"]


def test_qfq_proxy_price_basis_is_diagnostic_only() -> None:
    spec = complete_spec()
    spec["freeze"]["price_basis"] = "qfq_proxy"

    result = validate_experiment_spec(spec)

    assert result["status"] == "passed"
    assert result["capability"] == DIAGNOSTIC_ONLY
    assert "qfq_proxy_price_basis_diagnostic_only" in result["warnings"]
    assert result["certifies_returns"] is False


@pytest.mark.parametrize("bad_number", [float("nan"), float("inf"), -1, True, "nan"])
def test_budget_numbers_reject_nan_inf_negative_and_bool(bad_number) -> None:
    spec = complete_spec()
    spec["arms"][0]["budget"]["max_model_calls"] = bad_number
    spec["freeze"]["budgets_hash"] = canonical_sha256(
        {"raw": spec["arms"][0]["budget"], "desk": spec["arms"][1]["budget"]}
    )
    for item in spec["arms"]:
        item["budget_hash"] = spec["freeze"]["budgets_hash"]

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert "raw.max_model_calls_must_be_finite_nonnegative_number" in result["errors"]


def test_budget_hash_must_match_budget_content() -> None:
    spec = complete_spec()
    spec["arms"][0]["budget"]["max_tool_calls"] = 11

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert "freeze.budgets_hash_must_match_arm_budgets" in result["errors"]


def test_cli_reads_explicit_json_path_and_outputs_report_json(tmp_path, capsys) -> None:
    spec_path = tmp_path / "decision_desk_spec.json"
    spec_path.write_text(json.dumps(complete_spec()), encoding="utf-8")

    exit_code = main([str(spec_path)])

    captured = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["schema_version"] == "decision_desk_validation.v1"
    assert captured["capability"] == EVIDENCE_STRUCTURE_VALID
    assert captured["certifies_returns"] is False


def test_self_attested_ready_true_is_rejected_and_ignored_by_signature() -> None:
    spec = complete_spec()
    without_ready = copy.deepcopy(spec)
    spec["ready"] = True

    result = validate_experiment_spec(spec)

    assert result["status"] == BLOCKED
    assert "self_attested_ready_true_is_not_evidence" in result["errors"]
    assert result["spec_signature"] == canonical_sha256(without_ready)
