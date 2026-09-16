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
from backend.ops.run_envelope import build_run_envelope
from backend.runtime_identity import build_runtime_identity

logger = logging.getLogger(__name__)


class JobRunFinalizationError(RuntimeError):
    """Raised when a mandatory tracked-run finalizer cannot preserve truth."""


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


def _input_payload(
    *,
    run_id: str,
    job_name: str,
    trigger_source: str,
    as_of: str | None,
    input_coverage: dict[str, Any] | None,
    started_at: datetime,
) -> dict[str, Any]:
    payload = dict(input_coverage or {})
    payload["run_envelope"] = build_run_envelope(
        run_id=run_id,
        job_name=job_name,
        trigger_source=trigger_source,
        as_of=as_of,
        started_at=started_at,
        row_status="running",
        input_coverage=payload,
    )
    return payload


def _output_payload(
    *,
    handle: JobRunHandle,
    row: JobRun,
    result: Any,
    artifact_path: str | Path | None,
    finished_at: datetime,
) -> dict[str, Any]:
    summary = _result_summary(result)
    reasons = _degradation_reasons(result)
    summary["run_envelope"] = build_run_envelope(
        run_id=handle.run_id,
        job_name=row.job_name,
        trigger_source=row.trigger_source,
        as_of=row.as_of,
        started_at=row.started_at,
        completed_at=finished_at,
        row_status=terminal_status(result),
        input_coverage=_read_json(row.input_coverage_json),
        result=result,
        degradations=reasons,
        artifact_path=artifact_path,
    )
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


def _read_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


def _raw_artifact_path(result: Any, explicit: str | Path | None) -> str | Path | None:
    if explicit is not None:
        return explicit
    if isinstance(result, dict):
        return result.get("output_path") or result.get("artifact_path")
    return None


def _should_write_m63_daily_panel_artifact(row: JobRun, result: Any) -> bool:
    if row.job_name != "m63_postmarket" or row.trigger_source not in {"scheduler", "manual_cli"}:
        return False
    if row.status != "success":
        return False
    if not isinstance(result, dict):
        return False
    coverage = _read_json(row.input_coverage_json)
    if coverage.get("workflow") != "m63_daily" or coverage.get("mode") != "postmarket":
        return False
    if coverage.get("database") == "custom" or coverage.get("authoritative") is False:
        return False
    output = _read_json(row.output_summary_json)
    envelope = output.get("run_envelope") if isinstance(output, dict) else None
    return isinstance(envelope, dict) and envelope.get("status") == "complete"


def _attach_m63_daily_panel_artifact(db, row: JobRun, result: Any, artifact_path: str | Path | None) -> dict[str, Any] | None:
    if not _should_write_m63_daily_panel_artifact(row, result):
        return None
    markdown_artifact = _raw_artifact_path(result, artifact_path)
    if markdown_artifact is None:
        raise JobRunFinalizationError("m63 daily panel artifact finalization failed: missing_markdown_artifact")
    try:
        from backend.evidence.daily_panel import build_and_write_daily_panel_artifact_for_job_run

        return build_and_write_daily_panel_artifact_for_job_run(
            db,
            row,
            markdown_artifact_path=markdown_artifact,
            workflow_result=result,
        )
    except Exception as exc:  # noqa: BLE001 - must fail closed for authoritative scheduler runs.
        raise JobRunFinalizationError(
            f"m63 daily panel artifact finalization failed: {exc}"
        ) from exc


def _mark_m63_daily_panel_artifact_committed(finalization: dict[str, Any] | None) -> None:
    if not finalization:
        return
    try:
        from backend.evidence.daily_panel import mark_daily_panel_artifact_committed

        mark_daily_panel_artifact_committed(
            finalization["artifact_path"],
            run_id=str((finalization.get("run_envelope") or {}).get("run_id") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - post-DB artifact truth must fail closed.
        raise JobRunFinalizationError(
            f"m63 daily panel artifact commit mark failed: {exc}"
        ) from exc


def terminal_status(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("skipped"):
            return "skipped"
        if result.get("ok") is False:
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
        started = _utcnow()
        db.add(JobRun(
            run_id=run_id,
            job_name=job_name,
            trigger_source=trigger_source,
            as_of=as_of,
            status="running",
            started_at=started,
            input_coverage_json=_json(_input_payload(
                run_id=run_id,
                job_name=job_name,
                trigger_source=trigger_source,
                as_of=as_of,
                input_coverage=input_coverage,
                started_at=started,
            )),
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
            row.output_summary_json = _json({
                "run_envelope": build_run_envelope(
                    run_id=handle.run_id,
                    job_name=row.job_name,
                    trigger_source=row.trigger_source,
                    as_of=row.as_of,
                    started_at=row.started_at,
                    completed_at=finished,
                    row_status="error",
                    input_coverage=_read_json(row.input_coverage_json),
                    result={},
                    degradations=[str(error)[:500]],
                    artifact_path=artifact_path,
                    error=str(error),
                )
            })
        else:
            row.status = terminal_status(result)
            row.degradation_reasons_json = _json(_degradation_reasons(result))
            if row.as_of is None and isinstance(result, dict):
                row.as_of = str(result.get("as_of") or result.get("date") or "") or None
            row.artifact_path = _artifact_path(result, artifact_path)
            row.output_summary_json = _json(_output_payload(
                handle=handle,
                row=row,
                result=result,
                artifact_path=row.artifact_path,
                finished_at=finished,
            ))
            finalization = _attach_m63_daily_panel_artifact(db, row, result, artifact_path)
        if error is not None:
            finalization = None
        db.commit()
        _mark_m63_daily_panel_artifact_committed(finalization)
    except JobRunFinalizationError:
        db.rollback()
        logger.exception("job ledger finalization failed for %s", handle.run_id)
        raise
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
        "run_envelope": (
            parsed(row.output_summary_json, {}).get("run_envelope")
            or parsed(row.input_coverage_json, {}).get("run_envelope")
            or {}
        ),
        "artifact_path": row.artifact_path,
        "error": row.error,
        "runtime_version": row.runtime_version,
        "build_commit": row.build_commit,
        "db_role": row.db_role,
    }
