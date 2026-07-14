"""定时任务：scheduler 生命周期、job state、tracked job 与兼容入口。"""
import logging
from copy import deepcopy
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import settings
from backend.jobs.m63_schedule import job_m63_postmarket, register_m63_postmarket

logger = logging.getLogger(__name__)

# BackgroundScheduler 在独立线程运行，不阻塞 FastAPI event loop
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

JOB_STATE: dict[str, dict] = {}


def reset_job_state() -> None:
    """Reset in-memory scheduler state. Primarily used by tests."""
    JOB_STATE.clear()


def _state_for(job_name: str) -> dict:
    return JOB_STATE.setdefault(job_name, {
        "job": job_name,
        "running": False,
        "last_status": "never_run",
        "last_started_at": None,
        "last_finished_at": None,
        "last_duration_seconds": None,
        "last_result": None,
        "last_error": None,
        "success_count": 0,
        "error_count": 0,
    })


def get_scheduler_state() -> dict:
    """Return a JSON-serializable snapshot of scheduler runtime state."""
    return {
        "running": bool(getattr(scheduler, "running", False)),
        "jobs": deepcopy(JOB_STATE),
    }


def run_tracked_job(job_name: str, fn):
    """Run a job and record start/end/error metadata."""
    state = _state_for(job_name)
    started = datetime.now(UTC)
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
            "last_status": "success",
            "last_finished_at": finished.isoformat(),
            "last_duration_seconds": round((finished - started).total_seconds(), 3),
            "last_result": result,
            "success_count": state.get("success_count", 0) + 1,
        })
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
        raise


def tracked_job(job_name: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return run_tracked_job(job_name, lambda: fn(*args, **kwargs))
        return wrapper
    return decorator


def _kill_switch_guard(job_name: str) -> bool:
    """job 入口防线：熔断态返回 True 表示应跳过。"""
    try:
        from backend.ops import kill_switch
        if kill_switch.is_active():
            state = kill_switch.current_state() or {}
            logger.warning("🛑 [%s] 熔断激活，跳过：%s", job_name, state.get("reason"))
            return True
    except Exception as e:
        logger.error("kill_switch check failed in %s: %s", job_name, e)
    return False


def _postmarket_jobs():
    from backend.jobs import postmarket

    return postmarket


def _use_multi_agent_decision() -> bool:
    """Compatibility wrapper for postmarket signal aggregation mode."""
    return _postmarket_jobs()._use_multi_agent_decision()


def _recent_signal_returns(db, limit: int = 20) -> list[float]:
    """Compatibility wrapper for postmarket kill-switch return sampling."""
    return _postmarket_jobs()._recent_signal_returns(db, limit=limit)


def _run_kill_switch_checks(db) -> None:
    """Compatibility wrapper for postmarket kill-switch checks."""
    return _postmarket_jobs()._run_kill_switch_checks(
        db,
        recent_signal_returns=_recent_signal_returns,
    )


@tracked_job("premarket")
def job_premarket() -> None:
    """盘前任务：同步行情 + 个股新闻 + 沪深300指数"""
    if _kill_switch_guard("premarket"):
        return
    from backend.jobs.premarket import run_premarket

    return run_premarket()


def _build_regime(db, stocks):
    """Compatibility wrapper for postmarket regime construction."""
    return _postmarket_jobs()._build_regime(db, stocks)


def _load_postmarket_context(db, stocks) -> dict:
    """Compatibility wrapper for postmarket batch context loading."""
    return _postmarket_jobs()._load_postmarket_context(
        db,
        stocks,
        build_regime=_build_regime,
    )


def _postmarket_news_sentiment(stock, db) -> dict:
    """Compatibility wrapper for postmarket news sentiment."""
    return _postmarket_jobs()._postmarket_news_sentiment(stock, db)


def _should_record_memory_usage(context: dict) -> bool:
    """Compatibility wrapper for postmarket memory usage policy."""
    return _postmarket_jobs()._should_record_memory_usage(context)


def _analyze_postmarket_stock(
    stock,
    db,
    context: dict,
    as_of_date: str | None = None,
) -> dict | None:
    """Compatibility wrapper for per-stock postmarket analysis."""
    return _postmarket_jobs()._analyze_postmarket_stock(
        stock,
        db,
        context,
        as_of_date=as_of_date,
        postmarket_news_sentiment=_postmarket_news_sentiment,
        use_multi_agent_decision=_use_multi_agent_decision,
    )


def _persist_postmarket_stock(stock, analysis: dict, db) -> None:
    """Compatibility wrapper for postmarket signal persistence."""
    return _postmarket_jobs()._persist_postmarket_stock(stock, analysis, db)


def _maybe_send_postmarket_alert(stock, result: dict) -> bool:
    """Compatibility wrapper for postmarket Bark signal alerts."""
    return _postmarket_jobs()._maybe_send_postmarket_alert(stock, result)


def _open_position_weights(db) -> dict[str, float]:
    """Compatibility wrapper for PortfolioManager input weights."""
    return _postmarket_jobs()._open_position_weights(db)


def _apply_portfolio_decision(batch_items: list[tuple[Any, dict]], db) -> int:
    """Compatibility wrapper for batch-level portfolio decisions."""
    return _postmarket_jobs()._apply_portfolio_decision(
        batch_items,
        db,
        open_position_weights=_open_position_weights,
    )


def load_universe_symbols(path: str | Path) -> list[str]:
    """Compatibility wrapper for paper-trading universe JSON loading."""
    return _postmarket_jobs().load_universe_symbols(path)


def run_postmarket_batch(db, universe_symbols: list[str] | None = None) -> dict:
    """Run post-market analysis for active stocks or an explicit universe."""
    return _postmarket_jobs().run_postmarket_batch(
        db,
        universe_symbols,
        load_context=_load_postmarket_context,
        analyze_stock=_analyze_postmarket_stock,
        apply_portfolio_decision=_apply_portfolio_decision,
        persist_stock=_persist_postmarket_stock,
        send_alert=_maybe_send_postmarket_alert,
        run_kill_switch_checks=_run_kill_switch_checks,
    )


@tracked_job("postmarket")
def job_postmarket() -> dict:
    """盘后任务入口：量化 + 技术 + 情感 → 聚合 → 写 Signal 表。"""
    if _kill_switch_guard("postmarket"):
        return {"skipped": "kill_switch"}
    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        return run_postmarket_batch(db)
    finally:
        db.close()


@tracked_job("stoploss_check")
def job_stoploss_check() -> None:
    """盘中止损预警（每天 14:30 运行）。"""
    if _kill_switch_guard("stoploss_check"):
        return
    from backend.jobs.intraday import run_stoploss_check

    return run_stoploss_check()


@tracked_job("train_model")
def job_train_model() -> None:
    """每周六训练 LightGBM Alpha 候选模型（不自动晋升生产）。"""
    from backend.jobs.weekend import run_train_model

    return run_train_model()


@tracked_job("weekly_longterm")
def job_weekly_longterm() -> None:
    """长期分析师团 first batch：同步基本面并运行 LongTermTeam。"""
    from backend.jobs.weekend import run_weekly_longterm

    return run_weekly_longterm()


@tracked_job("weekly_long_term_reflect")
def job_weekly_long_term_reflect() -> dict:
    """Weekly long-term decision reflection into layered memory."""
    from backend.jobs.weekend import run_weekly_long_term_reflect

    return run_weekly_long_term_reflect()


@tracked_job("daily_memory_backup")
def job_daily_memory_backup() -> None:
    """Daily dump of ai_memory to ~/.mingcang/memory/backups/ (M9.横向)."""
    from backend.jobs.weekend import run_daily_memory_backup

    return run_daily_memory_backup()


@tracked_job("daily_memory_expire")
def job_daily_memory_expire() -> None:
    """Daily cleanup of expired memory rows and stock-memory outcomes."""
    from backend.jobs.weekend import run_daily_memory_expire

    return run_daily_memory_expire()


def _parse_hhmm(value: str, name: str) -> tuple[int, int]:
    """Parse a HH:MM schedule string, raising a clear error on bad format."""
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"Invalid schedule config {name}={value!r} — expected HH:MM format"
        ) from exc


def start() -> None:
    """Register all cron jobs and start the background scheduler."""
    pre_h, pre_m = _parse_hhmm(settings.schedule_premarket, "schedule_premarket")
    post_h, post_m = _parse_hhmm(settings.schedule_postmarket, "schedule_postmarket")
    long_mon_h, long_mon_m = _parse_hhmm(settings.schedule_longterm_monday_time, "schedule_longterm_monday_time")
    long_fri_h, long_fri_m = _parse_hhmm(settings.schedule_longterm_friday_time, "schedule_longterm_friday_time")
    reflect_h, reflect_m = _parse_hhmm(settings.schedule_longterm_time, "schedule_longterm_time")

    scheduler.add_job(job_premarket, CronTrigger(
        hour=int(pre_h), minute=int(pre_m), day_of_week="mon-fri",
    ), id="premarket", replace_existing=True)

    scheduler.add_job(job_postmarket, CronTrigger(
        hour=int(post_h), minute=int(post_m), day_of_week="mon-fri",
    ), id="postmarket", replace_existing=True)

    register_m63_postmarket(scheduler, settings, job_m63_postmarket)
    # 每周六 09:00 重训 LightGBM Alpha 模型
    scheduler.add_job(job_train_model, CronTrigger(
        hour=9, minute=0, day_of_week="sat",
    ), id="train_model", replace_existing=True)

    # 盘中止损预警 14:30（工作日）
    scheduler.add_job(job_stoploss_check, CronTrigger(
        hour=14, minute=30, day_of_week="mon-fri",
    ), id="stoploss_check", replace_existing=True)

    # 每日 00:30 备份 ai_memory（M9.横向）
    scheduler.add_job(job_daily_memory_backup, CronTrigger(
        hour=0, minute=30,
    ), id="daily_memory_backup", replace_existing=True)

    # 每日 01:00 清理过期 ai_memory（M9.3）
    scheduler.add_job(job_daily_memory_expire, CronTrigger(
        hour=1, minute=0,
    ), id="daily_memory_expire", replace_existing=True)

    # 长期分析师团：周一早盘前 + 周五收盘后复盘
    if settings.long_term_team_enabled:
        scheduler.add_job(job_weekly_longterm, CronTrigger(
            hour=int(long_mon_h), minute=int(long_mon_m), day_of_week=settings.schedule_longterm_monday_dow,
        ), id="weekly_longterm_monday", replace_existing=True)
        scheduler.add_job(job_weekly_longterm, CronTrigger(
            hour=int(long_fri_h), minute=int(long_fri_m), day_of_week=settings.schedule_longterm_friday_dow,
        ), id="weekly_longterm_friday", replace_existing=True)
        logger.info("long_term team scheduled: %s %s, %s %s",
                    settings.schedule_longterm_monday_dow,
                    settings.schedule_longterm_monday_time,
                    settings.schedule_longterm_friday_dow,
                    settings.schedule_longterm_friday_time)

    scheduler.add_job(job_weekly_long_term_reflect, CronTrigger(
        hour=int(reflect_h), minute=int(reflect_m), day_of_week=settings.schedule_longterm_dow,
    ), id="weekly_long_term_reflect", replace_existing=True)

    scheduler.start()
    logger.info("scheduler started (premarket=%s, postmarket=%s)",
                settings.schedule_premarket, settings.schedule_postmarket)


def stop() -> None:
    """Shut down the background scheduler without waiting for jobs to finish."""
    scheduler.shutdown(wait=False)
