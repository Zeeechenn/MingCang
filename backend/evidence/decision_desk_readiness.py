"""Separate operational continuity, output quality, data and return evidence.

Explicit offline inputs only. This report never activates a model, scheduler,
memory route or trading policy, and never certifies investment returns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CARD_TYPES = (
    "batch_integrity", "candidate", "position_health", "event_risk",
    "watchtower", "daily_delta", "human_confirmation", "review_attribution",
)


def build_readiness_report(
    *, as_of: str, continuity: dict[str, Any], panel: dict[str, Any],
    nav_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Classify supplied runtime artifacts without treating 20 days as quality."""
    datetime.strptime(as_of, "%Y-%m-%d")
    operational: list[str] = []
    days = continuity.get("days", [])
    day: dict[str, Any] = next((d for d in days if d.get("date") == as_of), {})
    if continuity.get("status") != "complete":
        operational.append("continuity_window_incomplete")
    if not day or day.get("status") != "complete":
        operational.append("requested_day_not_complete")
    checks = day.get("checks", {})
    for key, expected in {
        "artifact_panel": "complete", "batch_envelope_match": "matched",
        "run_envelope": "complete", "signal_batch_identity": "unique",
        "signal_run": "complete",
    }.items():
        if checks.get(key) != expected:
            operational.append(f"requested_day.{key}")

    quality: list[str] = []
    if panel.get("as_of") != as_of:
        quality.append("panel_date_mismatch_or_missing")
    if panel.get("ledger_commit_state") != "committed":
        quality.append("panel_not_committed")
    contract = panel.get("artifact_contract", {})
    if contract.get("close_confirmed") is not True:
        quality.append("panel_not_close_confirmed")
    if not day.get("run_id") or contract.get("source_job_run_id") != day.get("run_id"):
        quality.append("panel_run_mismatch_or_missing")
    cards = panel.get("cards", [])
    types = [c.get("card_type") for c in cards]
    if types != list(CARD_TYPES):
        quality.append("card_identity_order_or_count")
    card_states: dict[str, str] = {}
    for card in cards:
        kind = str(card.get("card_type", "unknown"))
        status = str(card.get("status", "missing"))
        card_states[kind] = status
        if status == "ready":
            continue
        payload = card.get("payload", {})
        reason = payload.get("reason") or payload.get("no_data_reason")
        if status == "ready_zero" and isinstance(reason, str) and reason.strip():
            continue
        if (status == "not_applicable" and card.get("lifecycle") == "shadow"
                and isinstance(reason, str) and reason.strip()):
            continue
        quality.append(f"{kind}:{status}")

    data: list[str] = []
    snapshot = nav_evidence.get("snapshot", {})
    digest = snapshot.get("sha256_before")
    if not digest or digest != snapshot.get("sha256_after"):
        data.append("snapshot_hash_missing_or_changed")
    lineage = nav_evidence.get("lineage", {})
    price_issues = lineage.get("price_basis_issues")
    if not isinstance(price_issues, list):
        price_issues = []
        data.append("price_basis_evidence_missing")
    if price_issues:
        data.append("price_basis_issues")
    if lineage.get("price_window", {}).get("end") != as_of:
        data.append("price_evidence_date_mismatch")
    actions = lineage.get("corporate_actions", {})
    if actions.get("status") != "authoritative":
        data.append("authoritative_corporate_actions_unavailable")
    if nav_evidence.get("status") == "blocked_price_basis":
        data.append("nav_price_basis_blocked")

    economics = ["prospective_matched_model_evidence_not_supplied"]
    if data:
        economics.append("data_gate_blocked")
    return {
        "schema_version": "decision_desk_readiness.v1", "as_of": as_of,
        "gates": {
            "operational": _gate(operational), "output_quality": _gate(quality),
            "data": _gate(data), "economic": _gate(economics),
        },
        "card_states": card_states,
        "price_basis_issues": price_issues,
        "work_metrics": continuity.get("metrics", {}).get("work_metrics", {}),
        "scope": "read_only_quality_and_data_collection",
        "economic_trial_ready": False, "certifies_returns": False,
        "changes_production": False,
    }


def select_evaluation_memory(
    items: list[dict[str, Any]], *, arm_id: str, cutoff: datetime,
) -> dict[str, Any]:
    """Select explicit arm-local validated memory; never load production memory.

    Updates after cutoff are excluded even when creation was earlier. Outcome
    memories additionally require the time the outcome became observable.
    Unknown timestamps and cross-arm entries are excluded, not repaired.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    if not arm_id:
        raise ValueError("arm_id required")
    accepted, excluded = [], []
    for item in items:
        reasons = []
        if item.get("arm_id") != arm_id:
            reasons.append("cross_arm_or_unscoped")
        if item.get("status") != "validated":
            reasons.append("not_validated")
        required = ["created_at", "updated_at"]
        if item.get("memory_type") in {"outcome", "lesson"}:
            required.append("outcome_available_at")
        for field in required:
            value = _aware(item.get(field))
            if value is None or value > cutoff:
                reasons.append(f"{field}_unknown_or_future")
        if "expires_at" in item:
            expiry = _aware(item["expires_at"])
            if expiry is None or expiry <= cutoff:
                reasons.append("expired_or_unknown_expiry")
        if reasons:
            excluded.append({"id": item.get("id"), "reasons": reasons})
        else:
            accepted.append(dict(item))
    return {"accepted": accepted, "excluded": excluded, "cutoff": cutoff.isoformat(),
            "arm_id": arm_id, "production_memory_written": False}


def _aware(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def _gate(reasons: list[str]) -> dict[str, Any]:
    return {"status": "blocked" if reasons else "passed", "blockers": reasons}


def build_quality_window_report(
    *, runs_root: Path, schedule: dict[str, Any], evaluated_at: datetime,
) -> dict[str, Any]:
    """Read saved daily collections against an explicit schedule, without reruns.

    Dates/timezone are caller declarations, not a certified trading calendar or
    proof of preregistration. Future slots are not read. Hashes bind saved bytes,
    not their factual accuracy, user completion or actual model observations.
    """
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    zone = ZoneInfo(schedule["timezone"])
    start = date.fromisoformat(schedule["contract_start"])
    slots = [_aware(value) for value in schedule["scheduled_at"]]
    if not slots or any(slot is None for slot in slots):
        raise ValueError("schedule requires timezone-aware timestamps")
    times = [slot.astimezone(zone) for slot in slots if slot is not None]
    dates = [slot.date() for slot in times]
    if dates != sorted(set(dates)) or dates[0] < start:
        raise ValueError("schedule dates must be unique, ordered and on/after contract_start")
    root = runs_root.expanduser().resolve()
    days: list[dict[str, Any]] = []
    for slot in times:
        day = slot.date().isoformat()
        item: dict[str, Any] = {"as_of": day, "scheduled_at": slot.isoformat(), "blockers": []}
        if slot > evaluated_at:
            item["status"] = "not_due"
        elif not (root / day).exists() and not (root / day).is_symlink():
            item.update(status="missing", blockers=["collection_missing"])
        else:
            try:
                item.update(_read_quality_collection(root, day, evaluated_at, zone))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                # Malformed artifacts are failed evidence, never successful zeroes.
                reason = str(exc) if isinstance(exc, _CollectionError) else "invalid_artifact_shape"
                item.update(status="failed", blockers=[reason])
        days.append(item)
    counts = {state: sum(item["status"] == state for item in days)
              for state in ("passed", "blocked", "failed", "missing", "not_due")}
    counts.update(scheduled=len(days), due=len(days) - counts["not_due"])
    gates: dict[str, Any] = {}
    card_blockers: dict[str, list[str]] = {}
    for name in ("operational", "output_quality", "data", "economic"):
        passed = [item["as_of"] for item in days
                  if item.get("gates", {}).get(name, {}).get("status") == "passed"]
        blocked = [item["as_of"] for item in days
                   if item["status"] != "not_due" and item["as_of"] not in passed]
        gates[name] = {"status": "blocked" if blocked else "pending" if counts["not_due"] else "passed",
                       "passed_dates": passed, "blocked_or_missing_dates": blocked,
                       "pass_rate_due": len(passed) / counts["due"] if counts["due"] else None}
    for item in days:
        for reason in item.get("gates", {}).get("output_quality", {}).get("blockers", []):
            card_blockers.setdefault(reason, []).append(item["as_of"])
    return {
        "schema_version": "decision_desk_quality_window.v1", "evaluated_at": evaluated_at.isoformat(),
        "schedule": schedule, "schedule_sha256": hashlib.sha256(
            json.dumps(schedule, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "schedule_authority": "caller_supplied_not_calendar_or_preregistration_certification",
        "runs_root": str(root), "days": days, "counts": counts, "gates": gates,
        "status": "blocked" if counts["blocked"] + counts["failed"] + counts["missing"]
        else "pending" if counts["not_due"] else "passed",
        "card_blockers": card_blockers,
        "human_completion": {"status": "not_evaluated", "reason": "requires_actual_user_completion_evidence"},
        "model_quality": {"status": "not_evaluated", "reason": "requires_response_and_provider_evidence"},
        "scope": "saved_collection_contract_checks_only", "changes_production": False,
        "economic_trial_ready": False, "certifies_returns": False,
    }


class _CollectionError(ValueError):
    """A stable reportable reason for refusing a saved collection."""


def _regular_path(folder: Path, name: str) -> Path:
    path = folder / name
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise _CollectionError(f"non_regular_artifact:{name}")
    return path


def _json_bytes(folder: Path, name: str) -> bytes:
    path = _regular_path(folder, name)
    with path.open("rb") as handle:
        data = handle.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise _CollectionError(f"artifact_too_large:{name}")
    return data


def _file_digest(folder: Path, name: str) -> str:
    with _regular_path(folder, name).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _object(data: bytes) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise _CollectionError("invalid_artifact_shape")
    return value


def _read_quality_collection(root: Path, day: str, now: datetime, zone: ZoneInfo) -> dict[str, Any]:
    folder = root / day / "collection"
    if (root / day).is_symlink() or folder.is_symlink():
        raise _CollectionError("symlinked_collection")
    manifest_bytes = _json_bytes(folder, "manifest.json")
    manifest = _object(manifest_bytes)
    if manifest.get("as_of") != day:
        raise _CollectionError("collection_date_mismatch")
    collected = _aware(manifest.get("collected_at"))
    if collected is None or collected > now or collected.astimezone(zone).date().isoformat() != day:
        raise _CollectionError("collection_time_invalid")
    if (manifest.get("snapshot_unchanged") is not True or manifest.get("writes_production") is not False
            or manifest.get("provider_called") is not False
            or manifest.get("scope") != "quality_collection_not_economic_trial"):
        raise _CollectionError("collection_scope_invalid")
    if any((folder / ("snapshot.db" + suffix)).exists()
           or (folder / ("snapshot.db" + suffix)).is_symlink() for suffix in ("-wal", "-shm")):
        raise _CollectionError("snapshot_sidecar_present")
    objects, verified = {}, {}
    for name in ("continuity.json", "panel.json", "nav.json", "readiness.json", "snapshot.db"):
        data = None if name == "snapshot.db" else _json_bytes(folder, name)
        digest = _file_digest(folder, name) if data is None else hashlib.sha256(data).hexdigest()
        if manifest["sha256"].get(name) != digest:
            raise _CollectionError(f"hash_mismatch:{name}")
        verified[name] = digest
        if data is not None:
            objects[name] = _object(data)
    saved, nav = objects["readiness.json"], objects["nav.json"]
    if saved.get("as_of") != day:
        raise _CollectionError("collection_date_mismatch")
    if saved.get("prospective_collection") is not True:
        raise _CollectionError("not_prospective_collection")
    if _aware(saved.get("collected_at")) != collected:
        raise _CollectionError("collection_time_mismatch")
    snapshot = nav.get("snapshot", {})
    if any(value != verified["snapshot.db"] for value in (
        snapshot.get("sha256_before"), snapshot.get("sha256_after"), saved.get("snapshot_sha256"),
    )):
        raise _CollectionError("snapshot_binding_mismatch")
    continuity = objects["continuity.json"]
    matching = [item for item in continuity["days"] if item.get("date") == day]
    if len(matching) != 1:
        raise _CollectionError("day_identity_not_unique")
    recomputed = build_readiness_report(
        as_of=day, continuity=continuity, panel=objects["panel.json"], nav_evidence=nav,
    )
    if saved.get("gates") != recomputed["gates"] or saved.get("card_states") != recomputed["card_states"]:
        raise _CollectionError("saved_gates_mismatch")
    # Detect non-atomic reads; the saved collection must stay immutable during evaluation.
    if (_json_bytes(folder, "manifest.json") != manifest_bytes
            or any(_file_digest(folder, name) != digest for name, digest in verified.items())):
        raise _CollectionError("collection_changed_during_read")
    blockers = [f"{gate}:{reason}" for gate in ("operational", "output_quality")
                for reason in recomputed["gates"][gate]["blockers"]]
    return {"status": "blocked" if blockers else "passed", "blockers": blockers,
            "gates": recomputed["gates"], "card_states": recomputed["card_states"],
            "run_id": matching[0].get("run_id"), "collected_at": collected.isoformat(),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "verified_sha256": verified, "hash_scope": "listed_five_files_only",
            "authenticity_verified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only window audit of saved quality collections.")
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True,
                        help="JSON with timezone, contract_start and ordered scheduled_at timestamps")
    parser.add_argument("--evaluated-at", help="Aware evaluation timestamp; defaults to current UTC time")
    args = parser.parse_args()
    try:
        now = _aware(args.evaluated_at) if args.evaluated_at else datetime.now(UTC)
        if now is None:
            raise ValueError("evaluated-at must be timezone-aware")
        result = build_quality_window_report(
            runs_root=args.runs_root, schedule=_object(args.schedule.read_bytes()), evaluated_at=now,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
