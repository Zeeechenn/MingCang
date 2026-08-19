"""Canonical RunEnvelope contracts and complete-run selectors."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.data.models.job import JobRun

RUN_ENVELOPE_VERSION = "run_envelope.v1"
OFFICIAL_DAILY_JOBS = (
    "m63_premarket",
    "m63_intraday",
    "m63_postmarket",
    "premarket",
    "postmarket",
)
SIGNAL_PRODUCING_JOBS = ("postmarket", "test2_signal_runner", "paper_trading.test2_signal_runner")
AUTHORITATIVE_PANEL_JOB = "m63_postmarket"
REQUIRED_DAILY_PHASES = ("m63_premarket", "m63_intraday", "m63_postmarket")
DEFAULT_REQUIRED_STEPS = {
    "m63_postmarket": ("m59_panel", "trigger_router", "task_capsule"),
}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _stored_run_envelope_from_row(row: JobRun) -> dict[str, Any] | None:
    """Return only an explicitly persisted v1 envelope, never a synthesized fallback."""
    output = _json_load(row.output_summary_json, {})
    if isinstance(output, dict) and isinstance(output.get("run_envelope"), dict):
        envelope = output["run_envelope"]
        if envelope.get("schema_version") == RUN_ENVELOPE_VERSION:
            return envelope
    input_payload = _json_load(row.input_coverage_json, {})
    if isinstance(input_payload, dict) and isinstance(input_payload.get("run_envelope"), dict):
        envelope = input_payload["run_envelope"]
        if envelope.get("schema_version") == RUN_ENVELOPE_VERSION:
            return envelope
    return None


def stored_run_envelope_from_row(row: JobRun) -> dict[str, Any] | None:
    """Public read helper for callers that must reject synthesized envelopes."""
    return _stored_run_envelope_from_row(row)


def complete_status(row: JobRun) -> bool:
    """Return whether a ledger row is a single complete daily batch."""
    if row.status != "success" or not row.as_of:
        return False
    envelope = _stored_run_envelope_from_row(row)
    if envelope is None:
        return False
    coverage = _as_dict(_as_dict(envelope.get("freshness")).get("input_coverage"))
    if coverage.get("database") == "custom" or coverage.get("authoritative") is False:
        return False
    return envelope.get("status") == "complete"


def run_envelope_from_row(row: JobRun) -> dict[str, Any]:
    """Read the canonical envelope embedded in a JobRun JSON field."""
    stored = _stored_run_envelope_from_row(row)
    if stored is not None:
        return stored
    output = _json_load(row.output_summary_json, {})
    input_payload = _json_load(row.input_coverage_json, {})
    return build_run_envelope(
        run_id=row.run_id,
        job_name=row.job_name,
        trigger_source=row.trigger_source,
        as_of=row.as_of,
        started_at=row.started_at,
        completed_at=row.finished_at,
        row_status=row.status,
        input_coverage=input_payload if isinstance(input_payload, dict) else {},
        result=output if isinstance(output, dict) else {},
        artifact_path=row.artifact_path,
        error=row.error,
    )


def build_run_envelope(
    *,
    run_id: str,
    job_name: str,
    trigger_source: str,
    as_of: str | None,
    started_at: Any = None,
    completed_at: Any = None,
    row_status: str = "running",
    input_coverage: dict[str, Any] | None = None,
    result: Any = None,
    degradations: Iterable[str] | None = None,
    artifact_path: str | Path | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build the Stage-2 RunEnvelope without requiring a new schema table."""
    coverage = dict(input_coverage or {})
    payload = _as_dict(result)
    trade_date = str(
        payload.get("trade_date")
        or payload.get("date")
        or payload.get("as_of")
        or as_of
        or ""
    )[:10] or None
    envelope_as_of = str(as_of or payload.get("as_of") or payload.get("date") or "")[:10] or None
    batch_id = str(
        payload.get("batch_id")
        or coverage.get("batch_id")
        or f"{job_name}:{envelope_as_of or trade_date or 'unknown'}:{run_id[:8]}"
    )
    degradation_list = list(dict.fromkeys(str(item) for item in (degradations or []) if item))
    artifact = artifact_path or payload.get("output_path") or payload.get("artifact_path")
    expected = (
        _int_or_none(coverage.get("expected_symbols"))
        or _int_or_none(coverage.get("expected"))
        or _int_or_none(payload.get("stocks"))
        or _int_or_none(payload.get("input_stocks"))
    )
    completed = (
        _int_or_none(payload.get("completed"))
        or _int_or_none(payload.get("saved"))
        or _int_or_none(payload.get("processed"))
        or _int_or_none(payload.get("succeeded"))
    )
    failed = (
        _int_or_none(payload.get("failed"))
        or _int_or_none(payload.get("errors"))
        or 0
    )
    if "required_steps" in coverage:
        required_step_source = coverage.get("required_steps") or []
    elif "required_steps" in payload:
        required_step_source = payload.get("required_steps") or []
    else:
        required_step_source = DEFAULT_REQUIRED_STEPS.get(job_name, ())
    required_steps = tuple(str(item) for item in required_step_source if item)
    step_rows = [step for step in payload.get("steps", []) if isinstance(step, dict)]
    step_by_name = {str(step.get("name") or ""): step for step in step_rows}
    failed_required_steps: list[str] = []
    completed_required_steps: list[str] = []
    missing_required_steps: list[str] = []
    for name in required_steps:
        step = step_by_name.get(name)
        if step is None:
            missing_required_steps.append(name)
            continue
        raw_step_result = step.get("result")
        step_result = raw_step_result if isinstance(raw_step_result, dict) else {}
        if step.get("ok") is False or step_result.get("skipped"):
            failed_required_steps.append(name)
        else:
            completed_required_steps.append(name)
    complete_counts = failed == 0 and (expected is None or completed == expected)
    complete_required_steps = not required_steps or (
        len(completed_required_steps) == len(required_steps)
        and not failed_required_steps
        and not missing_required_steps
    )
    if error:
        status = "failed"
    elif row_status == "success" and complete_counts and complete_required_steps and payload.get("ok") is not False:
        status = "complete"
    elif row_status == "running":
        status = "running"
    else:
        status = "partial"
    return {
        "schema_version": RUN_ENVELOPE_VERSION,
        "run_id": run_id,
        "batch_id": batch_id,
        "trade_date": trade_date,
        "as_of": envelope_as_of,
        "scope": str(coverage.get("scope") or payload.get("scope") or payload.get("mode") or "daily"),
        "entrypoint": job_name,
        "trigger_source": trigger_source,
        "started_at": _iso(started_at),
        "completed_at": _iso(completed_at),
        "status": status,
        "expected": {"symbols": expected},
        "completed": {"symbols": completed},
        "failed": {"symbols": failed},
        "freshness": {
            "as_of": envelope_as_of,
            "input_coverage": {k: v for k, v in coverage.items() if k != "run_envelope"},
            "fresh_close_required": payload.get("fresh_close_required"),
        },
        "degradations": degradation_list,
        "required": {
            "steps": list(required_steps),
            "completed_steps": completed_required_steps,
            "failed_steps": failed_required_steps,
            "missing_steps": missing_required_steps,
        },
        "profile": {
            "signal_profile": settings.paper_trading_profile,
            "rule_version": payload.get("rule_version") or coverage.get("rule_version"),
        },
        "artifacts": [str(item) for item in _as_list(artifact)],
    }


def select_complete_daily_run(
    db,
    *,
    as_of: str | None = None,
    job_names: Iterable[str] = (AUTHORITATIVE_PANEL_JOB,),
) -> dict[str, Any]:
    """Select exactly one authoritative complete daily run, never merging partials."""
    names = tuple(job_names)
    query = db.query(JobRun).filter(JobRun.job_name.in_(names), JobRun.status == "success")
    if as_of is not None:
        query = query.filter(JobRun.as_of == as_of)
    rows = query.order_by(JobRun.as_of.desc(), JobRun.started_at.desc(), JobRun.id.desc()).all()
    complete_rows = [
        row for row in rows
        if complete_status(row) and close_confirmed_declared(_stored_run_envelope_from_row(row))
    ]
    if not complete_rows:
        return {"status": "missing", "job_run": None, "as_of": as_of, "candidates": 0}
    target_as_of = str(as_of or complete_rows[0].as_of)
    same_day = [row for row in complete_rows if str(row.as_of)[:10] == target_as_of[:10]]
    if len(same_day) != 1:
        return {
            "status": "ambiguous",
            "job_run": None,
            "as_of": target_as_of,
            "candidates": len(same_day),
            "run_ids": [row.run_id for row in same_day],
        }
    return {
        "status": "selected",
        "job_run": same_day[0],
        "as_of": str(same_day[0].as_of)[:10] if same_day[0].as_of else None,
        "candidates": 1,
        "run_envelope": run_envelope_from_row(same_day[0]),
    }


def close_confirmed_declared(envelope: dict[str, Any] | None) -> bool:
    """False only when a run explicitly states it finished before the close.

    A postmarket run executed mid-session describes the previous session, so it
    must neither stand as the day's authoritative run nor make a later,
    close-confirmed rerun look ambiguous.
    """
    if envelope is None:
        return True
    return _as_dict(envelope.get("freshness")).get("close_confirmed") is not False


def select_complete_run_for_batch(
    db,
    *,
    as_of: str,
    batch_id: str,
    min_symbols: int | None = None,
    job_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Select one explicit complete run whose envelope covers a signal batch."""
    query = db.query(JobRun).filter(JobRun.status == "success", JobRun.as_of == as_of)
    if job_names is not None:
        query = query.filter(JobRun.job_name.in_(tuple(job_names)))
    rows = query.order_by(JobRun.started_at.desc(), JobRun.id.desc()).all()
    matches: list[tuple[JobRun, dict[str, Any]]] = []
    for row in rows:
        if not complete_status(row):
            continue
        envelope = _stored_run_envelope_from_row(row)
        if envelope is None:
            continue
        coverage = _as_dict(_as_dict(envelope.get("freshness")).get("input_coverage"))
        covered_batch = (
            envelope.get("batch_id") == batch_id
            or coverage.get("batch_id") == batch_id
            or coverage.get("signal_batch_id") == batch_id
        )
        if not covered_batch:
            continue
        completed_symbols = _int_or_none(_as_dict(envelope.get("completed")).get("symbols"))
        if min_symbols is not None and completed_symbols is not None and completed_symbols < min_symbols:
            continue
        matches.append((row, envelope))
    if not matches:
        return {"status": "missing", "job_run": None, "as_of": as_of, "batch_id": batch_id, "candidates": 0}
    if len(matches) != 1:
        return {
            "status": "ambiguous",
            "job_run": None,
            "as_of": as_of,
            "batch_id": batch_id,
            "candidates": len(matches),
            "run_ids": [row.run_id for row, _ in matches],
        }
    row, envelope = matches[0]
    return {
        "status": "selected",
        "job_run": row,
        "as_of": as_of,
        "batch_id": batch_id,
        "candidates": 1,
        "run_envelope": envelope,
    }


def evaluate_daily_bundle(
    db,
    *,
    as_of: str,
    required_phases: Iterable[str] = REQUIRED_DAILY_PHASES,
) -> dict[str, Any]:
    """Evaluate configured daily phase completeness without collapsing phases."""
    phases = tuple(required_phases)
    selected: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    for phase in phases:
        outcome = select_complete_daily_run(db, as_of=as_of, job_names=(phase,))
        if outcome["status"] == "selected":
            selected[phase] = outcome["run_envelope"]
        elif outcome["status"] == "ambiguous":
            ambiguous.append(phase)
        else:
            missing.append(phase)
    status = "complete" if not missing and not ambiguous else "incomplete"
    return {
        "schema_version": "daily_bundle_contract.v1",
        "as_of": as_of,
        "status": status,
        "required_phases": list(phases),
        "completed_phases": sorted(selected),
        "missing_phases": missing,
        "ambiguous_phases": ambiguous,
        "run_envelopes": selected,
    }


def build_proposal_gate_contract(
    *,
    proposal_id: str,
    as_of: str,
    proposal: dict[str, Any],
    revalidation: dict[str, Any],
    gate: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Research/simulation contract for proposal -> revalidate -> gate -> audit."""
    passed = bool(revalidation.get("ok") and gate.get("ok") and audit.get("ok"))
    return {
        "schema_version": "proposal_gate_contract.v1",
        "proposal_id": proposal_id,
        "as_of": as_of,
        "status": "complete" if passed else "blocked",
        "simulation_only": True,
        "broker_connection": "forbidden",
        "steps": {
            "proposal": proposal,
            "revalidate": revalidation,
            "gate": gate,
            "audit": audit,
        },
    }
