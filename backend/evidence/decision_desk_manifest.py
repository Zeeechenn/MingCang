"""Complete offline protocol binding for the existing bounded session controller.

Declarations and byte integrity only: no provider identity, PIT truth, operating
system permissions, or return claims are inferred from a matching hash.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_manifest(manifest: dict, plan: dict) -> dict:
    """Normalize a two-arm, no-tools, frozen-input research protocol."""
    required = {"schema_version", "registration_ref", "hypothesis", "primary_metric", "benchmark_hash",
                "data_snapshot_hash", "provider_version_hash", "price_basis", "risk_hash", "execution_hash", "failure_policy", "arms"}
    if isinstance(manifest, dict) and manifest.get("schema_version") == "decision_desk_manifest.v2":
        required.add("evaluation")
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("manifest fields incomplete or unknown")
    value = json.loads(json.dumps(manifest, allow_nan=False))
    if value["schema_version"] not in {"decision_desk_manifest.v1", "decision_desk_manifest.v2"}:
        raise ValueError("manifest version invalid")
    for field in ("registration_ref", "hypothesis", "primary_metric"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"manifest {field} required")
    for field in ("benchmark_hash", "data_snapshot_hash", "provider_version_hash", "risk_hash", "execution_hash"):
        if not _hash(value[field]):
            raise ValueError(f"manifest {field} invalid")
    if value["data_snapshot_hash"] != plan["shared_input_hash"]:
        raise ValueError("manifest shared input mismatch")
    if any(value[key] != plan[key] for key in ("risk_hash", "execution_hash")):
        raise ValueError("manifest policy mismatch")
    if value["price_basis"] not in {"unadjusted_authoritative", "qfq_proxy", "mixed_or_unknown"}:
        raise ValueError("manifest price basis invalid")
    failure = value["failure_policy"]
    if (not isinstance(failure, dict) or set(failure) != {"automatic_retries", "fallback", "retain_failures", "timeout_seconds"}
            or type(failure["automatic_retries"]) is not int or failure["automatic_retries"] != 0
            or failure["fallback"] is not False or failure["retain_failures"] is not True
            or type(failure["timeout_seconds"]) is not int or not 1 <= failure["timeout_seconds"] <= 300):
        raise ValueError("manifest requires no retries/fallback, retained failures and bounded timeout")
    arms = value["arms"]
    if not isinstance(arms, list) or len(arms) != 2 or not all(isinstance(arm, dict) for arm in arms):
        raise ValueError("manifest requires two arms")
    if [arm.get("arm_id") for arm in arms] != [arm["arm_id"] for arm in plan["arms"]]:
        raise ValueError("manifest arm identity mismatch")
    for arm, planned in zip(arms, plan["arms"], strict=True):
        fields = {"arm_id", "requested_model", "prompt_hash", "request_hash", "memory_hash", "tools", "memory_root", "output_root"}
        if set(arm) != fields or arm["requested_model"] != planned["requested_model"]:
            raise ValueError("manifest arm model or fields mismatch")
        if not all(_hash(arm[key]) for key in ("prompt_hash", "request_hash", "memory_hash")):
            raise ValueError("manifest arm byte hashes required")
        if arm["tools"] != []:
            raise ValueError("this manifest version requires no tools")
        if arm["memory_root"] != f"{arm['arm_id']}/memory" or arm["output_root"] != arm["arm_id"]:
            raise ValueError("manifest roots must stay separate per arm")
    if value["schema_version"] == "decision_desk_manifest.v2":
        if any(arm["arm_id"].casefold() == "research.events.json" for arm in arms):
            raise ValueError("reserved research metadata path")
        validate_evaluation_design(value["evaluation"])
    return value


def validate_evaluation_design(design: dict) -> None:
    """Validate declared forward-only nested splits; never certify calendar/PIT truth."""
    fields = {"family_id", "candidates", "selected_candidate_id", "trial_count", "registration_hash",
              "sessions", "label_horizon_sessions", "purge_sessions", "embargo_sessions",
              "outer_folds", "holdout_sessions", "holdout_sha256", "initial_lifecycle"}
    if not isinstance(design, dict) or set(design) != fields:
        raise ValueError("evaluation design fields incomplete or unknown")
    if not isinstance(design["family_id"], str) or not design["family_id"].strip():
        raise ValueError("candidate family required")
    if design["initial_lifecycle"] != "experimental":
        raise ValueError("research design must begin experimental")
    if not _hash(design["registration_hash"]) or not _hash(design["holdout_sha256"]):
        raise ValueError("registration and holdout hashes required")
    candidates = design["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("declared candidates required")
    ids = []
    for candidate in candidates:
        if (not isinstance(candidate, dict) or set(candidate) != {"candidate_id", "parameters_hash"}
                or not isinstance(candidate["candidate_id"], str) or not candidate["candidate_id"].strip()
                or not _hash(candidate["parameters_hash"])):
            raise ValueError("candidate identity and parameter hash required")
        ids.append(candidate["candidate_id"])
    if len(set(ids)) != len(ids) or design["selected_candidate_id"] not in ids:
        raise ValueError("selected candidate must be unique and declared")
    if type(design["trial_count"]) is not int or design["trial_count"] < len(ids):
        raise ValueError("trial count must cover the whole declared family")
    sessions = design["sessions"]
    if (not isinstance(sessions, list) or not sessions or not all(isinstance(day, str) for day in sessions)
            or sessions != sorted(set(sessions))):
        raise ValueError("sessions must be unique and ascending")
    try:
        if any(date.fromisoformat(day).isoformat() != day for day in sessions):
            raise ValueError("noncanonical session date")
    except ValueError as exc:
        raise ValueError("invalid session date") from exc
    for field in ("label_horizon_sessions", "purge_sessions", "embargo_sessions"):
        if type(design[field]) is not int or design[field] < 0:
            raise ValueError("session gaps must be nonnegative integers")
    horizon, purge, embargo = (design[key] for key in ("label_horizon_sessions", "purge_sessions", "embargo_sessions"))
    if horizon < 1 or purge < horizon:
        raise ValueError("purge must cover the label horizon")
    positions = {day: i for i, day in enumerate(sessions)}

    def indexes(days: Any) -> set[int]:
        if not isinstance(days, list) or not days or not all(isinstance(day, str) and day in positions for day in days):
            raise ValueError("fold sessions must come from declared calendar")
        if days != sorted(set(days)):
            raise ValueError("fold sessions must be unique and ascending")
        return {positions[day] for day in days}

    fold_ids: set[str] = set()

    def fold_sets(fold: Any, *, outer: bool) -> tuple[set[int], set[int]]:
        required = {"fold_id", "train_sessions", "test_sessions"} | ({"inner_folds"} if outer else set())
        if not isinstance(fold, dict) or set(fold) != required:
            raise ValueError("fold fields incomplete or unknown")
        name = fold["fold_id"]
        if not isinstance(name, str) or not name.strip() or name in fold_ids:
            raise ValueError("fold IDs must be unique")
        fold_ids.add(name)
        train, test = indexes(fold["train_sessions"]), indexes(fold["test_sessions"])
        if max(train) + purge >= min(test):
            raise ValueError("forward fold train/label horizon overlaps test or purge")
        return train, test

    def enforce_embargo(pairs: list[tuple[set[int], set[int]]]) -> None:
        for _, test in pairs:
            forbidden = set(range(max(test) + 1, max(test) + embargo + 1))
            if any(train & forbidden for train, _ in pairs):
                raise ValueError("training includes an embargoed session")

    folds = design["outer_folds"]
    if not isinstance(folds, list) or not folds:
        raise ValueError("nested outer folds required")
    pairs: list[tuple[set[int], set[int]]] = []
    used_test: set[int] = set()
    development: set[int] = set()
    for fold in folds:
        train, test = fold_sets(fold, outer=True)
        if used_test & test:
            raise ValueError("outer test sessions overlap")
        used_test |= test
        development |= train | test
        pairs.append((train, test))
        inner = fold["inner_folds"]
        if not isinstance(inner, list) or not inner:
            raise ValueError("each outer fold requires inner validation")
        inner_pairs = [fold_sets(item, outer=False) for item in inner]
        if any((a | b) - train for a, b in inner_pairs):
            raise ValueError("inner fold leaks outside outer training data")
        if sum(len(test) for _, test in inner_pairs) != len(set().union(*(test for _, test in inner_pairs))):
            raise ValueError("inner test sessions overlap")
        enforce_embargo(inner_pairs)
    enforce_embargo(pairs)
    holdout = indexes(design["holdout_sessions"])
    if max(development) + max(purge, embargo) >= min(holdout):
        raise ValueError("holdout must follow all development and exclusion windows")


def validate_manifest_request(manifest: dict, arm_id: str, request: bytes | None,
                              tool_observations: dict[str, bytes] | None) -> None:
    """Reject switched requests or extra tools before reserving a model call."""
    arm = next(item for item in manifest["arms"] if item["arm_id"] == arm_id)
    if not isinstance(request, bytes) or hashlib.sha256(request).hexdigest() != arm["request_hash"]:
        raise ValueError("manifest request bytes mismatch")
    try:
        data = json.loads(request)
        prompt = data["instructions"]
        memory = data["memory"]
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        memory_hash = hashlib.sha256(json.dumps(memory, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("manifest request requires instructions and memory") from exc
    if prompt_hash != arm["prompt_hash"] or memory_hash != arm["memory_hash"]:
        raise ValueError("manifest prompt or memory bytes mismatch")
    if memory != []:
        raise ValueError("manifest v1 requires initially empty memory; use a new protocol for memory ablation")
    if tool_observations:
        raise ValueError("manifest forbids tool observations")
