from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIMARY_DB_URL = f"sqlite:///{REPO_ROOT / 'mingcang.db'}"


def _envelope_json(
    *,
    run_id: str,
    job_name: str,
    as_of: str,
    batch_id: str | None = None,
    expected: int | None = 25,
    completed: int | None = 25,
    failed: int = 0,
    required_steps: list[str] | None = None,
    steps: list[dict] | None = None,
) -> str:
    from backend.ops.run_envelope import build_run_envelope

    coverage = {
        "expected_symbols": expected,
        "batch_id": batch_id or f"{job_name}:{as_of}",
        "required_steps": [] if required_steps is None else required_steps,
    }
    envelope = build_run_envelope(
        run_id=run_id,
        job_name=job_name,
        trigger_source="scheduler",
        as_of=as_of,
        row_status="success",
        input_coverage=coverage,
        result={
            "ok": True,
            "date": as_of,
            "batch_id": batch_id or f"{job_name}:{as_of}",
            "completed": completed,
            "failed": failed,
            "steps": steps or [],
        },
    )
    return json.dumps({"run_envelope": envelope}, ensure_ascii=False)


def test_runtime_identity_classifies_primary_and_demo_databases(tmp_path, monkeypatch):
    from backend.config import Settings
    from backend.runtime_identity import build_runtime_identity

    monkeypatch.setenv("MINGCANG_BUILD_COMMIT", "1234567890abcdef")
    primary = Settings(_env_file=None, database_url=PRIMARY_DB_URL, database_role="auto")
    demo = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'examples' / 'sample_db' / 'mingcang_demo.db'}",
        database_role="auto",
    )

    primary_identity = build_runtime_identity(primary, db_latest_date="2026-07-15")
    demo_identity = build_runtime_identity(demo, db_latest_date="2026-06-03")

    assert primary_identity["db_role"] == "primary"
    assert primary_identity["build_commit"] == "1234567890ab"
    assert primary_identity["db_latest_date"] == "2026-07-15"
    assert primary_identity["scheduler_mode"] == "manual"
    assert demo_identity["db_role"] == "demo"


def test_scheduler_persists_success_and_error_job_runs(tmp_path, monkeypatch):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun

    engine = create_engine(f"sqlite:///{tmp_path / 'job-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)

    assert scheduler.run_tracked_job(
        "ledger_success",
        lambda: {
            "ok": True,
            "date": "2026-07-15",
            "output_path": "m63_out/postmarket_2026-07-15.md",
        },
        trigger_source="manual_cli",
        input_coverage={"stocks": "25/25"},
    )["ok"] is True

    try:
        scheduler.run_tracked_job(
            "ledger_error",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    except RuntimeError:
        pass

    with Session() as db:
        success = db.query(JobRun).filter(JobRun.job_name == "ledger_success").one()
        failed = db.query(JobRun).filter(JobRun.job_name == "ledger_error").one()

        assert success.status == "success"
        assert success.as_of == "2026-07-15"
        assert success.artifact_path == "postmarket_2026-07-15.md"
        assert '"stocks": "25/25"' in (success.input_coverage_json or "")
        envelope = json.loads(success.output_summary_json or "{}")["run_envelope"]
        assert envelope["schema_version"] == "run_envelope.v1"
        assert envelope["entrypoint"] == "ledger_success"
        assert envelope["status"] == "complete"
        assert envelope["as_of"] == "2026-07-15"
        assert failed.status == "error"
        assert failed.error == "boom"
        failed_envelope = json.loads(failed.output_summary_json or "{}")["run_envelope"]
        assert failed_envelope["status"] == "failed"


def test_system_status_exposes_runtime_identity(test_db, monkeypatch):
    from backend.api.routes.system import system_status
    from backend.config import Settings
    from backend.data.database import Price

    monkeypatch.setattr("backend.llm.runtime_readiness", lambda settings: {"ready": True})
    monkeypatch.setattr("backend.scheduler.get_scheduler_state", lambda: {"jobs": {}})
    test_db.add(
        Price(
            symbol="600519",
            date="2026-07-15",
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
    )
    test_db.commit()

    isolated_settings = Settings(_env_file=None, database_url=PRIMARY_DB_URL, database_role="auto")
    payload = system_status(db=test_db, settings=isolated_settings)

    assert payload["version"]
    assert payload["build_commit"]
    assert payload["db_role"] == "primary"
    assert payload["db_latest_date"] == "2026-07-15"
    assert payload["scheduler_mode"] == "manual"


def test_system_health_exposes_persisted_workflow_freshness(test_db, monkeypatch):
    from datetime import UTC, datetime

    from backend.api.routes.system import system_health
    from backend.data.models.job import JobRun

    today = datetime.now(UTC).date().isoformat()
    test_db.add(JobRun(
        run_id="health-workflow-run",
        job_name="m63_postmarket",
        trigger_source="manual_cli",
        as_of=today,
        status="success",
        output_summary_json=_envelope_json(
            run_id="health-workflow-run",
            job_name="m63_postmarket",
            as_of=today,
        ),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.commit()
    monkeypatch.setattr("backend.ops.kill_switch.current_state", lambda: None)

    payload = system_health(db=test_db)

    assert payload["workflow_observability"]["observed"] is True
    assert payload["workflow_observability"]["fresh"] is True
    assert payload["workflow_observability"]["selector_status"] == "selected"
    assert payload["workflow_observability"]["latest"]["job_name"] == "m63_postmarket"
    assert payload["daily_bundle_observability"] is None


def test_system_health_fails_when_latest_signal_batch_lacks_job_run(test_db, monkeypatch):
    from datetime import UTC, datetime

    from backend.api.routes.system import system_health
    from backend.data.database import Signal
    from backend.data.models.job import JobRun

    today = datetime.now(UTC).date().isoformat()
    test_db.add(JobRun(
        run_id="old-workflow-run",
        job_name="m63_postmarket",
        trigger_source="manual_cli",
        as_of="2026-07-16",
        status="success",
        output_summary_json=_envelope_json(
            run_id="old-workflow-run",
            job_name="m63_postmarket",
            as_of="2026-07-16",
            batch_id="2026-07-16T22:00+08:00",
        ),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.add(Signal(
        symbol="600519",
        date=f"{today}T22:00+08:00",
        quant_score=0,
        technical_score=0,
        sentiment_score=0,
        composite_score=0,
        recommendation="观望",
        confidence="低",
        stop_loss=1,
        take_profit=1,
        data_timestamp=today,
    ))
    test_db.commit()
    monkeypatch.setattr("backend.ops.kill_switch.current_state", lambda: None)

    payload = system_health(db=test_db)

    assert payload["healthy"] is False
    assert payload["signal_batch_observability"]["observed"] is True
    assert payload["signal_batch_observability"]["latest"]["as_of"] == today
    assert payload["signal_batch_observability"]["latest_job_as_of"] == "2026-07-16"
    assert payload["signal_batch_observability"]["covered_by_job_run"] is False
    assert payload["signal_batch_observability"]["selector_status"] == "missing"


def test_run_envelope_fails_closed_on_partial_counts(tmp_path, monkeypatch):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun

    engine = create_engine(f"sqlite:///{tmp_path / 'partial-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)

    scheduler.run_tracked_job(
        "m63_postmarket",
        lambda: {"ok": True, "date": "2026-07-18", "processed": 24, "errors": 0},
        trigger_source="scheduler",
        as_of="2026-07-18",
        input_coverage={"expected_symbols": 25},
    )

    with Session() as db:
        row = db.query(JobRun).one()
        envelope = json.loads(row.output_summary_json or "{}")["run_envelope"]
        assert row.status == "success"
        assert envelope["status"] == "partial"
        from backend.ops.run_envelope import select_complete_daily_run

        assert select_complete_daily_run(db, as_of="2026-07-18")["status"] == "missing"


def test_complete_daily_selector_ignores_recent_non_daily_and_failed_runs(test_db):
    from datetime import UTC, datetime, timedelta

    from backend.api.routes.system import system_health
    from backend.data.models.job import JobRun

    now = datetime.now(UTC).replace(tzinfo=None)
    test_db.add(JobRun(
        run_id="complete-panel",
        job_name="m63_postmarket",
        trigger_source="scheduler",
        as_of=now.date().isoformat(),
        status="success",
        started_at=now - timedelta(minutes=10),
        output_summary_json=_envelope_json(
            run_id="complete-panel",
            job_name="m63_postmarket",
            as_of=now.date().isoformat(),
        ),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.add(JobRun(
        run_id="newer-maintenance",
        job_name="daily_memory_expire",
        trigger_source="scheduler",
        as_of=now.date().isoformat(),
        status="success",
        started_at=now,
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.add(JobRun(
        run_id="failed-panel",
        job_name="m63_postmarket",
        trigger_source="scheduler",
        as_of=(now.date() + timedelta(days=1)).isoformat(),
        status="error",
        started_at=now + timedelta(minutes=1),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.commit()

    payload = system_health(db=test_db)

    assert payload["workflow_observability"]["selector_status"] == "selected"
    assert payload["workflow_observability"]["latest"]["run_id"] == "complete-panel"


def test_complete_daily_selector_rejects_duplicate_complete_postmarket(test_db):
    from datetime import UTC, datetime, timedelta

    from backend.data.models.job import JobRun
    from backend.ops.run_envelope import select_complete_daily_run

    today = datetime.now(UTC).date().isoformat()
    for index in range(2):
        test_db.add(JobRun(
            run_id=f"duplicate-{index}",
            job_name="m63_postmarket",
            trigger_source="manual_cli" if index else "scheduler",
            as_of=today,
            status="success",
            started_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=index),
            output_summary_json=_envelope_json(
                run_id=f"duplicate-{index}",
                job_name="m63_postmarket",
                as_of=today,
            ),
            runtime_version="0.7.1",
            build_commit="test",
            db_role="primary",
        ))
    test_db.commit()

    result = select_complete_daily_run(test_db, as_of=today)

    assert result["status"] == "ambiguous"
    assert sorted(result["run_ids"]) == ["duplicate-0", "duplicate-1"]


def test_complete_daily_selector_rejects_legacy_rows_without_explicit_envelope(test_db):
    from datetime import UTC, datetime

    from backend.data.models.job import JobRun
    from backend.ops.run_envelope import select_complete_daily_run

    today = datetime.now(UTC).date().isoformat()
    test_db.add(JobRun(
        run_id="legacy-success",
        job_name="m63_postmarket",
        trigger_source="scheduler",
        as_of=today,
        status="success",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.commit()

    assert select_complete_daily_run(test_db, as_of=today)["status"] == "missing"


def test_optional_degradation_does_not_make_complete_core_partial(tmp_path, monkeypatch):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun

    engine = create_engine(f"sqlite:///{tmp_path / 'degraded-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)

    scheduler.run_tracked_job(
        "m63_postmarket",
        lambda: {
            "ok": True,
            "date": "2026-07-18",
            "completed": 25,
            "failed": 0,
            "degradation_reasons": ["--no-llm: optional discretion skipped"],
            "steps": [
                {"name": "m59_panel", "ok": True, "result": {}},
                {"name": "trigger_router", "ok": True, "result": {}},
                {"name": "task_capsule", "ok": True, "result": {}},
                {"name": "m68_news_shadow", "ok": True, "result": {"skipped": True, "reason": "--no-llm"}},
            ],
        },
        trigger_source="manual_cli",
        as_of="2026-07-18",
        input_coverage={"expected_symbols": 25, "required_steps": ["m59_panel", "trigger_router", "task_capsule"]},
    )

    with Session() as db:
        row = db.query(JobRun).one()
        envelope = json.loads(row.output_summary_json or "{}")["run_envelope"]
        assert row.status == "success"
        assert envelope["status"] == "complete"
        assert envelope["degradations"]


def test_system_signal_batch_requires_matching_complete_envelope_batch(test_db, monkeypatch):
    from backend.api.routes.system import system_health
    from backend.data.database import Signal
    from backend.data.models.job import JobRun

    batch_id = "2026-07-18T22:00+08:00"
    test_db.add(Signal(
        symbol="600519",
        date=batch_id,
        quant_score=0,
        technical_score=0,
        sentiment_score=0,
        composite_score=0,
        recommendation="观望",
        confidence="低",
        stop_loss=1,
        take_profit=1,
        data_timestamp="2026-07-18",
    ))
    test_db.add(JobRun(
        run_id="signal-batch-run",
        job_name="test2_signal_runner",
        trigger_source="manual_cli",
        as_of="2026-07-18",
        status="success",
        output_summary_json=_envelope_json(
            run_id="signal-batch-run",
            job_name="test2_signal_runner",
            as_of="2026-07-18",
            batch_id=batch_id,
            expected=1,
            completed=1,
        ),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.commit()
    monkeypatch.setattr("backend.ops.kill_switch.current_state", lambda: None)

    payload = system_health(db=test_db)

    assert payload["signal_batch_observability"]["covered_by_job_run"] is True
    assert payload["signal_batch_observability"]["selector_status"] == "selected"
    assert payload["signal_batch_observability"]["run_id"] == "signal-batch-run"


def test_system_signal_batch_ignores_non_signal_producing_matching_batch(test_db, monkeypatch):
    from backend.api.routes.system import system_health
    from backend.data.database import Signal
    from backend.data.models.job import JobRun

    batch_id = "2026-07-18T22:00+08:00"
    test_db.add(Signal(
        symbol="600519",
        date=batch_id,
        quant_score=0,
        technical_score=0,
        sentiment_score=0,
        composite_score=0,
        recommendation="观望",
        confidence="低",
        stop_loss=1,
        take_profit=1,
        data_timestamp="2026-07-18",
    ))
    test_db.add(JobRun(
        run_id="random-matching-run",
        job_name="random_audit_job",
        trigger_source="manual_cli",
        as_of="2026-07-18",
        status="success",
        output_summary_json=_envelope_json(
            run_id="random-matching-run",
            job_name="random_audit_job",
            as_of="2026-07-18",
            batch_id=batch_id,
            expected=1,
            completed=1,
        ),
        runtime_version="0.7.1",
        build_commit="test",
        db_role="primary",
    ))
    test_db.commit()
    monkeypatch.setattr("backend.ops.kill_switch.current_state", lambda: None)

    payload = system_health(db=test_db)

    assert payload["healthy"] is False
    assert payload["signal_batch_observability"]["covered_by_job_run"] is False
    assert payload["signal_batch_observability"]["selector_status"] == "missing"
    assert payload["signal_batch_observability"]["run_id"] is None


def test_daily_bundle_allows_multiple_required_phases(test_db):
    from datetime import UTC, datetime, timedelta

    from backend.data.models.job import JobRun
    from backend.ops.run_envelope import evaluate_daily_bundle, select_complete_daily_run

    today = datetime.now(UTC).date().isoformat()
    for index, phase in enumerate(("m63_premarket", "m63_intraday", "m63_postmarket")):
        test_db.add(JobRun(
            run_id=phase,
            job_name=phase,
            trigger_source="scheduler",
            as_of=today,
            status="success",
            started_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=index),
            output_summary_json=_envelope_json(
                run_id=phase,
                job_name=phase,
                as_of=today,
            ),
            runtime_version="0.7.1",
            build_commit="test",
            db_role="primary",
        ))
    test_db.commit()

    assert select_complete_daily_run(test_db, as_of=today)["status"] == "selected"
    bundle = evaluate_daily_bundle(test_db, as_of=today)
    assert bundle["status"] == "complete"
    assert bundle["completed_phases"] == ["m63_intraday", "m63_postmarket", "m63_premarket"]


def test_m63_daily_manual_cli_persists_configured_contract_and_keeps_custom_untracked(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.evidence import daily_panel
    from backend.workflows import m63_daily

    engine = create_engine(f"sqlite:///{tmp_path / 'm63-daily-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    queue_path = tmp_path / "m63_queue.json"
    queue_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(m63_daily, "DEFAULT_QUEUE_PATH", queue_path)
    monkeypatch.setattr(
        daily_panel,
        "build_postmarket_panel",
        lambda *args, **kwargs: {
            "schema_version": "postmarket_panel.v1",
            "header": {"as_of": "2026-07-18"},
            "buy_candidates": {"items": [], "vetoed_items": []},
            "position_health": {"items": []},
            "risk_warnings": {"concentration": {}, "stop_loss_buffer_ranking": {}},
            "watchtower_followups": {"items": []},
            "watchtower_confirm": {"items": []},
            "review_attribution": {"note": "test"},
            "daily_delta": {
                "current_as_of": "2026-07-18",
                "previous_as_of": "2026-07-17",
                "summary": "no change",
            },
        },
    )
    monkeypatch.setattr(
        daily_panel,
        "build_news_event_risk_from_db",
        lambda *args, **kwargs: {
            "schema_version": "news_event_risk_facade.v1",
            "as_of": "2026-07-18",
            "status": "ready",
            "event_risk_cards": [],
            "panel_payload": {"total": 0, "attention_count": 0, "attention": []},
            "direction_experiment": {"lifecycle": "shadow", "status": "blocked"},
            "degradation_flags": [],
        },
    )

    custom_db = tmp_path / "custom-source.db"
    seen_db_paths: list[object] = []

    def _report(mode: str, **kwargs):
        seen_db_paths.append(kwargs.get("db_path"))
        payload = {"ok": True, "mode": mode, "date": "2026-07-18", "text": f"{mode} report"}
        if mode == "postmarket":
            payload["steps"] = [
                {"name": "m59_panel", "ok": True, "result": {}},
                {"name": "trigger_router", "ok": True, "result": {}},
                {"name": "task_capsule", "ok": True, "result": {}},
            ]
        return payload

    monkeypatch.setattr(m63_daily, "build_premarket_report", lambda **kwargs: _report("premarket", **kwargs))
    monkeypatch.setattr(m63_daily, "build_intraday_report", lambda **kwargs: _report("intraday", **kwargs))
    monkeypatch.setattr(m63_daily, "build_postmarket_report", lambda **kwargs: _report("postmarket", **kwargs))
    def _write_report(mode: str, as_of: str, text: str):
        path = tmp_path / f"{mode}_{as_of}.md"
        path.write_text(text, encoding="utf-8")
        return path

    monkeypatch.setattr(m63_daily, "write_report", _write_report)

    for mode in ("premarket", "intraday", "postmarket"):
        assert m63_daily.main(["--mode", mode]) == 0

    assert seen_db_paths == [None, None, None]
    with Session() as db:
        rows = db.query(JobRun).order_by(JobRun.id).all()
        assert [row.job_name for row in rows] == ["m63_premarket", "m63_intraday", "m63_postmarket"]
        for row in rows:
            envelope = json.loads(row.output_summary_json or "{}")["run_envelope"]
            assert row.as_of == "2026-07-18"
            assert envelope["schema_version"] == "run_envelope.v1"
            assert envelope["as_of"] == "2026-07-18"
            assert envelope["status"] == "complete"
            assert envelope["trigger_source"] == "manual_cli"
            assert envelope["freshness"]["input_coverage"]["database"] == "configured"

    for mode in ("premarket", "intraday", "postmarket"):
        assert m63_daily.main(["--mode", mode, "--db", str(custom_db)]) == 0

    assert seen_db_paths == [None, None, None, custom_db, custom_db, custom_db]
    with Session() as db:
        assert db.query(JobRun).count() == 3


def test_m63_weekly_manual_cli_persists_configured_m63_weekend_and_keeps_custom_untracked(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.tools import m63_weekly

    engine = create_engine(f"sqlite:///{tmp_path / 'm63-weekend-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    seen_db_paths: list[object] = []

    def _weekly(**kwargs):
        seen_db_paths.append(kwargs.get("db_path"))
        return {
            "ok": True,
            "date": "2026-07-19",
            "as_of": "2026-07-19",
            "output_path": str(tmp_path / "weekly_2026-07-19.md"),
        }

    monkeypatch.setattr(m63_weekly, "run_weekly", _weekly)

    assert m63_weekly.main(["--as-of", "2026-07-19", "--no-llm"]) == 0

    with Session() as db:
        row = db.query(JobRun).one()
        envelope = json.loads(row.output_summary_json or "{}")["run_envelope"]
        assert row.job_name == "m63_weekend"
        assert row.as_of == "2026-07-19"
        assert envelope["status"] == "complete"
        assert envelope["batch_id"] == "m63_weekend:2026-07-19"
        assert envelope["freshness"]["input_coverage"]["database"] == "configured"

    assert m63_weekly.main(["--as-of", "2026-07-19", "--db", str(tmp_path / "custom.db"), "--no-llm"]) == 0
    assert seen_db_paths == [None, tmp_path / "custom.db"]
    with Session() as db:
        assert db.query(JobRun).count() == 1


def test_test2_signal_runner_main_persists_batch_timestamp_and_stale_partial(tmp_path, monkeypatch):
    import sys

    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from paper_trading import test2_signal_runner as runner

    engine = create_engine(f"sqlite:///{tmp_path / 'test2-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    monkeypatch.setattr(runner, "_load_universe", lambda path=runner.DEFAULT_UNIVERSE: {"AAA": "A", "BBB": "B"})
    monkeypatch.setattr(runner, "_run_m68_shadow_followup", lambda *args, **kwargs: {"skipped": True, "reason": "test"})

    batches = iter([
        (
            [
                {"symbol": "AAA", "name": "A", "date": "2026-07-18T22:00+08:00", "data_date": "2026-07-18", "composite_score": 1, "recommendation": "观望", "quant_score": 1, "technical_score": 0, "sentiment_score": 0, "stop_loss": 1, "take_profit": 2},
                {"symbol": "BBB", "name": "B", "date": "2026-07-18T22:00+08:00", "data_date": "2026-07-18", "composite_score": 1, "recommendation": "观望", "quant_score": 1, "technical_score": 0, "sentiment_score": 0, "stop_loss": 1, "take_profit": 2},
            ],
            {"universe": 2, "processed": 2, "skipped": 0, "errors": 0, "missing": 0, "stale_skipped": 0},
        ),
        (
            [
                {"symbol": "AAA", "name": "A", "date": "2026-07-19T22:00+08:00", "data_date": "2026-07-19", "composite_score": 1, "recommendation": "观望", "quant_score": 1, "technical_score": 0, "sentiment_score": 0, "stop_loss": 1, "take_profit": 2},
            ],
            {"universe": 2, "processed": 1, "skipped": 0, "errors": 0, "missing": 0, "stale_skipped": 1},
        ),
        (
            [
                {"symbol": "AAA", "name": "A", "date": "2026-07-20T22:00+08:00", "data_date": "2026-07-20", "composite_score": 1, "recommendation": "观望", "quant_score": 1, "technical_score": 0, "sentiment_score": 0, "stop_loss": 1, "take_profit": 2},
                {"symbol": "BBB", "name": "B", "date": "2026-07-20T22:00+08:00", "data_date": "2026-07-20", "composite_score": 1, "recommendation": "观望", "quant_score": 1, "technical_score": 0, "sentiment_score": 0, "stop_loss": 1, "take_profit": 2},
            ],
            {"universe": 2, "processed": 2, "skipped": 0, "errors": 0, "missing": 0, "stale_skipped": 0},
        ),
    ])
    monkeypatch.setattr(runner, "run", lambda *args, **kwargs: next(batches))

    monkeypatch.setattr(sys, "argv", ["test2_signal_runner.py", "--no-llm", "--no-shadow", "--workers", "1"])
    runner.main()
    monkeypatch.setattr(sys, "argv", ["test2_signal_runner.py", "--no-llm", "--no-shadow", "--workers", "1"])
    runner.main()
    custom_universe = tmp_path / "custom-universe.json"
    custom_universe.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["test2_signal_runner.py", "--no-llm", "--no-shadow", "--workers", "1", "--universe", str(custom_universe)])
    runner.main()

    with Session() as db:
        rows = db.query(JobRun).order_by(JobRun.id).all()
        envelopes = [json.loads(row.output_summary_json or "{}")["run_envelope"] for row in rows]
        assert [row.job_name for row in rows] == ["test2_signal_runner", "test2_signal_runner", "test2_signal_runner"]
        assert envelopes[0]["batch_id"] == "2026-07-18T22:00+08:00"
        assert envelopes[0]["as_of"] == "2026-07-18"
        assert envelopes[0]["status"] == "complete"
        assert envelopes[0]["completed"]["symbols"] == 2
        assert envelopes[1]["batch_id"] == "2026-07-19T22:00+08:00"
        assert envelopes[1]["status"] == "partial"
        assert envelopes[1]["failed"]["symbols"] == 1
        assert envelopes[2]["batch_id"] == "2026-07-20T22:00+08:00"
        assert envelopes[2]["status"] == "complete"
        assert envelopes[2]["freshness"]["input_coverage"]["authoritative"] is False
        from backend.ops.run_envelope import select_complete_run_for_batch

        assert select_complete_run_for_batch(
            db,
            as_of="2026-07-20",
            batch_id="2026-07-20T22:00+08:00",
            min_symbols=2,
        )["status"] == "missing"


def test_proposal_gate_contract_is_simulation_only():
    from backend.ops.run_envelope import build_proposal_gate_contract

    contract = build_proposal_gate_contract(
        proposal_id="proposal-1",
        as_of="2026-07-18",
        proposal={"action": "candidate_review"},
        revalidation={"ok": True},
        gate={"ok": True},
        audit={"ok": True},
    )

    assert contract["schema_version"] == "proposal_gate_contract.v1"
    assert contract["status"] == "complete"
    assert contract["simulation_only"] is True
    assert contract["broker_connection"] == "forbidden"


def test_pre_close_run_does_not_make_a_close_confirmed_rerun_ambiguous(test_db):
    """Re-running postmarket after the close must not fail as a duplicate.

    Regression cover for 2026-08-19: a postmarket run executed mid-session took
    the day's only authoritative slot, and the correct post-close rerun then
    died with `run_selection_ambiguous`, permanently burning the day.
    """
    from datetime import UTC, datetime, timedelta

    from backend.data.models.job import JobRun
    from backend.ops.run_envelope import select_complete_daily_run

    today = datetime.now(UTC).date().isoformat()

    def _row(run_id: str, minutes: int, close_confirmed: bool) -> JobRun:
        envelope = json.loads(_envelope_json(run_id=run_id, job_name="m63_postmarket", as_of=today))
        envelope["run_envelope"]["freshness"]["close_confirmed"] = close_confirmed
        return JobRun(
            run_id=run_id,
            job_name="m63_postmarket",
            trigger_source="manual_cli",
            as_of=today,
            status="success",
            started_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=minutes),
            output_summary_json=json.dumps(envelope),
            runtime_version="0.7.1",
            build_commit="test",
            db_role="primary",
        )

    test_db.add(_row("pre-close", 0, False))
    test_db.commit()
    assert select_complete_daily_run(test_db, as_of=today, job_names=("m63_postmarket",))["status"] == "missing"

    test_db.add(_row("post-close", 5, True))
    test_db.commit()

    selection = select_complete_daily_run(test_db, as_of=today, job_names=("m63_postmarket",))
    assert selection["status"] == "selected"
    assert selection["job_run"].run_id == "post-close"


def test_two_close_confirmed_runs_on_one_day_still_fail_closed(test_db):
    from datetime import UTC, datetime, timedelta

    from backend.data.models.job import JobRun
    from backend.ops.run_envelope import select_complete_daily_run

    today = datetime.now(UTC).date().isoformat()
    for index, run_id in enumerate(("first", "second")):
        test_db.add(JobRun(
            run_id=run_id,
            job_name="m63_postmarket",
            trigger_source="manual_cli",
            as_of=today,
            status="success",
            started_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=index),
            output_summary_json=_envelope_json(run_id=run_id, job_name="m63_postmarket", as_of=today),
            runtime_version="0.7.1",
            build_commit="test",
            db_role="primary",
        ))
    test_db.commit()

    assert select_complete_daily_run(test_db, as_of=today, job_names=("m63_postmarket",))["status"] == "ambiguous"
