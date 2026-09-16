"""Bounded offline session control for decision-desk recording attempts.

The session layer freezes a small budget-and-input plan, reserves one model
call under a local file lock, and delegates byte-level attempt recording to
``record_model_observation``. It is not a full research protocol certification,
trading ledger, execution engine, runner, scheduler, model client, or
third-party trusted timestamp service.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.evidence.decision_desk_manifest import validate_manifest, validate_manifest_request
from backend.evidence.decision_desk_recording import record_model_observation

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-Unix hosts
    fcntl = None  # type: ignore[assignment]


Provider = Callable[[bytes], dict[str, Any]]
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
REPO_ROOT = Path(__file__).resolve().parents[2]
DATE_WINDOW_TIMEZONE = "Asia/Shanghai"
RESERVED_ARM_IDS = frozenset({"budget", "budget.lock", "freeze.json"})
SUPPORTED_PROBLEMS = frozenset(
    {
        "same_model_raw_vs_desk",
        "same_desk_model_comparison",
        "same_model_workflow_improvement",
    }
)
PLAN_KEYS = frozenset(
    {
        "problem",
        "date_window",
        "shared_input_hash",
        "risk_hash",
        "execution_hash",
        "budget_policy",
        "arms",
    }
)
ARM_KEYS = frozenset({"arm_id", "account_id", "requested_model", "budget"})
BUDGET_KEYS = frozenset({"total_model_calls", "total_cost_cny", "max_attempt_cost_cny"})
HASH_FIELDS = ("shared_input_hash", "risk_hash", "execution_hash")


def freeze_plan(output_root: Path, experiment_id: str, plan: dict[str, Any], *, manifest: dict | None = None) -> dict[str, Any]:
    """Freeze an offline experiment plan once under an exclusive experiment directory."""
    root = _resolve_output_root(output_root)
    _validate_identifier(experiment_id)
    _validate_no_symlink(root)
    normalized = _validate_plan(plan)
    bound_manifest = validate_manifest(manifest, normalized) if manifest is not None else None
    experiment_dir = _child(root, experiment_id)
    experiment_dir.mkdir(parents=True, exist_ok=False)
    _fsync_dir(experiment_dir.parent)
    frozen_at = _now()
    plan_hash = _sha256_json(normalized)
    payload = {
        "schema_version": "decision_desk_session_freeze.v1",
        "status": "frozen",
        "experiment_id": experiment_id,
        "frozen_at": frozen_at.isoformat(),
        "machine_generated_frozen_at": True,
        "date_window_timezone": DATE_WINDOW_TIMEZONE,
        "plan_hash": plan_hash,
        "plan_hash_is_trusted_timestamp": False,
        "plan": normalized,
        "budget_policy": normalized["budget_policy"],
        "physical_attempt_root": "{output_root}/{experiment_id}/{arm_id}/{attempt_id}",
        "arms": [arm["arm_id"] for arm in normalized["arms"]],
        "claims": _claims(),
        "durability_boundary": "local_filesystem_fsync_not_disk_failure_proof",
    }
    if bound_manifest is not None:
        payload["manifest"] = bound_manifest
        payload["manifest_hash"] = _sha256_json(bound_manifest)
    payload["freeze_signature"] = _freeze_signature(payload)
    _write_json_atomic(_child(experiment_dir, "freeze.json"), payload)
    return payload


def run_frozen_attempt(
    *,
    output_root: Path,
    experiment_id: str,
    arm_id: str,
    attempt_id: str,
    cutoff: datetime,
    provider: Provider,
    request_bytes: bytes | None = None,
    request_payload: dict[str, Any] | None = None,
    tool_observations: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Run one frozen offline attempt after reserving one model call."""
    root = _resolve_output_root(output_root)
    _validate_identifier(experiment_id)
    _validate_identifier(arm_id)
    _validate_identifier(attempt_id)
    if not _is_aware(cutoff):
        raise ValueError("cutoff must be timezone-aware")
    if cutoff > _now().astimezone(cutoff.tzinfo):
        raise ValueError("cutoff cannot be in the future")

    experiment_dir = _existing_child(root, experiment_id)
    freeze = _load_and_verify_freeze(experiment_dir)
    arm = _arm_by_id(freeze["plan"], arm_id)
    _validate_cutoff_window(cutoff, freeze["plan"]["date_window"])
    attempt_dir = _child(experiment_dir, arm_id, attempt_id)
    if attempt_dir.exists():
        raise FileExistsError(f"attempt already exists: {attempt_dir}")

    if freeze.get("manifest") is not None:
        if request_payload is not None:
            raise ValueError("manifest attempts require exact request_bytes")
        validate_manifest_request(freeze["manifest"], arm_id, request_bytes, tool_observations)

    reservation = _reserve_budget(
        experiment_dir=experiment_dir,
        arm_id=arm_id,
        attempt_id=attempt_id,
        arm_budget=arm["budget"],
    )

    receipt = record_model_observation(
        output_root=root,
        experiment_id=experiment_id,
        arm_id=arm_id,
        attempt_id=attempt_id,
        requested_model=arm["requested_model"],
        cutoff=cutoff,
        request_bytes=request_bytes,
        request_payload=request_payload,
        provider=provider,
        budget={"max_model_calls": 1, "max_cost_cny": arm["budget"]["max_attempt_cost_cny"]},
        tool_observations=tool_observations,
    )
    receipt["session"] = {
        "plan_hash": freeze["plan_hash"],
        "freeze_signature": freeze["freeze_signature"],
        "account_id": arm["account_id"],
    }
    if freeze.get("manifest_hash"):
        receipt["session"]["manifest_hash"] = freeze["manifest_hash"]
    receipt["reservation"] = reservation
    receipt["claims"] = {**receipt["claims"], **_claims()}
    _write_json_atomic(_child(attempt_dir, "receipt.json"), receipt)
    return receipt


def inspect_session(output_root: Path, experiment_id: str) -> dict[str, Any]:
    """Summarize frozen plan, reservations, and receipts without creating a ledger."""
    root = _resolve_output_root(output_root)
    _validate_identifier(experiment_id)
    experiment_dir = _existing_child(root, experiment_id)
    freeze = _load_and_verify_freeze(experiment_dir)
    arms: dict[str, Any] = {}
    for arm in freeze["plan"]["arms"]:
        arm_id = arm["arm_id"]
        expected_attempt_cost = _decimal_from_number(arm["budget"]["max_attempt_cost_cny"])
        if expected_attempt_cost is None:
            raise RuntimeError("invalid frozen budget")
        reservations = _read_reservations(
            experiment_dir,
            arm_id,
            expected_attempt_cost=expected_attempt_cost,
        )
        receipt_counts = _receipt_counts_for_reservations(experiment_dir, arm_id, reservations)
        arms[arm_id] = {
            "account_id": arm["account_id"],
            "physical_attempt_root": f"{experiment_id}/{arm_id}/{{attempt_id}}",
            "requested_model": arm["requested_model"],
            "budget": arm["budget"],
            "budget_policy": freeze["plan"]["budget_policy"],
            "budget_comparability_claim": freeze["plan"]["budget_policy"] == "matched",
            "reserved_model_calls": sum(item["reserved"]["model_calls"] for item in reservations),
            "reserved_cost_cny": float(sum(item["reserved"]["cost_cny"] for item in reservations)),
            "reservation_files": [item["path"] for item in reservations],
            "receipts": receipt_counts,
        }
    result = {
        "schema_version": "decision_desk_session_inspection.v1",
        "experiment_id": experiment_id,
        "freeze": {
            "frozen_at": freeze["frozen_at"],
            "machine_generated_frozen_at": freeze["machine_generated_frozen_at"],
            "plan_hash": freeze["plan_hash"],
            "plan_hash_verified": True,
            "freeze_signature_verified": True,
            "plan_hash_is_trusted_timestamp": False,
        },
        "arms": arms,
        "claims": _claims(),
    }
    if (freeze.get("manifest") or {}).get("schema_version") == "decision_desk_manifest.v2":
        result["research"] = _research_state(experiment_dir, freeze)[0]
    return result


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dict")
    if "frozen_at" in plan:
        raise ValueError("frozen_at is machine generated")
    unknown = set(plan) - PLAN_KEYS
    if unknown:
        raise ValueError(f"unknown plan fields: {sorted(unknown)}")
    problem = plan.get("problem")
    if not isinstance(problem, str) or problem not in SUPPORTED_PROBLEMS:
        raise ValueError("plan problem invalid")
    for field in HASH_FIELDS:
        if not _is_sha256(plan.get(field)):
            raise ValueError(f"plan {field} invalid")
    date_window = plan.get("date_window")
    if not isinstance(date_window, dict) or set(date_window) != {"start", "end"}:
        raise ValueError("plan date_window invalid")
    start = _parse_date(date_window.get("start"))
    end = _parse_date(date_window.get("end"))
    if start is None or end is None or end < start:
        raise ValueError("plan date_window invalid")
    budget_policy = plan.get("budget_policy")
    if not isinstance(budget_policy, str) or budget_policy not in {"matched", "declared_per_arm"}:
        raise ValueError("plan budget_policy invalid")
    arms = plan.get("arms")
    if not isinstance(arms, list) or len(arms) != 2:
        raise ValueError("plan requires exactly two arms")

    normalized_arms = [_validate_arm(item) for item in arms]
    arm_ids = [item["arm_id"].casefold() for item in normalized_arms]
    if RESERVED_ARM_IDS.intersection(arm_ids):
        raise ValueError("arm_id conflicts with session control paths")
    account_ids = [item["account_id"].casefold() for item in normalized_arms]
    if len(set(arm_ids)) != 2:
        raise ValueError("arm_id values must be unique")
    if len(set(account_ids)) != 2:
        raise ValueError("account_id values must be unique")
    same_model = normalized_arms[0]["requested_model"] == normalized_arms[1]["requested_model"]
    if problem.startswith("same_model_") and not same_model:
        raise ValueError("same-model problem requires equal requested models")
    if problem == "same_desk_model_comparison" and same_model:
        raise ValueError("model comparison requires distinct requested models")
    if budget_policy == "matched" and normalized_arms[0]["budget"] != normalized_arms[1]["budget"]:
        raise ValueError("matched budget_policy requires equal arm budgets")

    return {
        "problem": problem,
        "date_window": {"start": date_window["start"], "end": date_window["end"]},
        "shared_input_hash": plan["shared_input_hash"],
        "risk_hash": plan["risk_hash"],
        "execution_hash": plan["execution_hash"],
        "budget_policy": budget_policy,
        "arms": normalized_arms,
    }


def _validate_arm(arm: Any) -> dict[str, Any]:
    if not isinstance(arm, dict):
        raise ValueError("arm must be a dict")
    unknown = set(arm) - ARM_KEYS
    if unknown:
        raise ValueError(f"unknown arm fields: {sorted(unknown)}")
    for field in ("arm_id", "account_id"):
        _validate_identifier(arm.get(field))
    requested_model = arm.get("requested_model")
    if not isinstance(requested_model, str) or not requested_model.strip():
        raise ValueError("arm requested_model invalid")
    budget = arm.get("budget")
    if not isinstance(budget, dict) or set(budget) != BUDGET_KEYS:
        raise ValueError("arm budget invalid")
    total_model_calls = budget.get("total_model_calls")
    total_cost_cny = _decimal_from_number(budget.get("total_cost_cny"))
    max_attempt_cost_cny = _decimal_from_number(budget.get("max_attempt_cost_cny"))
    if (
        isinstance(total_model_calls, bool)
        or not isinstance(total_model_calls, int)
        or total_model_calls <= 0
        or total_cost_cny is None
        or total_cost_cny <= 0
        or max_attempt_cost_cny is None
        or max_attempt_cost_cny <= 0
        or max_attempt_cost_cny > total_cost_cny
    ):
        raise ValueError("arm budget invalid")
    return {
        "arm_id": arm["arm_id"],
        "account_id": arm["account_id"],
        "requested_model": requested_model,
        "budget": {
            "total_model_calls": total_model_calls,
            "total_cost_cny": float(total_cost_cny),
            "max_attempt_cost_cny": float(max_attempt_cost_cny),
        },
    }


def _reserve_budget(
    *,
    experiment_dir: Path,
    arm_id: str,
    attempt_id: str,
    arm_budget: dict[str, Any],
) -> dict[str, Any]:
    lock_path = _child(experiment_dir, "budget.lock")
    lock_path.touch(exist_ok=True)
    _fsync_dir(experiment_dir)
    with _exclusive_lock(lock_path):
        expected_cost = _decimal_from_number(arm_budget["max_attempt_cost_cny"])
        if expected_cost is None:
            raise RuntimeError("invalid frozen budget")
        # A known overrun or corrupt record in either arm blocks new calls in
        # the whole experiment. Already in-flight providers cannot be cancelled here.
        freeze = _load_and_verify_freeze(experiment_dir)
        if (freeze.get("manifest") or {}).get("schema_version") == "decision_desk_manifest.v2":
            state, _ = _research_state(experiment_dir, freeze)
            if state["lifecycle"] not in {"experimental", "shadow"} or state["holdout_access_reserved"]:
                raise RuntimeError("research lifecycle or holdout access blocks new attempts")
        reservations: list[dict[str, Any]] = []
        for frozen_arm in freeze["plan"]["arms"]:
            other_id = frozen_arm["arm_id"]
            other_cost = _decimal_from_number(frozen_arm["budget"]["max_attempt_cost_cny"])
            if other_cost is None:
                raise RuntimeError("invalid frozen budget")
            prior = _read_reservations(experiment_dir, other_id, expected_attempt_cost=other_cost)
            _assert_attempt_dirs_have_reservations(experiment_dir, other_id, prior)
            _assert_prior_receipts_do_not_exceed_budget(experiment_dir, other_id, prior, other_cost)
            if other_id == arm_id:
                reservations = prior
        used_calls = sum(item["reserved"]["model_calls"] for item in reservations)
        used_cost = sum(item["reserved"]["cost_cny"] for item in reservations)
        reserve = {"model_calls": 1, "cost_cny": expected_cost}
        total_cost = _decimal_from_number(arm_budget["total_cost_cny"])
        if total_cost is None:
            raise RuntimeError("invalid frozen budget")
        if (
            used_calls + reserve["model_calls"] > arm_budget["total_model_calls"]
            or used_cost + reserve["cost_cny"] > total_cost
        ):
            raise RuntimeError("budget exhausted")
        reservation_dir = _child(_child(experiment_dir, "budget"), arm_id)
        reservation_dir.mkdir(parents=True, exist_ok=True)
        _reject_symlink_chain(reservation_dir, experiment_dir)
        reservation_path = _child(reservation_dir, f"{attempt_id}.reservation.json")
        payload = {
            "schema_version": "decision_desk_session_reservation.v1",
            "status": "reserved",
            "arm_id": arm_id,
            "attempt_id": attempt_id,
            "created_at": _now().isoformat(),
            "reserved": {"model_calls": 1, "cost_cny": float(expected_cost)},
            "source": "conservative_pre_call_reservation",
            "not_refunded_automatically": True,
            "durability_boundary": "local_filesystem_fsync_not_disk_failure_proof",
        }
        _write_json_exclusive(reservation_path, payload)
    return {
        "path": _relative(experiment_dir.parent, reservation_path),
        "budget_reserved": {"model_calls": 1, "cost_cny": float(expected_cost)},
        "source": "conservative_pre_call_reservation",
        "not_refunded_automatically": True,
    }


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    if fcntl is None:
        raise RuntimeError("Unix flock unavailable")
    _validate_no_symlink(path)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_and_verify_freeze(experiment_dir: Path) -> dict[str, Any]:
    _reject_symlink_chain(experiment_dir, experiment_dir.parent)
    freeze_path = _child(experiment_dir, "freeze.json")
    freeze = _read_json(freeze_path)
    if freeze.get("experiment_id") != experiment_dir.name:
        raise ValueError("freeze experiment identity mismatch")
    plan = freeze.get("plan")
    if not isinstance(plan, dict) or freeze.get("plan_hash") != _sha256_json(plan):
        raise ValueError("freeze hash mismatch")
    if freeze.get("freeze_signature") != _freeze_signature(freeze):
        raise ValueError("freeze hash mismatch")
    if freeze.get("manifest") is not None:
        manifest = validate_manifest(freeze["manifest"], plan)
        if freeze.get("manifest_hash") != _sha256_json(manifest):
            raise ValueError("manifest hash mismatch")
    frozen_at = _parse_aware_datetime(freeze.get("frozen_at"))
    if frozen_at is None or frozen_at > _now().astimezone(frozen_at.tzinfo):
        raise ValueError("freeze timestamp invalid")
    return freeze


def _arm_by_id(plan: dict[str, Any], arm_id: str) -> dict[str, Any]:
    arms = plan.get("arms")
    for arm in arms if isinstance(arms, list) else []:
        if isinstance(arm, dict) and arm.get("arm_id") == arm_id:
            return arm
    raise ValueError("unknown arm_id")


def _validate_cutoff_window(cutoff: datetime, date_window: dict[str, Any]) -> None:
    start = _parse_date(date_window.get("start"))
    end = _parse_date(date_window.get("end"))
    cutoff_date = cutoff.astimezone(ZoneInfo(DATE_WINDOW_TIMEZONE)).date()
    if start is None or end is None or cutoff_date < start or cutoff_date > end:
        raise ValueError("cutoff outside frozen date window")


def _read_reservations(
    experiment_dir: Path,
    arm_id: str,
    *,
    expected_attempt_cost: Decimal,
) -> list[dict[str, Any]]:
    reservation_dir = _child(_child(experiment_dir, "budget"), arm_id)
    if not reservation_dir.exists():
        return []
    _reject_symlink_chain(reservation_dir, experiment_dir)
    result: list[dict[str, Any]] = []
    for path in sorted(reservation_dir.glob("*.reservation.json")):
        _validate_no_symlink(path)
        item = _read_json(path)
        if item.get("arm_id") != arm_id:
            raise RuntimeError("reservation arm mismatch")
        attempt_id = item.get("attempt_id")
        _validate_identifier(attempt_id)
        if path.name != f"{attempt_id}.reservation.json":
            raise RuntimeError("reservation attempt filename mismatch")
        reserved = item.get("reserved")
        if not isinstance(reserved, dict):
            raise RuntimeError("reservation reserved payload invalid")
        calls = _decimal_from_number(reserved.get("model_calls"))
        cost = _decimal_from_number(reserved.get("cost_cny"))
        if calls != Decimal(1) or cost != expected_attempt_cost:
            raise RuntimeError("reservation budget payload invalid")
        result.append(
            {
                "path": _relative(experiment_dir.parent, path),
                "attempt_id": attempt_id,
                "reserved": {"model_calls": 1, "cost_cny": cost},
            }
        )
    return result


def _assert_attempt_dirs_have_reservations(
    experiment_dir: Path,
    arm_id: str,
    reservations: list[dict[str, Any]],
) -> None:
    arm_dir = _child(experiment_dir, arm_id)
    if not arm_dir.exists():
        return
    _reject_symlink_chain(arm_dir, experiment_dir)
    reserved_attempts = {item["attempt_id"] for item in reservations}
    for child in arm_dir.iterdir():
        if child.is_symlink():
            raise RuntimeError("attempt path symlink unsupported")
        if child.is_dir() and child.name not in reserved_attempts:
            raise RuntimeError("attempt missing reservation")


def _assert_prior_receipts_do_not_exceed_budget(
    experiment_dir: Path,
    arm_id: str,
    reservations: list[dict[str, Any]],
    expected_attempt_cost: Decimal,
) -> None:
    for reservation in reservations:
        receipt_path = _child(experiment_dir, arm_id, reservation["attempt_id"], "receipt.json")
        if not receipt_path.exists():
            continue
        receipt = _read_json(receipt_path)
        if (
            receipt.get("experiment_id") != experiment_dir.name
            or receipt.get("arm_id") != arm_id
            or receipt.get("attempt_id") != reservation["attempt_id"]
        ):
            raise RuntimeError("prior receipt identity mismatch")
        if "usage_exceeds_budget" in receipt.get("errors", []):
            raise RuntimeError("prior receipt usage exceeds budget")
        usage = receipt.get("usage")
        if usage is None:
            continue
        if not isinstance(usage, dict):
            raise RuntimeError("prior receipt usage invalid")
        model_calls = _decimal_from_number(usage.get("model_calls"))
        cost_cny = _decimal_from_number(usage.get("cost_cny"))
        if model_calls is None or cost_cny is None:
            raise RuntimeError("prior receipt usage invalid")
        if model_calls > 1 or cost_cny > expected_attempt_cost:
            raise RuntimeError("prior receipt usage exceeds budget")


def _receipt_counts_for_reservations(
    experiment_dir: Path,
    arm_id: str,
    reservations: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "missing": 0}
    for reservation in reservations:
        receipt_path = _child(experiment_dir, arm_id, reservation["attempt_id"], "receipt.json")
        if not receipt_path.exists():
            counts["missing"] += 1
            continue
        receipt = _read_json(receipt_path)
        status = receipt.get("status")
        if status == "passed":
            counts["passed"] += 1
        elif status == "failed":
            counts["failed"] += 1
        else:
            counts["missing"] += 1
    return counts


def _resolve_output_root(output_root: Path) -> Path:
    root = Path(output_root).expanduser().resolve()
    if root == REPO_ROOT or REPO_ROOT in root.parents:
        raise ValueError("output_root must be outside the repository")
    return root


def _child(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts)
    if path.is_symlink():
        raise RuntimeError("symlink paths are not supported")
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("path resolves outside output_root")
    for parent in [path, *path.parents]:
        if parent == root.parent:
            break
        if parent.exists() and parent.is_symlink():
            raise RuntimeError("symlink paths are not supported")
    return path


def _existing_child(root: Path, *parts: str) -> Path:
    path = _child(root, *parts)
    if not path.exists():
        raise FileNotFoundError(path)
    _reject_symlink_chain(path, root)
    return path


def _reject_symlink_chain(path: Path, root: Path) -> None:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            raise RuntimeError("symlink paths are not supported")
        if current == root:
            return
        if current == current.parent:
            return
        current = current.parent


def _validate_no_symlink(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise RuntimeError("symlink paths are not supported")


def _validate_identifier(value: Any) -> None:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError("invalid path identifier")
    if value in {".", ".."} or "/" in value or "\\" in value or Path(value).is_absolute():
        raise ValueError("invalid path identifier")


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _decimal_from_number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed_float = float(value)
    if not math.isfinite(parsed_float) or parsed_float < 0:
        return None
    return Decimal(str(value))


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _parse_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if _is_aware(parsed) else None


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _freeze_signature(payload: dict[str, Any]) -> str:
    signed = {key: value for key, value in payload.items() if key != "freeze_signature"}
    return _sha256_json(signed)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = _child(path.parent, f".{path.name}.tmp")
    with tmp.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    _fsync_dir(path.parent)


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_dir(path.parent)


def _read_json(path: Path) -> dict[str, Any]:
    _validate_no_symlink(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("json payload must be object")
    return payload


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _now() -> datetime:
    return datetime.now(UTC)


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _claims() -> dict[str, bool]:
    return {
        "budget_and_input_plan_only": True,
        "complete_research_protocol_certified": False,
        "complete_runner": False,
        "trading_ledger": False,
        "os_isolation_proven": False,
        "profitability_certified": False,
    }


_RESEARCH_TRANSITIONS = {
    "experimental": {"shadow", "dormant", "rejected", "archived"},
    "shadow": {"dormant", "rejected", "archived"},
    "dormant": {"experimental", "rejected", "archived"},
    "rejected": {"archived"},
    "archived": set(),
}


def _research_state(experiment_dir: Path, freeze: dict) -> tuple[dict, list[dict]]:
    if (freeze.get("manifest") or {}).get("schema_version") != "decision_desk_manifest.v2":
        raise ValueError("research lifecycle requires a v2 manifest")
    path = _child(experiment_dir, "budget", "research.events.json")
    payload = _read_json(path) if path.exists() else {"events": []}
    events = payload.get("events")
    if not isinstance(events, list):
        raise RuntimeError("research events corrupt")
    state: dict[str, Any] = {"lifecycle": "experimental", "holdout_access_reserved": False,
                              "holdout_result": None, "event_count": len(events)}
    previous = freeze["manifest_hash"]
    previous_at = _parse_aware_datetime(freeze["frozen_at"])
    for seq, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != {"seq", "kind", "at", "details", "previous_hash", "sha256"}:
            raise RuntimeError("research events corrupt")
        unsigned = {key: value for key, value in event.items() if key != "sha256"}
        if event["seq"] != seq or event["previous_hash"] != previous or event["sha256"] != _sha256_json(unsigned):
            raise RuntimeError("research event chain mismatch")
        at = _parse_aware_datetime(event["at"])
        if at is None or previous_at is None or not previous_at <= at <= _now():
            raise RuntimeError("research event timestamp invalid")
        previous_at = at
        details = event["details"]
        if not isinstance(details, dict):
            raise RuntimeError("research event details invalid")
        if event["kind"] == "lifecycle":
            target = details.get("to")
            if target not in _RESEARCH_TRANSITIONS[state["lifecycle"]] or not details.get("reason"):
                raise RuntimeError("research lifecycle transition invalid")
            state["lifecycle"] = target
        elif event["kind"] == "holdout_reserved":
            if state["holdout_access_reserved"] or details.get("sha256") != freeze["manifest"]["evaluation"]["holdout_sha256"]:
                raise RuntimeError("holdout reservation invalid")
            state["holdout_access_reserved"] = True
        elif event["kind"] == "holdout_result":
            if not state["holdout_access_reserved"] or state["holdout_result"] is not None or details.get("status") not in {"read", "hash_mismatch", "read_failed"}:
                raise RuntimeError("holdout result invalid")
            state["holdout_result"] = details["status"]
        else:
            raise RuntimeError("unknown research event")
        previous = event["sha256"]
    return state, events


def _append_research_event(experiment_dir: Path, freeze: dict, events: list[dict], kind: str, details: dict) -> None:
    event = {"seq": len(events), "kind": kind, "at": _now().isoformat(), "details": details,
             "previous_hash": events[-1]["sha256"] if events else freeze["manifest_hash"]}
    event["sha256"] = _sha256_json(event)
    directory = _child(experiment_dir, "budget")
    directory.mkdir(exist_ok=True)
    _write_json_atomic(_child(directory, "research.events.json"), {"events": [*events, event]})


def set_research_lifecycle(output_root: Path, experiment_id: str, *, lifecycle: str, reason: str) -> dict:
    """Record a manual research transition. Stable/production promotion is unavailable."""
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise ValueError("lifecycle reason required")
    root = _resolve_output_root(output_root)
    _validate_identifier(experiment_id)
    directory = _existing_child(root, experiment_id)
    lock = _child(directory, "budget.lock")
    lock.touch(exist_ok=True)
    with _exclusive_lock(lock):
        freeze = _load_and_verify_freeze(directory)
        state, events = _research_state(directory, freeze)
        if lifecycle not in _RESEARCH_TRANSITIONS[state["lifecycle"]]:
            raise ValueError("research lifecycle transition not allowed")
        _append_research_event(directory, freeze, events, "lifecycle", {"to": lifecycle, "reason": reason.strip()})
        return _research_state(directory, freeze)[0]


def read_frozen_holdout(output_root: Path, experiment_id: str, *, artifact: Path) -> bytes:
    """Reserve the only controlled holdout read before opening it; block further model attempts.

    Failed reads remain consumed. This cannot prevent reads outside this function
    and is not proof that a local operator had never seen the source artifact.
    """
    root = _resolve_output_root(output_root)
    _validate_identifier(experiment_id)
    directory = _existing_child(root, experiment_id)
    lock = _child(directory, "budget.lock")
    lock.touch(exist_ok=True)
    with _exclusive_lock(lock):
        freeze = _load_and_verify_freeze(directory)
        state, events = _research_state(directory, freeze)
        if state["lifecycle"] not in {"experimental", "shadow"} or state["holdout_access_reserved"]:
            raise RuntimeError("holdout access unavailable or already reserved")
        design = freeze["manifest"]["evaluation"]
        if design["holdout_sessions"][-1] >= _now().astimezone(ZoneInfo(DATE_WINDOW_TIMEZONE)).date().isoformat():
            raise RuntimeError("holdout sessions must have completed before today")
        for arm in freeze["plan"]["arms"]:
            cost = _decimal_from_number(arm["budget"]["max_attempt_cost_cny"])
            if cost is None:
                raise RuntimeError("invalid frozen budget")
            reservations = _read_reservations(directory, arm["arm_id"], expected_attempt_cost=cost)
            _assert_attempt_dirs_have_reservations(directory, arm["arm_id"], reservations)
            for reservation in reservations:
                receipt_path = _child(directory, arm["arm_id"], reservation["attempt_id"], "receipt.json")
                receipt = _read_json(receipt_path) if receipt_path.exists() else {}
                if (receipt.get("status") not in {"passed", "failed"}
                        or receipt.get("session", {}).get("manifest_hash") != freeze["manifest_hash"]
                        or receipt.get("session", {}).get("freeze_signature") != freeze["freeze_signature"]
                        or receipt.get("experiment_id") != experiment_id
                        or receipt.get("arm_id") != arm["arm_id"]
                        or receipt.get("attempt_id") != reservation["attempt_id"]):
                    raise RuntimeError("unfinished local attempt blocks holdout access")
        _append_research_event(directory, freeze, events, "holdout_reserved", {"sha256": design["holdout_sha256"]})
        state, events = _research_state(directory, freeze)
        try:
            # Nonblocking open plus fstat rejects FIFOs/devices before a read
            # can wait forever. The descriptor check avoids a path-swap race.
            fd = os.open(artifact, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise OSError("holdout artifact must be a regular file")
                data = handle.read(64 * 1024 * 1024 + 1)
            status = "read" if len(data) <= 64 * 1024 * 1024 and hashlib.sha256(data).hexdigest() == design["holdout_sha256"] else "hash_mismatch"
        except OSError:
            _append_research_event(directory, freeze, events, "holdout_result", {"status": "read_failed"})
            raise
        _append_research_event(directory, freeze, events, "holdout_result", {"status": status})
        if status != "read":
            raise ValueError("holdout artifact size or hash mismatch; access remains reserved")
        return data
