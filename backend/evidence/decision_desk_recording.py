"""Offline observation recorder for decision-desk model attempts.

This module records explicitly supplied request bytes, injected provider output,
and caller-provided tool observation bytes. It is not a trading ledger, runner,
freeze mechanism, model client, or proof of OS isolation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Provider = Callable[[bytes], dict[str, Any]]
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
REPO_ROOT = Path(__file__).resolve().parents[2]


def record_model_observation(
    *,
    output_root: Path,
    experiment_id: str,
    arm_id: str,
    attempt_id: str,
    requested_model: str,
    cutoff: datetime,
    provider: Provider,
    budget: dict[str, Any],
    request_bytes: bytes | None = None,
    request_payload: dict[str, Any] | None = None,
    tool_observations: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Record one explicit, offline provider attempt under an exclusive directory."""
    _validate_identifier(experiment_id)
    _validate_identifier(arm_id)
    _validate_identifier(attempt_id)
    if not isinstance(requested_model, str) or not requested_model.strip():
        raise ValueError("requested_model must be a non-empty string")
    if not _is_aware(cutoff):
        raise ValueError("cutoff must be timezone-aware")
    _validate_budget(budget)
    root = _resolve_output_root(output_root)
    request = _request_bytes(request_bytes=request_bytes, request_payload=request_payload)
    if tool_observations is not None and not isinstance(tool_observations, dict):
        raise ValueError("tool_observations must be a mapping of name to bytes")
    for name, payload in (tool_observations or {}).items():
        _validate_identifier(name)
        if not isinstance(payload, bytes):
            raise ValueError("tool observation payloads must be bytes")

    attempt_dir = root / experiment_id / arm_id / attempt_id
    if not attempt_dir.resolve().is_relative_to(root):
        raise ValueError("attempt path resolves outside output_root")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    artifacts: dict[str, str] = {}
    errors: list[str] = []
    started_at = _now_iso()

    request_path = attempt_dir / "request.bin"
    request_path.write_bytes(request)
    request_digest = _sha256_bytes(request)
    artifacts[request_digest] = _relative(root, request_path)

    tool_entries = _write_tool_observations(
        root=root,
        attempt_dir=attempt_dir,
        artifacts=artifacts,
        tool_observations=tool_observations,
    )

    resolved_model: str | None = None
    response_entry: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    try:
        provider_result = provider(request)
        if not isinstance(provider_result, dict):
            errors.append("provider_result_must_be_dict")
            response_bytes = b""
        else:
            resolved_raw = provider_result.get("resolved_model")
            if isinstance(resolved_raw, str) and resolved_raw.strip():
                resolved_model = resolved_raw
            else:
                errors.append("resolved_model_required")
            response_raw = provider_result.get("response_bytes")
            if isinstance(response_raw, bytes):
                response_bytes = response_raw
            else:
                errors.append("response_bytes_required")
                response_bytes = b""
            usage_raw = provider_result.get("usage")
            usage = usage_raw if isinstance(usage_raw, dict) else None
            if usage is None:
                errors.append("usage_required")
            else:
                _validate_reported_usage(usage=usage, budget=budget, errors=errors)
        if resolved_model != requested_model:
            errors.append("resolved_model_mismatch")
        response_path = attempt_dir / "response.bin"
        response_path.write_bytes(response_bytes)
        response_digest = _sha256_bytes(response_bytes)
        artifacts[response_digest] = _relative(root, response_path)
        response_entry = {"path": _relative(root, response_path), "sha256": response_digest}
    except Exception as exc:
        errors.append("provider_exception")
        errors.append(f"{type(exc).__name__}: {exc}")
        (attempt_dir / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")

    receipt = {
        "schema_version": "decision_desk_recording.v1",
        "status": "failed" if errors else "passed",
        "experiment_id": experiment_id,
        "arm_id": arm_id,
        "attempt_id": attempt_id,
        "cutoff": cutoff.isoformat(),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "model_receipt": {
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "request_receipt_hash": request_digest,
            "response_receipt_hash": response_entry["sha256"] if response_entry else None,
        },
        "visible_input": {"path": _relative(root, request_path), "sha256": request_digest},
        "response": response_entry,
        "usage": usage,
        "provider_calls_invoked": 1,
        "budget": dict(budget),
        "tool_observations": tool_entries,
        "artifacts": artifacts,
        "errors": errors,
        "claims": {
            "complete_runner": False,
            "trading_ledger": False,
            "os_isolation_proven": False,
            "profitability_certified": False,
            "tool_observations_provider_verified": False,
        },
    }
    (attempt_dir / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return receipt


def _write_tool_observations(
    *,
    root: Path,
    attempt_dir: Path,
    artifacts: dict[str, str],
    tool_observations: dict[str, bytes] | None,
) -> list[dict[str, Any]]:
    if not tool_observations:
        return []
    tool_dir = attempt_dir / "tool_observations"
    tool_dir.mkdir()
    entries: list[dict[str, Any]] = []
    for name, payload in sorted(tool_observations.items()):
        _validate_identifier(name)
        if not isinstance(payload, bytes):
            raise ValueError("tool observation payloads must be bytes")
        path = tool_dir / f"{name}.bin"
        path.write_bytes(payload)
        digest = _sha256_bytes(payload)
        relative = _relative(root, path)
        artifacts[digest] = relative
        entries.append({"name": name, "path": relative, "sha256": digest, "provider_observed": False})
    return entries


def _request_bytes(*, request_bytes: bytes | None, request_payload: dict[str, Any] | None) -> bytes:
    if (request_bytes is None) == (request_payload is None):
        raise ValueError("provide exactly one of request_bytes or request_payload")
    if request_bytes is not None:
        if not isinstance(request_bytes, bytes):
            raise ValueError("request_bytes must be bytes")
        return request_bytes
    if not isinstance(request_payload, dict):
        raise ValueError("request_payload must be a dict")
    return json.dumps(
        request_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _validate_identifier(value: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError("invalid path identifier")
    if value in {".", ".."} or "/" in value or "\\" in value or Path(value).is_absolute():
        raise ValueError("invalid path identifier")


def _resolve_output_root(output_root: Path) -> Path:
    root = Path(output_root).expanduser().resolve()
    if root == REPO_ROOT or REPO_ROOT in root.parents:
        raise ValueError("output_root must be outside the repository")
    return root


def _validate_budget(budget: dict[str, Any]) -> None:
    if not isinstance(budget, dict):
        raise ValueError("invalid budget")
    max_model_calls = budget.get("max_model_calls")
    max_cost_cny = budget.get("max_cost_cny")
    if not isinstance(max_model_calls, int) or max_model_calls != 1 or isinstance(max_model_calls, bool):
        raise ValueError("invalid budget")
    if _finite_nonnegative_number(max_cost_cny) is None:
        raise ValueError("invalid budget")


def _validate_reported_usage(*, usage: dict[str, Any], budget: dict[str, Any], errors: list[str]) -> None:
    model_calls = _finite_nonnegative_number(usage.get("model_calls"))
    cost_cny = _finite_nonnegative_number(usage.get("cost_cny"))
    if model_calls is None or cost_cny is None:
        errors.append("usage_invalid")
        return
    if model_calls != 1:
        errors.append("usage_model_calls_must_match_one_invocation")
    if model_calls > 1 or cost_cny > float(budget["max_cost_cny"]):
        errors.append("usage_exceeds_budget")


def _finite_nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
