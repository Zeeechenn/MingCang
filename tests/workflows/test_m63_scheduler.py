"""M63 scheduler adapter tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _complete_steps() -> list[dict]:
    return [
        {"name": "m59_panel", "ok": True, "result": {}},
        {"name": "trigger_router", "ok": True, "result": {"pending": []}},
        {"name": "task_capsule", "ok": True, "result": {"capsule_id": "m63_postmarket:2026-08-18"}},
    ]


def _panel_payload(as_of: str) -> dict:
    return {
        "schema_version": "postmarket_panel.v1",
        "header": {"as_of": as_of},
        "buy_candidates": {"items": [], "vetoed_items": []},
        "position_health": {"items": []},
        "risk_warnings": {"concentration": {}, "stop_loss_buffer_ranking": {}},
        "watchtower_followups": {"items": []},
        "watchtower_confirm": {"items": []},
        "review_attribution": {"note": "test"},
        "daily_delta": {
            "current_as_of": as_of,
            "previous_as_of": "2026-08-17",
            "summary": "no change",
        },
    }


def _news_payload(as_of: str) -> dict:
    return {
        "schema_version": "news_event_risk_facade.v1",
        "as_of": as_of,
        "status": "ready",
        "event_risk_cards": [],
        "panel_payload": {"total": 0, "attention_count": 0, "attention": []},
        "direction_experiment": {
            "lifecycle": "shadow",
            "status": "blocked",
            "direction_weights_allowed": False,
        },
        "degradation_flags": [],
    }


def _write_queue(path: Path, rows: list[dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows or [], ensure_ascii=False), encoding="utf-8")


def test_m63_postmarket_job_writes_daily_report(monkeypatch, tmp_path):
    from backend import scheduler
    from backend.tools import m63_daily

    monkeypatch.setattr(
        m63_daily,
        "build_postmarket_report",
        lambda: {"ok": True, "mode": "postmarket", "date": "2026-07-14", "text": "report"},
    )
    monkeypatch.setattr(
        m63_daily,
        "write_report",
        lambda mode, as_of, text: tmp_path / f"{mode}_{as_of}.md",
    )

    result = scheduler.job_m63_postmarket()

    assert result["ok"] is True
    assert result["output_path"].endswith("postmarket_2026-07-14.md")


def test_m63_postmarket_job_respects_kill_switch(monkeypatch):
    from backend import scheduler
    from backend.tools import m63_daily

    monkeypatch.setattr(scheduler, "_kill_switch_guard", lambda _job: True)
    monkeypatch.setattr(
        m63_daily,
        "build_postmarket_report",
        lambda: (_ for _ in ()).throw(AssertionError("M63 must not run while blocked")),
    )

    assert scheduler.job_m63_postmarket() == {"skipped": "kill_switch"}


def test_scheduler_registers_m63_as_a_separate_postmarket_job(monkeypatch):
    from backend import scheduler

    class FakeScheduler:
        running = False

        def __init__(self):
            self.jobs = []

        def add_job(self, fn, trigger, *, id, replace_existing):
            self.jobs.append((fn, trigger, id, replace_existing))

        def start(self):
            self.running = True

    fake = FakeScheduler()
    monkeypatch.setattr(scheduler, "scheduler", fake)
    monkeypatch.setattr(scheduler.settings, "m63_daily_enabled", True)
    monkeypatch.setattr(scheduler.settings, "schedule_m63_postmarket", "17:30")

    scheduler.start()

    ids = [item[2] for item in fake.jobs]
    assert "postmarket" in ids
    assert "m63_postmarket" in ids


def test_m63_scheduler_tracked_run_writes_canonical_daily_panel_artifact(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta

    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.evidence import daily_panel
    from backend.workflows import m63_daily

    engine = create_engine(f"sqlite:///{tmp_path / 'job-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    queue_path = tmp_path / "m63_queue.json"
    _write_queue(queue_path, [{"id": "done-1", "status": "done", "created_at": "2026-08-18", "done_at": "2026-08-18"}])
    monkeypatch.setattr(m63_daily, "DEFAULT_QUEUE_PATH", queue_path)
    monkeypatch.setattr(daily_panel, "build_postmarket_panel", lambda *args, **kwargs: _panel_payload("2026-08-18"))
    monkeypatch.setattr(daily_panel, "build_news_event_risk_from_db", lambda *args, **kwargs: _news_payload("2026-08-18"))
    monkeypatch.setattr(
        m63_daily,
        "build_postmarket_report",
        lambda: {
            "ok": True,
            "mode": "postmarket",
            "date": "2026-08-18",
            "text": "report",
            "completed": 3,
            "failed": 0,
            "steps": _complete_steps(),
            "router": {"pending": []},
        },
    )

    def write_report(mode: str, as_of: str, text: str) -> Path:
        path = tmp_path / "m63_out" / f"{mode}_{as_of}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    monkeypatch.setattr(m63_daily, "write_report", write_report)
    with Session() as db:
        now = datetime.now(UTC).replace(tzinfo=None)
        db.add(JobRun(
            run_id="failed-before-success",
            job_name="m63_postmarket",
            trigger_source="scheduler",
            as_of="2026-08-18",
            status="error",
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=4),
            runtime_version="0.7.1",
            build_commit="test",
            db_role="primary",
        ))
        db.commit()

    result = scheduler.job_m63_postmarket()

    assert result["ok"] is True
    with Session() as db:
        row = db.query(JobRun).filter(JobRun.status == "success").one()
        assert row.status == "success"
        panel_path = Path(row.artifact_path or "")
        assert panel_path.name == "postmarket_2026-08-18.daily_panel.json"
        assert panel_path.exists()
        output = json.loads(row.output_summary_json or "{}")
        envelope = output["run_envelope"]
        artifact = json.loads(panel_path.read_text(encoding="utf-8"))

        assert artifact["run_envelope"]["run_id"] == row.run_id
        assert artifact["cards"][0]["run_ref"]["run_id"] == row.run_id

    assert artifact["schema_version"] == "daily_panel.v1"
    assert artifact["ledger_commit_state"] == "committed"
    assert artifact["run_envelope"] == envelope
    assert artifact["artifact_contract"]["no_synthetic_envelope"] is True
    assert artifact["work_metrics"]["duplicate_suppression"]["status"] == "available"
    assert artifact["work_metrics"]["human_review"]["status"] == "available"
    assert artifact["work_metrics"]["human_review"]["required"] == 1
    assert artifact["work_metrics"]["human_review"]["completed"] == 1
    assert artifact["work_metrics"]["human_review"]["source"] == str(queue_path)
    assert artifact["work_metrics"]["failure_recovery"] == {
        "status": "available",
        "recovered": 1,
        "open_failures": 0,
        "evidence": "same_day_prior_failed_or_degraded_m63_job_runs",
    }
    assert any(item.endswith("postmarket_2026-08-18.md") for item in envelope["artifacts"])
    assert any(item.endswith("postmarket_2026-08-18.daily_panel.json") for item in envelope["artifacts"])


def test_m63_manual_cli_tracked_default_db_also_writes_daily_panel_artifact(monkeypatch, tmp_path):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.evidence import daily_panel
    from backend.workflows import m63_daily

    engine = create_engine(f"sqlite:///{tmp_path / 'manual-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    queue_path = tmp_path / "m63_queue.json"
    _write_queue(queue_path)
    monkeypatch.setattr(m63_daily, "DEFAULT_QUEUE_PATH", queue_path)
    monkeypatch.setattr(daily_panel, "build_postmarket_panel", lambda *args, **kwargs: _panel_payload("2026-08-18"))
    monkeypatch.setattr(daily_panel, "build_news_event_risk_from_db", lambda *args, **kwargs: _news_payload("2026-08-18"))
    markdown_path = tmp_path / "postmarket_2026-08-18.md"
    markdown_path.write_text("report", encoding="utf-8")

    scheduler.run_tracked_job(
        "m63_postmarket",
        lambda: {
            "ok": True,
            "mode": "postmarket",
            "date": "2026-08-18",
            "output_path": str(markdown_path),
            "completed": 3,
            "failed": 0,
            "steps": _complete_steps(),
        },
        trigger_source="manual_cli",
        as_of="2026-08-18",
        input_coverage={
            "workflow": "m63_daily",
            "mode": "postmarket",
            "required_steps": ["m59_panel", "trigger_router", "task_capsule"],
        },
    )

    with Session() as db:
        row = db.query(JobRun).one()
        assert row.status == "success"
        panel_path = Path(row.artifact_path or "")
        assert panel_path.name == "postmarket_2026-08-18.daily_panel.json"
        artifact = json.loads(panel_path.read_text(encoding="utf-8"))
        assert artifact["ledger_commit_state"] == "committed"


def test_m63_scheduler_custom_db_tracking_skips_daily_panel_artifact(monkeypatch, tmp_path):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun

    engine = create_engine(f"sqlite:///{tmp_path / 'custom-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    markdown_path = tmp_path / "postmarket_2026-08-18.md"
    markdown_path.write_text("report", encoding="utf-8")

    scheduler.run_tracked_job(
        "m63_postmarket",
        lambda: {
            "ok": True,
            "date": "2026-08-18",
            "output_path": str(markdown_path),
            "completed": 3,
            "failed": 0,
            "steps": _complete_steps(),
        },
        trigger_source="scheduler",
        as_of="2026-08-18",
        input_coverage={
            "workflow": "m63_daily",
            "mode": "postmarket",
            "database": "custom",
            "required_steps": ["m59_panel", "trigger_router", "task_capsule"],
        },
    )

    with Session() as db:
        row = db.query(JobRun).one()
        envelope = json.loads(row.output_summary_json or "{}")["run_envelope"]

        assert row.status == "success"
        assert row.artifact_path == "postmarket_2026-08-18.md"
        assert envelope["status"] == "complete"
        assert envelope["artifacts"] == ["postmarket_2026-08-18.md"]
    assert not (tmp_path / "postmarket_2026-08-18.daily_panel.json").exists()


def test_m63_panel_artifact_finalization_fails_closed_when_work_metrics_unavailable(monkeypatch, tmp_path):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.evidence import daily_panel
    from backend.ops.job_ledger import JobRunFinalizationError
    from backend.workflows import m63_daily

    engine = create_engine(f"sqlite:///{tmp_path / 'missing-queue-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    monkeypatch.setattr(m63_daily, "DEFAULT_QUEUE_PATH", tmp_path / "missing_queue.json")
    monkeypatch.setattr(daily_panel, "build_postmarket_panel", lambda *args, **kwargs: _panel_payload("2026-08-18"))
    monkeypatch.setattr(daily_panel, "build_news_event_risk_from_db", lambda *args, **kwargs: _news_payload("2026-08-18"))
    markdown_path = tmp_path / "postmarket_2026-08-18.md"
    markdown_path.write_text("report", encoding="utf-8")

    with pytest.raises(JobRunFinalizationError, match="work_metric_unavailable:human_review"):
        scheduler.run_tracked_job(
            "m63_postmarket",
            lambda: {
                "ok": True,
                "mode": "postmarket",
                "date": "2026-08-18",
                "output_path": str(markdown_path),
                "completed": 3,
                "failed": 0,
                "steps": _complete_steps(),
            },
            trigger_source="manual_cli",
            as_of="2026-08-18",
            input_coverage={
                "workflow": "m63_daily",
                "mode": "postmarket",
                "required_steps": ["m59_panel", "trigger_router", "task_capsule"],
            },
        )

    with Session() as db:
        row = db.query(JobRun).one()
        assert row.status == "error"
        assert "work_metric_unavailable:human_review" in (row.error or "")
    assert not (tmp_path / "postmarket_2026-08-18.daily_panel.json").exists()


def test_m63_panel_artifact_commit_mark_failure_turns_run_error(monkeypatch, tmp_path):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.evidence import daily_panel
    from backend.ops.job_ledger import JobRunFinalizationError
    from backend.workflows import m63_daily

    engine = create_engine(f"sqlite:///{tmp_path / 'commit-mark-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    queue_path = tmp_path / "m63_queue.json"
    _write_queue(queue_path)
    monkeypatch.setattr(m63_daily, "DEFAULT_QUEUE_PATH", queue_path)
    monkeypatch.setattr(daily_panel, "build_postmarket_panel", lambda *args, **kwargs: _panel_payload("2026-08-18"))
    monkeypatch.setattr(daily_panel, "build_news_event_risk_from_db", lambda *args, **kwargs: _news_payload("2026-08-18"))
    monkeypatch.setattr(
        daily_panel,
        "mark_daily_panel_artifact_committed",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mark failed")),
    )
    markdown_path = tmp_path / "postmarket_2026-08-18.md"
    markdown_path.write_text("report", encoding="utf-8")

    with pytest.raises(JobRunFinalizationError, match="commit mark failed"):
        scheduler.run_tracked_job(
            "m63_postmarket",
            lambda: {
                "ok": True,
                "mode": "postmarket",
                "date": "2026-08-18",
                "output_path": str(markdown_path),
                "completed": 3,
                "failed": 0,
                "steps": _complete_steps(),
            },
            trigger_source="manual_cli",
            as_of="2026-08-18",
            input_coverage={
                "workflow": "m63_daily",
                "mode": "postmarket",
                "required_steps": ["m59_panel", "trigger_router", "task_capsule"],
            },
        )

    panel_path = tmp_path / "postmarket_2026-08-18.daily_panel.json"
    artifact = json.loads(panel_path.read_text(encoding="utf-8"))
    assert artifact["ledger_commit_state"] == "pending"
    with Session() as db:
        row = db.query(JobRun).one()
        assert row.status == "error"
        assert "commit mark failed" in (row.error or "")


def test_m63_panel_work_metrics_use_day_scope_queue_cohort(monkeypatch, tmp_path):
    from backend import scheduler
    from backend.config import settings
    from backend.data.database import Base
    from backend.data.models.job import JobRun
    from backend.evidence import daily_panel
    from backend.workflows import m63_daily

    engine = create_engine(f"sqlite:///{tmp_path / 'queue-cohort-ledger.db'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "job_ledger_enabled", True)
    monkeypatch.setattr("backend.data.database.SessionLocal", Session)
    queue_path = tmp_path / "m63_queue.json"
    _write_queue(queue_path, [
        {"id": "old-done", "status": "done", "created_at": "2026-08-17", "done_at": "2026-08-17"},
        {"id": "old-open", "status": "pending", "created_at": "2026-08-17"},
        {"id": "today-open", "status": "pending", "created_at": "2026-08-18"},
        {"id": "today-done", "status": "done", "created_at": "2026-08-18", "done_at": "2026-08-18"},
        {"id": "today-future-done", "status": "done", "created_at": "2026-08-18", "done_at": "2026-08-19"},
        {"id": "future-done", "status": "done", "created_at": "2026-08-19", "done_at": "2026-08-19"},
    ])
    monkeypatch.setattr(m63_daily, "DEFAULT_QUEUE_PATH", queue_path)
    monkeypatch.setattr(daily_panel, "build_postmarket_panel", lambda *args, **kwargs: _panel_payload("2026-08-18"))
    monkeypatch.setattr(daily_panel, "build_news_event_risk_from_db", lambda *args, **kwargs: _news_payload("2026-08-18"))
    markdown_path = tmp_path / "postmarket_2026-08-18.md"
    markdown_path.write_text("report", encoding="utf-8")

    scheduler.run_tracked_job(
        "m63_postmarket",
        lambda: {
            "ok": True,
            "mode": "postmarket",
            "date": "2026-08-18",
            "output_path": str(markdown_path),
            "completed": 3,
            "failed": 0,
            "steps": _complete_steps(),
        },
        trigger_source="manual_cli",
        as_of="2026-08-18",
        input_coverage={
            "workflow": "m63_daily",
            "mode": "postmarket",
            "required_steps": ["m59_panel", "trigger_router", "task_capsule"],
        },
    )

    with Session() as db:
        row = db.query(JobRun).one()
        artifact = json.loads(Path(row.artifact_path or "").read_text(encoding="utf-8"))
    assert artifact["work_metrics"]["human_review"] == {
        "status": "available",
        "cohort": "created_on_day",
        "required": 3,
        "completed": 1,
        "source": str(queue_path),
        "excluded_future": 1,
        "excluded_historical_completed": 1,
    }
    assert artifact["work_metrics"]["review_freshness"]["cohort"] == "as_of_backlog"
    assert artifact["work_metrics"]["review_freshness"]["total"] == 3
    assert artifact["work_metrics"]["review_freshness"]["stale"] == 1
    human_card = next(card for card in artifact["cards"] if card["card_type"] == "human_confirmation")
    pending_ids = {item["id"] for item in human_card["payload"]["pending_queue"]}
    assert "today-future-done" in pending_ids
    assert "future-done" not in pending_ids
