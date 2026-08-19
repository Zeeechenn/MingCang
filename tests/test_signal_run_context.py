"""Official signals must be attributable to the tracked run that produced them.

Regression cover for the ledger gap found on 2026-08-19: production signal rows
existed for 2026-07-20, 2026-07-24 and 2026-08-18 while `job_runs` held nothing
newer than a 2026-07-16 smoke row, so every close-confirmed day failed the
One Loop continuity audit with `missing_authoritative_signal_run`.
"""
from __future__ import annotations

import pytest

RESULT = {
    "breakdown": {"quant": 10.0, "technical": 20.0, "sentiment": 5.0},
    "composite_score": 15.0,
    "recommendation": "观望",
    "confidence": "中",
    "stop_loss": 9.5,
    "take_profit": 11.5,
}


def _signal(db, symbol: str = "600519"):
    from backend.data.database import Signal

    return db.query(Signal).filter(Signal.symbol == symbol).one()


def test_signal_written_inside_tracked_run_carries_the_run_id(test_db):
    from backend.decision.aggregator import save_signal
    from backend.ops.run_context import RunContext, bind_run_context

    context = RunContext(
        run_id="run-abc123",
        job_name="postmarket",
        trigger_source="scheduler",
        as_of="2026-08-19",
    )
    with bind_run_context(context):
        save_signal("600519", "2026-08-19", dict(RESULT), test_db)

    assert _signal(test_db).run_id == "run-abc123"


def test_rerun_inside_a_second_tracked_run_rebinds_the_row(test_db):
    from backend.decision.aggregator import save_signal
    from backend.ops.run_context import RunContext, bind_run_context

    for run_id in ("run-first", "run-second"):
        context = RunContext(run_id=run_id, job_name="postmarket", trigger_source="scheduler")
        with bind_run_context(context):
            save_signal("600519", "2026-08-19", dict(RESULT), test_db)

    assert _signal(test_db).run_id == "run-second"


def test_untracked_official_write_is_recorded_as_a_degradation(test_db, caplog):
    import backend.decision.aggregator as aggregator
    from backend.data.models.degradation import DegradationEvent

    aggregator._UNTRACKED_WRITE_WARNED.clear()
    with caplog.at_level("WARNING"):
        aggregator.save_signal("600519", "2026-08-19", dict(RESULT), test_db)

    assert _signal(test_db).run_id is None
    events = test_db.query(DegradationEvent).filter(
        DegradationEvent.category == "untracked_signal_write"
    ).all()
    assert len(events) == 1
    assert "2026-08-19" in caplog.text


def test_untracked_official_write_fails_closed_when_the_guard_is_on(test_db, monkeypatch):
    import backend.decision.aggregator as aggregator
    from backend.config import settings
    from backend.data.database import Signal

    monkeypatch.setattr(settings, "require_signal_run_context", True)
    with pytest.raises(aggregator.UntrackedSignalWriteError):
        aggregator.save_signal("600519", "2026-08-19", dict(RESULT), test_db)

    assert test_db.query(Signal).count() == 0


def test_best_effort_ledger_failure_does_not_stamp_an_unresolvable_run_id(test_db):
    """A ledger row that never persisted must not lend its id to official output."""
    from backend.decision.aggregator import save_signal
    from backend.ops.run_context import RunContext, bind_run_context

    context = RunContext(
        run_id="run-not-persisted",
        job_name="postmarket",
        trigger_source="scheduler",
        persisted=False,
    )
    with bind_run_context(context):
        save_signal("600519", "2026-08-19", dict(RESULT), test_db)

    assert _signal(test_db).run_id is None


def test_tracked_job_binds_the_ledger_run_id_for_the_whole_call(monkeypatch):
    """The ledger handle and the ambient context must name the same run."""
    from backend.config import settings
    from backend.ops import job_ledger, job_runner
    from backend.ops.run_context import current_run_id

    monkeypatch.setattr(settings, "job_ledger_enabled", False)
    seen: dict[str, str | None] = {}

    def _work() -> dict:
        seen["run_id"] = current_run_id()
        return {"ok": True}

    monkeypatch.setattr(
        job_ledger,
        "start_job_run",
        lambda *a, **k: job_ledger.JobRunHandle(run_id="run-xyz", persisted=True),
    )
    monkeypatch.setattr(job_runner, "start_job_run", job_ledger.start_job_run)
    monkeypatch.setattr(job_runner, "finish_job_run", lambda *a, **k: None)

    job_runner.execute_tracked_job(
        {},
        "postmarket",
        _work,
        trigger_source="scheduler",
        as_of="2026-08-19",
        input_coverage=None,
        artifact_path=None,
    )

    assert seen["run_id"] == "run-xyz"
    assert current_run_id() is None


def test_legacy_database_without_the_column_self_heals_on_write(test_db):
    """The daily entrypoints never call init_db, so the write path must repair itself."""
    from sqlalchemy import text

    import backend.data.schema_runtime as schema_runtime
    from backend.decision.aggregator import save_signal
    from backend.ops.run_context import RunContext, bind_run_context

    test_db.execute(text("DROP INDEX IF EXISTS ix_signals_run_id"))
    test_db.execute(text("ALTER TABLE signals DROP COLUMN run_id"))
    test_db.commit()
    schema_runtime._SIGNALS_RUN_ID_ENSURED.clear()
    assert "run_id" not in {
        row[1] for row in test_db.execute(text("PRAGMA table_info(signals)")).fetchall()
    }

    context = RunContext(run_id="run-legacy", job_name="postmarket", trigger_source="manual_cli")
    with bind_run_context(context):
        save_signal("600519", "2026-08-19", dict(RESULT), test_db)

    assert _signal(test_db).run_id == "run-legacy"
