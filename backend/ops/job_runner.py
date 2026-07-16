"""Execution wrapper that keeps scheduler facade state aligned with the job ledger."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.ops.job_ledger import (
    finish_job_run,
    start_job_run,
    terminal_status,
)


def execute_tracked_job(
    state: dict[str, Any],
    job_name: str,
    fn: Callable[[], Any],
    *,
    trigger_source: str,
    as_of: str | None,
    input_coverage: dict[str, Any] | None,
    artifact_path: str | Path | None,
) -> Any:
    """Execute a job and update both volatile and persistent operational state."""
    started = datetime.now(UTC)
    ledger_handle = start_job_run(
        job_name,
        trigger_source=trigger_source,
        as_of=as_of,
        input_coverage=input_coverage,
    )
    state.update({
        "running": True,
        "last_status": "running",
        "last_started_at": started.isoformat(),
        "last_finished_at": None,
        "last_duration_seconds": None,
        "last_error": None,
    })
    try:
        result = fn()
        finished = datetime.now(UTC)
        state.update({
            "running": False,
            "last_status": terminal_status(result),
            "last_finished_at": finished.isoformat(),
            "last_duration_seconds": round((finished - started).total_seconds(), 3),
            "last_result": result,
            "success_count": state.get("success_count", 0) + 1,
        })
        finish_job_run(ledger_handle, result=result, artifact_path=artifact_path)
        return result
    except Exception as exc:
        finished = datetime.now(UTC)
        state.update({
            "running": False,
            "last_status": "error",
            "last_finished_at": finished.isoformat(),
            "last_duration_seconds": round((finished - started).total_seconds(), 3),
            "last_error": str(exc),
            "error_count": state.get("error_count", 0) + 1,
        })
        finish_job_run(ledger_handle, error=exc, artifact_path=artifact_path)
        raise
