"""定时任务：scheduler 生命周期、job state、tracked job 与兼容入口。"""
import logging
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from backend.config import settings
from backend.jobs.m63_schedule import job_m63_postmarket

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


def run_tracked_job(
    job_name: str,
    fn,
    *,
    trigger_source: str = "scheduler",
    as_of: str | None = None,
    input_coverage: dict[str, Any] | None = None,
    artifact_path: str | Path | None = None,
):
    """Run a job and record in-memory plus persistent start/end/error metadata."""
    from backend.ops.job_runner import execute_tracked_job

    return execute_tracked_job(
        _state_for(job_name),
        job_name,
        fn,
        trigger_source=trigger_source,
        as_of=as_of,
        input_coverage=input_coverage,
        artifact_path=artifact_path,
    )


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
def job_premarket() -> dict | None:
    """盘前任务：同步行情 + 个股新闻 + 沪深300指数"""
    if _kill_switch_guard("premarket"):
        return None
    from backend.jobs.premarket import run_premarket

    return run_premarket("CN")


@tracked_job("premarket_hk")
def job_premarket_hk() -> dict:
    """港股灰度盘前刷新；仅显式白名单。"""
    from backend.jobs.premarket import run_premarket

    return run_premarket("HK")


@tracked_job("premarket_us")
def job_premarket_us() -> dict:
    """美股灰度盘前刷新；仅显式白名单。"""
    from backend.jobs.premarket import run_premarket

    return run_premarket("US")


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


def run_postmarket_batch(
    db,
    universe_symbols: list[str] | None = None,
    market: str | None = None,
) -> dict:
    """Run post-market analysis for active stocks or an explicit universe."""
    return _postmarket_jobs().run_postmarket_batch(
        db,
        universe_symbols,
        market,
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
        return run_postmarket_batch(db, market="CN")
    finally:
        db.close()


def _run_gray_postmarket(market: str) -> dict:
    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        return run_postmarket_batch(db, market=market)
    finally:
        db.close()


@tracked_job("postmarket_hk")
def job_postmarket_hk() -> dict:
    """港股收盘确认后的影子信号任务。"""
    return _run_gray_postmarket("HK")


@tracked_job("postmarket_us")
def job_postmarket_us() -> dict:
    """美股收盘确认后的影子信号任务。"""
    return _run_gray_postmarket("US")


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


def start() -> None:
    """Register all cron jobs and start the background scheduler."""
    from backend.jobs.schedule_registry import register_scheduler_jobs

    register_scheduler_jobs(scheduler, settings, {
        "premarket": job_premarket, "postmarket": job_postmarket,
        "premarket_hk": job_premarket_hk, "postmarket_hk": job_postmarket_hk,
        "premarket_us": job_premarket_us, "postmarket_us": job_postmarket_us,
        "m63_postmarket": job_m63_postmarket, "train_model": job_train_model,
        "stoploss_check": job_stoploss_check, "daily_memory_backup": job_daily_memory_backup,
        "daily_memory_expire": job_daily_memory_expire, "weekly_longterm": job_weekly_longterm,
        "weekly_long_term_reflect": job_weekly_long_term_reflect,
    })

    scheduler.start()
    logger.info(
        "scheduler started (CN=%s/%s, HK=%s/%s, US=%s/%s, gray=%s)",
        settings.schedule_premarket,
        settings.schedule_postmarket,
        settings.schedule_hk_premarket,
        settings.schedule_hk_postmarket,
        settings.schedule_us_premarket,
        settings.schedule_us_postmarket,
        settings.multimarket_gray_enabled,
    )


def stop() -> None:
    """Shut down the background scheduler without waiting for jobs to finish."""
    scheduler.shutdown(wait=False)
