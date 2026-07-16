from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_runtime_identity_classifies_primary_and_demo_databases(tmp_path, monkeypatch):
    from backend.config import Settings
    from backend.runtime_identity import build_runtime_identity

    monkeypatch.setenv("MINGCANG_BUILD_COMMIT", "1234567890abcdef")
    primary = Settings(_env_file=None)
    demo = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'examples' / 'sample_db' / 'mingcang_demo.db'}",
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
        assert failed.status == "error"
        assert failed.error == "boom"


def test_system_status_exposes_runtime_identity(test_db, monkeypatch):
    from backend.api.deps import get_settings
    from backend.api.routes.system import system_status
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

    payload = system_status(db=test_db, settings=get_settings())

    assert payload["version"]
    assert payload["build_commit"]
    assert payload["db_role"] == "primary"
    assert payload["db_latest_date"] == "2026-07-15"
    assert payload["scheduler_mode"] == "manual"
