"""Best-effort persistent ledger for scheduled and manual workflows."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table

from backend.config import settings
from backend.data.models.job import JobRun
from backend.runtime_identity import build_runtime_identity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobRunHandle:
    run_id: str
    persisted: bool


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _session():
    from backend.data.database import SessionLocal

    return SessionLocal()


def _ensure_table(db) -> None:
    cast(Table, JobRun.__table__).create(bind=db.get_bind(), checkfirst=True)


def _result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"result_type": type(result).__name__, "value": str(result)[:500]}
    summary_keys = (
        "ok",
        "status",
        "mode",
        "date",
        "as_of",
        "count",
        "processed",
        "succeeded",
        "failed",
        "skipped",
    )
    summary = {key: result[key] for key in summary_keys if key in result}
    if isinstance(result.get("steps"), list):
        summary["steps"] = [
            {
                "name": step.get("name"),
                "ok": step.get("ok"),
                "skipped": (step.get("result") or {}).get("skipped")
                if isinstance(step, dict)
                else None,
            }
            for step in result["steps"]
            if isinstance(step, dict)
        ]
    return summary


def _degradation_reasons(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    reasons = [str(item) for item in result.get("degradation_reasons", []) if item]
    if result.get("ok") is False:
        reasons.append(str(result.get("reason") or result.get("error") or "workflow returned ok=false"))
    for step in result.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("ok") is False:
            reasons.append(f"{step.get('name') or 'step'}: {step.get('error') or 'failed'}")
        step_result = step.get("result")
        if isinstance(step_result, dict) and step_result.get("skipped"):
            reasons.append(
                f"{step.get('name') or 'step'} skipped: "
                f"{step_result.get('reason') or 'unspecified'}"
            )
    return list(dict.fromkeys(reasons))


def _artifact_path(result: Any, explicit: str | Path | None) -> str | None:
    candidate = explicit
    if candidate is None and isinstance(result, dict):
        candidate = result.get("output_path") or result.get("artifact_path")
    if candidate is None:
        return None
    path = Path(str(candidate))
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return path.name


def terminal_status(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("skipped"):
            return "skipped"
        if result.get("ok") is False or _degradation_reasons(result):
            return "degraded"
    return "success"


def start_job_run(
    job_name: str,
    *,
    trigger_source: str,
    as_of: str | None = None,
    input_coverage: dict[str, Any] | None = None,
) -> JobRunHandle:
    """Create a running ledger row without blocking the underlying workflow on failure."""
    run_id = uuid.uuid4().hex
    if not settings.job_ledger_enabled:
        return JobRunHandle(run_id=run_id, persisted=False)

    db = _session()
    try:
        _ensure_table(db)
        identity = build_runtime_identity(settings)
        db.add(JobRun(
            run_id=run_id,
            job_name=job_name,
            trigger_source=trigger_source,
            as_of=as_of,
            status="running",
            started_at=_utcnow(),
            input_coverage_json=_json(input_coverage or {}),
            degradation_reasons_json=_json([]),
            runtime_version=identity["version"],
            build_commit=identity["build_commit"],
            db_role=identity["db_role"],
        ))
        db.commit()
        return JobRunHandle(run_id=run_id, persisted=True)
    except Exception:
        db.rollback()
        logger.exception("job ledger start failed for %s", job_name)
        return JobRunHandle(run_id=run_id, persisted=False)
    finally:
        db.close()


def finish_job_run(
    handle: JobRunHandle,
    *,
    result: Any = None,
    error: BaseException | None = None,
    artifact_path: str | Path | None = None,
) -> None:
    """Finalize a ledger row; errors are logged but never mask the workflow result."""
    if not handle.persisted:
        return

    db = _session()
    try:
        row = db.query(JobRun).filter(JobRun.run_id == handle.run_id).one_or_none()
        if row is None:
            logger.error("job ledger row disappeared: %s", handle.run_id)
            return
        finished = _utcnow()
        row.finished_at = finished
        row.duration_seconds = round((finished - row.started_at).total_seconds(), 3)
        row.updated_at = finished
        if error is not None:
            row.status = "error"
            row.error = str(error)[:2000]
            row.degradation_reasons_json = _json([str(error)[:500]])
        else:
            row.status = terminal_status(result)
            row.output_summary_json = _json(_result_summary(result))
            row.degradation_reasons_json = _json(_degradation_reasons(result))
            if row.as_of is None and isinstance(result, dict):
                row.as_of = str(result.get("as_of") or result.get("date") or "") or None
            row.artifact_path = _artifact_path(result, artifact_path)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("job ledger finish failed for %s", handle.run_id)
    finally:
        db.close()


def serialize_job_run(row: JobRun) -> dict[str, Any]:
    def parsed(value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    return {
        "run_id": row.run_id,
        "job_name": row.job_name,
        "trigger_source": row.trigger_source,
        "as_of": row.as_of,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "duration_seconds": row.duration_seconds,
        "input_coverage": parsed(row.input_coverage_json, {}),
        "degradation_reasons": parsed(row.degradation_reasons_json, []),
        "output_summary": parsed(row.output_summary_json, {}),
        "artifact_path": row.artifact_path,
        "error": row.error,
        "runtime_version": row.runtime_version,
        "build_commit": row.build_commit,
        "db_role": row.db_role,
    }
