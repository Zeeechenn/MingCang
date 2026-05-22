"""System status, health, runtime config, kill switch, and cold-start init routes."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.schemas import DataCoverageOut
from backend.data.database import (
    FinancialMetric,
    LongTermLabel,
    Price,
    SessionLocal,
    Signal,
    get_db,
)
from backend.data.external_sources import build_external_source_catalog, probe_external_sources

logger = logging.getLogger(__name__)
router = APIRouter()


RUNTIME_CONFIG_KEYS = {
    "paper_trading_profile",
    "new_framework_entry_threshold",
    "test1_entry_threshold",
    "weight_quant",
    "weight_technical",
    "weight_sentiment",
    "adx_filter_enabled",
    "regime_filter_enabled",
    "multi_agent_enabled",
    "risk_manager_enabled",
    "director_min_confidence",
    "long_term_team_enabled",
    "trailing_stop_enabled",
    "max_position_per_stock",
    "max_position_per_sector",
    "max_total_equity_pct",
    "financial_backfill_years",
    "tavily_supplement_threshold",
    "anspire_news_days",
    "anspire_news_max_results",
    "anspire_news_max_add",
    "anspire_news_min_score",
    "schedule_daily_review_time",
    "schedule_longterm_monday_dow",
    "schedule_longterm_monday_time",
    "schedule_longterm_friday_dow",
    "schedule_longterm_friday_time",
}


def _runtime_config_payload() -> dict:
    """Return editable runtime settings for the Admin UI."""
    from backend.config import active_signal_weights, settings
    from backend.ops import kill_switch

    weights = active_signal_weights()
    ks_state = kill_switch.current_state()
    return {
        "persisted": False,
        "note": "运行时配置只影响当前 FastAPI 进程，重启后按 .env 恢复。",
        "profile": settings.paper_trading_profile,
        "active_profile": weights.profile,
        "entry_threshold": weights.entry_threshold,
        "new_framework_entry_threshold": settings.new_framework_entry_threshold,
        "test1_entry_threshold": settings.test1_entry_threshold,
        "weights": {
            "quant": weights.quant,
            "technical": weights.technical,
            "sentiment": weights.sentiment,
        },
        "raw_weights": {
            "weight_quant": settings.weight_quant,
            "weight_technical": settings.weight_technical,
            "weight_sentiment": settings.weight_sentiment,
            "test1_weight_quant": settings.test1_weight_quant,
            "test1_weight_technical": settings.test1_weight_technical,
            "test1_weight_sentiment": settings.test1_weight_sentiment,
        },
        "adx_filter_enabled": settings.adx_filter_enabled,
        "regime_filter_enabled": settings.regime_filter_enabled,
        "multi_agent_enabled": settings.multi_agent_enabled,
        "risk_manager_enabled": settings.risk_manager_enabled,
        "director_min_confidence": settings.director_min_confidence,
        "long_term_team_enabled": settings.long_term_team_enabled,
        "trailing_stop_enabled": settings.trailing_stop_enabled,
        "max_position_per_stock": settings.max_position_per_stock,
        "max_position_per_sector": settings.max_position_per_sector,
        "max_total_equity_pct": settings.max_total_equity_pct,
        "data_draft": {
            "financial_backfill_years": settings.financial_backfill_years,
            "tavily_supplement_threshold": settings.tavily_supplement_threshold,
            "anspire_news_days": settings.anspire_news_days,
            "anspire_news_max_results": settings.anspire_news_max_results,
            "anspire_news_max_add": settings.anspire_news_max_add,
            "anspire_news_min_score": settings.anspire_news_min_score,
        },
        "schedule": {
            "daily_review_time": settings.schedule_daily_review_time,
            "longterm_monday_dow": settings.schedule_longterm_monday_dow,
            "longterm_monday_time": settings.schedule_longterm_monday_time,
            "longterm_friday_dow": settings.schedule_longterm_friday_dow,
            "longterm_friday_time": settings.schedule_longterm_friday_time,
        },
        "kill_switch_active": bool(ks_state and ks_state.get("active")),
    }


@router.get("/system/runtime-config")
def get_runtime_config():
    """Return editable runtime configuration for the Admin UI."""
    return _runtime_config_payload()


@router.patch("/system/runtime-config")
def update_runtime_config(payload: dict):
    """Update a safe whitelist of runtime settings for the current process."""
    from backend.config import settings

    for key in payload:
        if key not in RUNTIME_CONFIG_KEYS:
            raise HTTPException(400, f"Unsupported runtime config key: {key}")

    for key, value in payload.items():
        setattr(settings, key, value)

    return _runtime_config_payload()


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)):
    """Return database and long-term label status summary."""
    from backend.config import settings

    latest_price_date = db.query(Price.date).order_by(Price.date.desc()).first()
    latest_label_date = db.query(LongTermLabel.date).order_by(LongTermLabel.date.desc()).first()
    try:
        from backend.scheduler import get_scheduler_state
        scheduler_state = get_scheduler_state()
    except Exception:
        scheduler_state = None

    return {
        "database_url": settings.database_url,
        "database_path": settings.database_url.removeprefix("sqlite:///"),
        "database_exists": Path(settings.database_url.removeprefix("sqlite:///")).exists(),
        "latest_price_date": latest_price_date[0] if latest_price_date else None,
        "financial_metrics_count": db.query(FinancialMetric).count(),
        "long_term_labels_count": db.query(LongTermLabel).count(),
        "latest_long_term_label_date": latest_label_date[0] if latest_label_date else None,
        "scheduler": scheduler_state,
    }


@router.get("/system/data-coverage", response_model=DataCoverageOut)
def data_coverage(db: Session = Depends(get_db)):
    """Return data coverage and provider reliability report."""
    from backend.data.quality import build_data_coverage_report

    return build_data_coverage_report(db)


@router.get("/system/external-data-sources")
def external_data_sources(probe: bool = False, symbol: str = "600519"):
    """Return candidate external data sources and optional side-effect-free probes."""
    payload = build_external_source_catalog()
    payload["probes"] = probe_external_sources(symbol=symbol) if probe else {}
    return payload


@router.get("/system/health")
def system_health(db: Session = Depends(get_db)):
    """
    综合健康检查（Tier 4）：DB / 数据新鲜度 / kill switch / 连续亏损。

    供外部监控（如 Bark / Uptime / Grafana）轮询。
    """
    from backend.config import settings
    from backend.ops import kill_switch

    db_path = settings.database_url.removeprefix("sqlite:///")
    db_ok = Path(db_path).exists()

    latest_price_date = None
    data_age_days = None
    try:
        row = db.query(Price.date).order_by(Price.date.desc()).first()
        latest_price_date = row[0] if row else None
        if latest_price_date:
            last = datetime.strptime(latest_price_date, "%Y-%m-%d")
            data_age_days = (datetime.utcnow() - last).days
    except Exception:
        db_ok = False

    recent_losses = 0
    try:
        recent_signals = (
            db.query(Signal)
            .filter(Signal.recommendation.in_(["可小仓试错", "买入", "强买"]))
            .order_by(Signal.date.desc())
            .limit(10)
            .all()
        )
        returns = []
        for sig in recent_signals:
            sig_p = db.query(Price.close).filter(
                Price.symbol == sig.symbol, Price.date == sig.date
            ).first()
            next_p = db.query(Price.close).filter(
                Price.symbol == sig.symbol, Price.date > sig.date
            ).order_by(Price.date.asc()).first()
            if sig_p and next_p and sig_p[0]:
                returns.append((next_p[0] - sig_p[0]) / sig_p[0])
        recent_losses = kill_switch.detect_consecutive_losses(returns)
    except Exception:
        pass

    ks_state = kill_switch.current_state()
    try:
        from backend.scheduler import get_scheduler_state
        scheduler_state = get_scheduler_state()
    except Exception as e:
        scheduler_state = {"error": str(e), "jobs": {}}

    healthy = (
        db_ok
        and (data_age_days is None or data_age_days <= kill_switch.DEFAULT_DATA_STALE_DAYS)
        and not (ks_state and ks_state.get("active"))
    )

    return {
        "healthy": healthy,
        "db_ok": db_ok,
        "db_path": db_path,
        "latest_price_date": latest_price_date,
        "data_age_days": data_age_days,
        "data_stale_threshold_days": kill_switch.DEFAULT_DATA_STALE_DAYS,
        "kill_switch": ks_state,
        "consecutive_losses": recent_losses,
        "consecutive_losses_threshold": kill_switch.DEFAULT_CONSECUTIVE_LOSSES,
        "scheduler": scheduler_state,
    }


@router.post("/system/kill-switch/trigger")
def trigger_kill_switch(reason: str = "manual"):
    """Manually trigger the kill switch with a reason string."""
    from backend.ops import kill_switch

    state = kill_switch.trigger(reason=reason, metadata={"source": "api"})
    return state.to_dict()


@router.post("/system/kill-switch/reset")
def reset_kill_switch():
    """Reset an active kill switch state."""
    from backend.ops import kill_switch

    kill_switch.reset()
    return {"reset": True}


_init_state: dict = {
    "running": False,
    "step": "idle",
    "log": [],
    "started_at": None,
    "finished_at": None,
    "counts": {},
    "error": None,
}


def _init_log(msg: str) -> None:
    _init_state["log"].append(msg)
    if len(_init_state["log"]) > 60:
        _init_state["log"] = _init_state["log"][-60:]
    logger.info("[init] %s", msg)


def _run_initialize() -> None:
    from datetime import datetime as _dt

    from backend.data.database import Stock

    db: Session | None = SessionLocal()
    try:
        _init_state.update({
            "running": True, "step": "prices",
            "log": [], "error": None, "counts": {},
            "started_at": _dt.now().strftime("%H:%M:%S"),
            "finished_at": None,
        })

        from backend.data.market import backfill_if_needed
        assert db is not None
        stocks = db.query(Stock).filter(Stock.active).all()
        _init_log(f"价格回填：共 {len(stocks)} 只股票")
        price_rows = 0
        for s in stocks:
            try:
                n = backfill_if_needed(s.symbol, s.market, db)
                price_rows += n
                if n:
                    _init_log(f"  {s.symbol} {s.name} +{n} 条")
            except Exception as e:
                _init_log(f"  {s.symbol} 价格失败: {e}")
        _init_state["counts"]["price_rows"] = price_rows
        _init_log(f"价格完成，新增 {price_rows} 条")

        _init_state["step"] = "financials"
        from backend.data.fundamentals import sync_financial_metrics
        _init_log(f"财报同步：共 {len(stocks)} 只")
        fin_rows = 0
        for s in stocks:
            if s.market != "CN":
                continue
            try:
                n = sync_financial_metrics(s.symbol, db)
                fin_rows += n
                if n:
                    _init_log(f"  {s.symbol} +{n} 期财报")
            except Exception as e:
                _init_log(f"  {s.symbol} 财报失败: {e}")
        _init_state["counts"]["financial_rows"] = fin_rows
        _init_log(f"财报完成，新增 {fin_rows} 条")

        _init_state["step"] = "disclosure"
        from backend.data.fundamentals import sync_disclosure_dates
        _init_log("同步真实披露日...")
        n = sync_disclosure_dates(db)
        _init_state["counts"]["disclosure_rows"] = n
        _init_log(f"披露日完成，更新 {n} 条")

        _init_state["step"] = "signals"
        _init_log("生成首批信号（运行盘后任务）...")
        db.close()
        db = None
        from backend.scheduler import job_postmarket
        job_postmarket()
        _init_log("信号生成完成")

        _init_state.update({
            "step": "done",
            "finished_at": _dt.now().strftime("%H:%M:%S"),
        })
        _init_log("初始化完成")

    except Exception as e:
        _init_state.update({"step": "error", "error": str(e)})
        _init_log(f"失败: {e}")
        logger.error("initialize failed: %s", e, exc_info=True)
    finally:
        _init_state["running"] = False
        if db is not None:
            db.close()


@router.post("/system/initialize")
def start_initialize(background_tasks: BackgroundTasks):
    """启动冷启动初始化：价格回填 → 财报同步 → 披露日 → 生成首批信号。"""
    if _init_state["running"]:
        raise HTTPException(409, "初始化已在运行中")
    background_tasks.add_task(_run_initialize)
    return {"status": "started"}


@router.get("/system/initialize/status")
def get_initialize_status():
    """查询冷启动进度。"""
    return {
        "running": _init_state["running"],
        "step": _init_state["step"],
        "log": _init_state["log"][-20:],
        "started_at": _init_state["started_at"],
        "finished_at": _init_state["finished_at"],
        "counts": _init_state["counts"],
        "error": _init_state["error"],
    }
