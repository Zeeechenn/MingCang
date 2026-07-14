"""Isolated scheduler adapter for the M63 daily evidence workflow."""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger


def job_m63_postmarket() -> dict:
    """Run M63 under the shared kill-switch and scheduler-state contracts."""
    from backend.scheduler import _kill_switch_guard, run_tracked_job

    def run() -> dict:
        if _kill_switch_guard("m63_postmarket"):
            return {"skipped": "kill_switch"}
        from backend.workflows import m63_daily

        result = m63_daily.build_postmarket_report()
        path = m63_daily.write_report(result["mode"], result["date"], result["text"])
        result["output_path"] = str(path)
        return result

    return run_tracked_job("m63_postmarket", run)


def register_m63_postmarket(scheduler, settings, job=job_m63_postmarket) -> None:
    """Register M63 separately from the signal-writing postmarket batch."""
    if not settings.m63_daily_enabled:
        return
    from backend.scheduler import _parse_hhmm

    hour, minute = _parse_hhmm(settings.schedule_m63_postmarket, "schedule_m63_postmarket")
    scheduler.add_job(
        job,
        CronTrigger(hour=hour, minute=minute, day_of_week="mon-fri"),
        id="m63_postmarket",
        replace_existing=True,
    )
