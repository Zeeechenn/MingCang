from datetime import datetime, timedelta


def test_data_coverage_snapshot_adds_generated_at_and_warnings(test_db):
    from backend.data.database import NewsItem, Price, Stock
    from backend.data.quality import build_data_coverage_snapshot

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", active=True))
    test_db.add(Price(symbol="600519", date="2026-05-20", open=1, high=1, low=1, close=1, volume=1))
    test_db.add(NewsItem(
        symbol="600519",
        title="old",
        url="https://example.com/old",
        published_at=datetime.utcnow() - timedelta(days=3),
        source="x",
    ))
    test_db.commit()

    snapshot = build_data_coverage_snapshot(test_db, generated_at="2026-05-20T16:00:00Z")

    assert snapshot["generated_at"] == "2026-05-20T16:00:00Z"
    assert snapshot["summary"]["active_stocks"] == 1
    assert snapshot["checks"]["price_coverage_ok"] is True
    assert snapshot["checks"]["financial_coverage_ok"] is False
    assert snapshot["checks"]["fresh_news_ok"] is False
    assert any("financial" in item["code"] for item in snapshot["warnings"])
    assert any("fresh_news" in item["code"] for item in snapshot["warnings"])


def test_scheduler_tracks_success_and_failure():
    from backend import scheduler

    scheduler.reset_job_state()

    assert scheduler.run_tracked_job("unit_success", lambda: {"count": 2}) == {"count": 2}
    success = scheduler.get_scheduler_state()["jobs"]["unit_success"]
    assert success["last_status"] == "success"
    assert success["success_count"] == 1
    assert success["last_result"] == {"count": 2}

    try:
        scheduler.run_tracked_job("unit_error", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    except RuntimeError:
        pass
    failed = scheduler.get_scheduler_state()["jobs"]["unit_error"]
    assert failed["last_status"] == "error"
    assert failed["error_count"] == 1
    assert "boom" in failed["last_error"]


def test_scheduler_weekly_long_term_reflect_invokes_layered_memory(monkeypatch):
    from backend import scheduler

    calls = []

    class FakeDb:
        def close(self):
            calls.append("closed")

    monkeypatch.setattr("backend.data.database.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        "backend.decision.memory_layered.weekly_long_term_reflect",
        lambda db: calls.append(db) or "reflection",
    )

    result = scheduler.job_weekly_long_term_reflect()

    assert result == {"status": "ok", "reflection": "reflection"}
    assert isinstance(calls[0], FakeDb)
    assert calls[1] == "closed"


def test_system_health_exposes_scheduler_state(test_db):
    from backend import scheduler
    from backend.api.routes.system import system_health

    scheduler.reset_job_state()
    scheduler.run_tracked_job("health_probe", lambda: None)

    health = system_health(db=test_db)

    assert "scheduler" in health
    assert health["scheduler"]["jobs"]["health_probe"]["last_status"] == "success"
