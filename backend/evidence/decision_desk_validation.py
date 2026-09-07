"""Offline validation for decision-desk experiment evidence structure.

This module validates frozen experiment specifications and post-run receipts.
It does not read production state, call models, run execution accounting, or
certify returns. A passing result only means the supplied evidence structure is
internally consistent enough for the capability label returned in the report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, cast

SUPPORTED_PROBLEMS = frozenset(
    {
        "same_model_raw_vs_desk",
        "same_desk_model_comparison",
        "same_model_workflow_improvement",
    }
)
EVIDENCE_STRUCTURE_VALID = "evidence_structure_valid"
DIAGNOSTIC_ONLY = "diagnostic_only"
SMOKE_ONLY = "smoke_only"
BLOCKED = "blocked"

PRICE_BASIS_AUTHORITATIVE = "unadjusted_authoritative"
PRICE_BASIS_QFQ_PROXY = "qfq_proxy"
RECOGNIZED_MODEL_PREFIXES = ("claude-", "gpt-")
VERIFIED_BY_DECLARED_HASH_ONLY = (
    "declared_hash_only_not_recomputed_by_offline_validator"
)


def canonical_json(value: Any) -> str:
    """Serialize a JSON-like payload in a stable form for signatures."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def canonical_sha256(value: Any) -> str:
    """Return a full SHA-256 digest for a canonical JSON-like payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_experiment_spec(spec: Any) -> dict[str, Any]:
    """Validate a frozen decision-desk experiment spec and actual receipts."""
    validator = _Validator(spec)
    validator.run()
    return validator.report()


def verify_observation_artifacts(spec: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    """Check retained observation bytes, without claiming a model saw them.

    ``artifacts`` maps SHA-256 to relative files beneath an explicit evidence
    root. This is a read-only integrity check, not a recorder or a second ledger.
    """
    required: set[str] = set()
    arms = spec.get("arms", [])
    for arm in arms if isinstance(arms, list) else []:
        if not isinstance(arm, dict):
            continue
        for key in ("visible_input_hashes", "tool_return_hashes"):
            for entry in arm.get(key, []) if isinstance(arm.get(key), list) else []:
                digest = entry.get("sha256") if isinstance(entry, dict) else entry
                if _is_sha256(digest):
                    required.add(str(digest).lower())
        receipt = _dict_or_empty(arm.get("model_receipt"))
        for key in ("request_receipt_hash", "response_receipt_hash"):
            if _is_sha256(receipt.get(key)):
                required.add(receipt[key].lower())
    days = _dict_or_empty(spec.get("coverage")).get("days", [])
    for day in days if isinstance(days, list) else []:
        if isinstance(day, dict) and _is_sha256(day.get("observation_hash")):
            required.add(day["observation_hash"].lower())
    index = _dict_or_empty(spec.get("artifacts"))
    root = artifact_root.resolve()
    errors: list[str] = []
    verified = 0
    if not required:
        errors.append("no_observation_hashes_to_verify")
    for digest in sorted(required):
        relative = index.get(digest)
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            errors.append(f"{digest}.relative_artifact_path_required")
            continue
        try:
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                errors.append(f"{digest}.artifact_outside_root_or_not_file")
                continue
            actual = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    actual.update(block)
            if actual.hexdigest() != digest:
                errors.append(f"{digest}.artifact_bytes_mismatch")
            else:
                verified += 1
        except (OSError, RuntimeError):
            errors.append(f"{digest}.artifact_unreadable")
    return {"status": BLOCKED if errors else "passed", "verified_files": verified,
            "required_files": len(required), "errors": errors,
            "proves_model_observed_bytes": False, "certifies_returns": False}


class _Validator:
    def __init__(self, spec: Any) -> None:
        self.input_is_dict = isinstance(spec, dict)
        self.spec: dict[str, Any] = cast("dict[str, Any]", spec) if isinstance(spec, dict) else {}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.capability = EVIDENCE_STRUCTURE_VALID

    def run(self) -> None:
        if not self.input_is_dict:
            self._error("spec_must_be_object")
            return

        if self.spec.get("ready") is True:
            self._error("self_attested_ready_true_is_not_evidence")

        problem = str(self.spec.get("problem") or "")
        if problem not in SUPPORTED_PROBLEMS:
            self._error("unsupported_problem")
        arms = self.spec.get("arms")
        if not isinstance(arms, list) or len(arms) != 2:
            self._error("exactly_two_arms_required")
            arms = []

        freeze = _dict_or_empty(self.spec.get("freeze"))
        first_decision_at = _parse_aware_time(self.spec.get("first_decision_at"))
        freeze_at = _parse_aware_time(freeze.get("frozen_at"))
        cutoff_at = _parse_aware_time(freeze.get("information_cutoff"))
        if freeze_at is None:
            self._error("freeze.frozen_at_timezone_aware_required")
        if cutoff_at is None:
            self._error("freeze.information_cutoff_timezone_aware_required")
        if first_decision_at is None:
            self._error("first_decision_at_timezone_aware_required")
        if freeze_at and first_decision_at and freeze_at >= first_decision_at:
            self._error("freeze_must_precede_first_decision")
        if cutoff_at and first_decision_at and cutoff_at >= first_decision_at:
            self._error("information_cutoff_must_precede_first_decision")

        self._validate_frozen_contract(freeze, arms)
        self._validate_arms(problem, arms, freeze)
        self._validate_days()

    def report(self) -> dict[str, Any]:
        if self.errors:
            status = BLOCKED
            capability = BLOCKED
        else:
            status = "passed"
            capability = self.capability
        return {
            "schema_version": "decision_desk_validation.v1",
            "status": status,
            "capability": capability,
            "certifies_returns": False,
            "errors": self.errors,
            "warnings": self.warnings,
            "unverified_declared_hash_fields": ["policy_hash", "execution_hash", "baseline_hash"],
            "observation_bytes_verified": False,
            "trust_boundary": {
                "pure_offline_validator": True,
                "os_isolation_proven": False,
                "production_db_read": False,
                "model_api_called": False,
                "scheduler_or_ui_changed": False,
            },
            "spec_signature": canonical_sha256(_without_self_attested_readiness(self.spec)),
        }

    def _validate_frozen_contract(self, freeze: dict[str, Any], arms: Any) -> None:
        for key in ("inputs_hash", "policy_hash", "execution_hash", "baseline_hash", "budgets_hash"):
            if not _is_sha256(freeze.get(key)):
                self._error(f"freeze.{key}_required")
        self._warn(f"policy_hash.{VERIFIED_BY_DECLARED_HASH_ONLY}")
        self._warn(f"execution_hash.{VERIFIED_BY_DECLARED_HASH_ONLY}")
        self._warn(f"baseline_hash.{VERIFIED_BY_DECLARED_HASH_ONLY}")
        price_basis = str(freeze.get("price_basis") or "")
        if price_basis == PRICE_BASIS_QFQ_PROXY:
            self._warn("qfq_proxy_price_basis_diagnostic_only")
            self._downgrade(DIAGNOSTIC_ONLY)
        elif price_basis != PRICE_BASIS_AUTHORITATIVE:
            self._warn("unknown_price_basis_diagnostic_only")
            self._downgrade(DIAGNOSTIC_ONLY)
        planned_dates = freeze.get("planned_dates")
        planned_dates_for_hash: list[str] = []
        if not _is_string_list(planned_dates):
            self._error("freeze.planned_dates_required")
        else:
            planned_dates_for_hash = cast("list[str]", planned_dates)
            if len(set(planned_dates_for_hash)) != len(planned_dates_for_hash):
                self._error("freeze.planned_dates_must_be_unique")
        if freeze.get("planned_dates_hash") != canonical_sha256(planned_dates_for_hash):
            self._error("freeze.planned_dates_hash_must_match_planned_dates")
        if isinstance(arms, list):
            normalized = [arm for arm in arms if isinstance(arm, dict)]
            budgets_by_arm = {
                arm.get("arm_id"): arm.get("budget")
                for arm in normalized
                if isinstance(arm.get("arm_id"), str) and arm.get("arm_id")
            }
            if budgets_by_arm and freeze.get("budgets_hash") != canonical_sha256(budgets_by_arm):
                self._error("freeze.budgets_hash_must_match_arm_budgets")

    def _validate_arms(self, problem: str, arms: list[Any], freeze: dict[str, Any]) -> None:
        normalized = [arm for arm in arms if isinstance(arm, dict)]
        if len(normalized) != len(arms):
            self._error("each_arm_must_be_object")
        if len(normalized) != 2:
            return

        arm_ids = [arm.get("arm_id") for arm in normalized]
        identity_roots = [arm.get("identity_root") for arm in normalized]
        state_roots = [arm.get("state_root") for arm in normalized]
        account_ids = [arm.get("account_id") for arm in normalized]
        if not _has_two_unique_strings(arm_ids):
            self._error("arms_require_unique_arm_ids")
        if not _has_two_unique_strings(identity_roots):
            self._error("arms_require_independent_identity_roots")
        if not _has_two_unique_strings(state_roots):
            self._error("arms_require_independent_state_roots")
        if not _has_two_unique_strings(account_ids):
            self._error("arms_require_separate_accounts")

        inputs_hash = freeze.get("inputs_hash")
        risk_hash = freeze.get("policy_hash")
        execution_hash = freeze.get("execution_hash")
        budget_hash = freeze.get("budgets_hash")
        if normalized[0].get("budget") != normalized[1].get("budget"):
            self._error("matched_experiment_requires_equal_arm_budgets")
        for arm in normalized:
            arm_id = str(arm.get("arm_id") or "<missing>")
            for key in ("prompt_hash", "tool_contract_hash", "decision_policy_hash"):
                if not _is_sha256(arm.get(key)):
                    self._error(f"{arm_id}.{key}_required")
            if not _string_field(arm, "workflow_version"):
                self._error(f"{arm_id}.workflow_version_required")
            if arm.get("inputs_hash") != inputs_hash:
                self._error(f"{arm_id}.inputs_hash_mismatch")
            if arm.get("policy_hash") != risk_hash:
                self._error(f"{arm_id}.risk_policy_mismatch")
            if arm.get("execution_hash") != execution_hash:
                self._error(f"{arm_id}.execution_policy_mismatch")
            if arm.get("budget_hash") != budget_hash:
                self._error(f"{arm_id}.budget_policy_mismatch")
            self._validate_model_receipt(arm_id, arm)
            self._validate_hash_list(arm_id, "visible_input_hashes", arm.get("visible_input_hashes"))
            self._validate_hash_list(arm_id, "tool_return_hashes", arm.get("tool_return_hashes"))
            self._validate_budget_receipt(arm_id, arm)

        if problem == "same_model_raw_vs_desk":
            if _model_pair(normalized, "requested_model") and normalized[0]["requested_model"] != normalized[1]["requested_model"]:
                self._error("same_model_raw_vs_desk_requires_same_requested_model")
            if _model_pair(normalized, "resolved_model") and normalized[0]["resolved_model"] != normalized[1]["resolved_model"]:
                self._error("same_model_raw_vs_desk_requires_same_resolved_model")
            workflows = {_string_field(arm, "workflow") for arm in normalized}
            if workflows != {"raw", "desk"}:
                self._error("same_model_raw_vs_desk_requires_raw_and_desk_workflows")
        elif problem == "same_desk_model_comparison":
            if {_string_field(arm, "workflow") for arm in normalized} != {"desk"}:
                self._error("same_desk_model_comparison_requires_both_desk_workflow")
            if _model_pair(normalized, "resolved_model") and normalized[0]["resolved_model"] == normalized[1]["resolved_model"]:
                self._error("same_desk_model_comparison_requires_distinct_resolved_models")
            for key in ("workflow_version", "prompt_hash", "tool_contract_hash", "decision_policy_hash"):
                if normalized[0].get(key) != normalized[1].get(key):
                    self._error(f"same_desk_model_comparison.{key}_mismatch")
        elif problem == "same_model_workflow_improvement":
            if _model_pair(normalized, "resolved_model") and normalized[0]["resolved_model"] != normalized[1]["resolved_model"]:
                self._error("same_model_workflow_improvement_requires_same_resolved_model")
            if not _has_two_unique_strings([arm.get("workflow_version") for arm in normalized]):
                self._error("same_model_workflow_improvement_requires_one_workflow_version_change")
            changed = [key for key in ("prompt_hash", "tool_contract_hash", "decision_policy_hash")
                       if normalized[0].get(key) != normalized[1].get(key)]
            if len(changed) != 1 or changed[0] != self.spec.get("changed_component"):
                self._error("workflow_improvement_requires_one_declared_component_change")

    def _validate_model_receipt(self, arm_id: str, arm: dict[str, Any]) -> None:
        requested = str(arm.get("requested_model") or "")
        resolved = str(arm.get("resolved_model") or "")
        receipt = _dict_or_empty(arm.get("model_receipt"))
        if not requested or not resolved:
            self._error(f"{arm_id}.model_requested_and_resolved_required")
            return
        if receipt.get("requested_model") != requested or receipt.get("resolved_model") != resolved:
            self._error(f"{arm_id}.model_receipt_mismatch")
        for key in ("request_receipt_hash", "response_receipt_hash"):
            if not _is_sha256(receipt.get(key)):
                self._error(f"{arm_id}.model_receipt.{key}_required")
        if not _recognized_model_identifier(requested) or not _recognized_model_identifier(resolved):
            self._warn(f"{arm_id}.unrecognized_model_identifier_smoke_only")
            self._downgrade(SMOKE_ONLY)
        if requested != resolved:
            self._warn(f"{arm_id}.model_fallback_or_alias_diagnostic_only")
            self._downgrade(DIAGNOSTIC_ONLY)

    def _validate_hash_list(self, arm_id: str, key: str, value: Any) -> None:
        if not isinstance(value, list) or not value:
            self._error(f"{arm_id}.{key}_required")
            return
        for index, item in enumerate(value):
            digest = item.get("sha256") if isinstance(item, dict) else item
            if not _is_sha256(digest):
                self._error(f"{arm_id}.{key}.{index}.sha256_required")

    def _validate_budget_receipt(self, arm_id: str, arm: dict[str, Any]) -> None:
        budget = _dict_or_empty(arm.get("budget"))
        actual = _dict_or_empty(arm.get("actual_usage"))
        for key in ("max_model_calls", "max_tool_calls", "max_cost_cny"):
            if key not in budget or key not in actual:
                self._error(f"{arm_id}.{key}_budget_and_actual_required")
                continue
            budget_value = _finite_nonnegative_number(budget[key])
            actual_value = _finite_nonnegative_number(actual[key])
            if budget_value is None:
                self._error(f"{arm_id}.{key}_must_be_finite_nonnegative_number")
                continue
            if actual_value is None:
                self._error(f"{arm_id}.{key}_actual_must_be_finite_nonnegative_number")
                continue
            if actual_value > budget_value:
                self._error(f"{arm_id}.{key}_exceeded")

    def _validate_days(self) -> None:
        coverage = _dict_or_empty(self.spec.get("coverage"))
        min_valid_days = coverage.get("min_valid_days")
        days = coverage.get("days")
        freeze = _dict_or_empty(self.spec.get("freeze"))
        planned_dates = freeze.get("planned_dates")
        if not isinstance(days, list) or not days:
            self._error("coverage.days_required")
            return
        if isinstance(min_valid_days, bool) or not isinstance(min_valid_days, int) or min_valid_days <= 0:
            self._error("coverage.min_valid_days_positive_int_required")
            return
        valid_days = 0
        failed_days = 0
        dates: list[str] = []
        for index, day in enumerate(days):
            if not isinstance(day, dict):
                self._error(f"coverage.days.{index}_must_be_object")
                continue
            date = day.get("date")
            if not isinstance(date, str) or not date:
                self._error(f"coverage.days.{index}.date_required")
            else:
                dates.append(date)
            if not _is_sha256(day.get("observation_hash")):
                self._error(f"coverage.days.{index}.observation_hash_required")
            status = day.get("status")
            if status == "valid":
                valid_days += 1
            elif status == "failed":
                failed_days += 1
                if not day.get("failure_reason"):
                    self._error(f"coverage.days.{index}.failure_reason_required")
            else:
                self._error(f"coverage.days.{index}.status_must_be_valid_or_failed")
        declared_failed_days = coverage.get("failed_days")
        if declared_failed_days != failed_days:
            self._error("coverage.failed_days_must_match_preserved_failed_records")
        if len(set(dates)) != len(dates):
            self._error("coverage.dates_must_be_unique")
        if _is_string_list(planned_dates) and dates != planned_dates:
            self._error("coverage.dates_must_match_frozen_planned_dates")
        if valid_days < min_valid_days:
            self._error("coverage.valid_days_below_minimum")

    def _error(self, code: str) -> None:
        self.errors.append(code)

    def _warn(self, code: str) -> None:
        if code not in self.warnings:
            self.warnings.append(code)

    def _downgrade(self, capability: str) -> None:
        order = {EVIDENCE_STRUCTURE_VALID: 3, DIAGNOSTIC_ONLY: 2, SMOKE_ONLY: 1}
        if order[capability] < order[self.capability]:
            self.capability = capability


def _parse_aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _string_field(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    return item if isinstance(item, str) else ""


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _has_two_unique_strings(value: list[Any]) -> bool:
    return len(value) == 2 and all(isinstance(item, str) and item for item in value) and len(set(value)) == 2


def _finite_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _recognized_model_identifier(value: str) -> bool:
    return value.startswith(RECOGNIZED_MODEL_PREFIXES) and len(value) > 4


def _model_pair(arms: list[dict[str, Any]], key: str) -> bool:
    return all(isinstance(arm.get(key), str) and arm.get(key) for arm in arms)


def _without_self_attested_readiness(spec: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(spec)
    cleaned.pop("ready", None)
    return cleaned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate decision-desk experiment evidence JSON.")
    parser.add_argument("json_path", type=Path, help="Explicit path to an offline experiment JSON spec.")
    parser.add_argument("--artifacts-root", type=Path, help="Read-only verification of retained observation files.")
    args = parser.parse_args(argv)

    with args.json_path.open("r", encoding="utf-8") as handle:
        spec = json.load(handle)
    report = validate_experiment_spec(spec)
    if args.artifacts_root is not None and report["status"] != BLOCKED:
        artifact_check = verify_observation_artifacts(spec, args.artifacts_root)
        report["artifact_check"] = artifact_check
        report["observation_bytes_verified"] = artifact_check["status"] == "passed"
        if artifact_check["status"] == BLOCKED:
            report["status"] = BLOCKED
            report["capability"] = BLOCKED
            report["errors"].extend(artifact_check["errors"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == BLOCKED else 0


if __name__ == "__main__":
    raise SystemExit(main())
