from __future__ import annotations


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
