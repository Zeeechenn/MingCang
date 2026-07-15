"""Cron registration extracted from the scheduler compatibility facade."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from apscheduler.triggers.cron import CronTrigger

from backend.jobs.m63_schedule import register_m63_postmarket

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str, name: str) -> tuple[int, int]:
    try:
        hour, minute = value.split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid schedule config {name}={value!r} — expected HH:MM format") from exc


def register_scheduler_jobs(
    scheduler: Any,
    settings: Any,
    jobs: dict[str, Callable[..., Any]],
) -> None:
    """Register CN production and explicit HK/US gray schedules."""
    pre_h, pre_m = _parse_hhmm(settings.schedule_premarket, "schedule_premarket")
    post_h, post_m = _parse_hhmm(settings.schedule_postmarket, "schedule_postmarket")
    scheduler.add_job(
        jobs["premarket"],
        CronTrigger(hour=pre_h, minute=pre_m, day_of_week="mon-fri"),
        id="premarket",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs["postmarket"],
        CronTrigger(hour=post_h, minute=post_m, day_of_week="mon-fri"),
        id="postmarket",
        replace_existing=True,
    )

    if settings.multimarket_gray_enabled:
        gray_contracts = (
            ("premarket_hk", settings.schedule_hk_premarket, "Asia/Hong_Kong"),
            ("postmarket_hk", settings.schedule_hk_postmarket, "Asia/Hong_Kong"),
            ("premarket_us", settings.schedule_us_premarket, "America/New_York"),
            ("postmarket_us", settings.schedule_us_postmarket, "America/New_York"),
        )
        for job_id, schedule, timezone in gray_contracts:
            hour, minute = _parse_hhmm(schedule, f"schedule_{job_id}")
            scheduler.add_job(
                jobs[job_id],
                CronTrigger(
                    hour=hour,
                    minute=minute,
                    day_of_week="mon-fri",
                    timezone=timezone,
                ),
                id=job_id,
                replace_existing=True,
            )

    register_m63_postmarket(scheduler, settings, jobs["m63_postmarket"])
    fixed = (
        ("train_model", {"hour": 9, "minute": 0, "day_of_week": "sat"}),
        ("stoploss_check", {"hour": 14, "minute": 30, "day_of_week": "mon-fri"}),
        ("daily_memory_backup", {"hour": 0, "minute": 30}),
        ("daily_memory_expire", {"hour": 1, "minute": 0}),
    )
    for job_id, trigger_kwargs in fixed:
        scheduler.add_job(
            jobs[job_id],
            CronTrigger(**trigger_kwargs),
            id=job_id,
            replace_existing=True,
        )

    if settings.long_term_team_enabled:
        for suffix, dow, schedule in (
            ("monday", settings.schedule_longterm_monday_dow, settings.schedule_longterm_monday_time),
            ("friday", settings.schedule_longterm_friday_dow, settings.schedule_longterm_friday_time),
        ):
            hour, minute = _parse_hhmm(schedule, f"schedule_longterm_{suffix}_time")
            scheduler.add_job(
                jobs["weekly_longterm"],
                CronTrigger(hour=hour, minute=minute, day_of_week=dow),
                id=f"weekly_longterm_{suffix}",
                replace_existing=True,
            )
        logger.info("long_term team scheduled: %s/%s", settings.schedule_longterm_monday_time, settings.schedule_longterm_friday_time)

    reflect_h, reflect_m = _parse_hhmm(settings.schedule_longterm_time, "schedule_longterm_time")
    scheduler.add_job(
        jobs["weekly_long_term_reflect"],
        CronTrigger(hour=reflect_h, minute=reflect_m, day_of_week=settings.schedule_longterm_dow),
        id="weekly_long_term_reflect",
        replace_existing=True,
    )
