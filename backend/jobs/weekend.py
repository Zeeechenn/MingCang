"""Weekend and maintenance scheduler job implementations."""
import logging

from backend.config import settings

logger = logging.getLogger(__name__)


def run_train_model() -> None:
    """每周六训练 LightGBM Alpha 候选模型（不自动晋升生产）"""
    from backend.analysis.qlib_engine import train
    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        ok = train(db)
        if ok:
            logger.info("weekly candidate model training succeeded; awaiting human promotion")
        else:
            logger.warning("weekly candidate model training skipped (insufficient data)")
    except Exception as e:
        logger.error("weekly model training failed: %s", e)
    finally:
        db.close()


def run_weekly_longterm() -> None:
    """
    长期分析师团 first batch：每周日 11:00
    同步 industry + 5 年财报 → 跑 LongTermTeam → save_label
    """
    from backend.agents.long_term.storage import save_label
    from backend.agents.long_term.team import LongTermTeam
    from backend.data.database import SessionLocal, Stock
    from backend.data.fundamentals import (
        sync_disclosure_dates,
        sync_financial_metrics,
        sync_industry,
    )

    if not settings.long_term_team_enabled:
        logger.info("long_term team disabled, skipping weekly job")
        return

    db = SessionLocal()
    try:
        # 1. 同步基本面（industry 已有则跳过，财报幂等）
        try:
            n = sync_industry(db)
            logger.info("industry synced: %d updated", n)
        except Exception as e:
            logger.warning("sync_industry failed: %s", e)

        stocks = db.query(Stock).filter(Stock.active, Stock.market == "CN").all()
        for s in stocks:
            try:
                inserted = sync_financial_metrics(s.symbol, db, years=settings.financial_backfill_years)
                if inserted:
                    logger.info("financials %s: +%d rows", s.symbol, inserted)
            except Exception as e:
                logger.error("sync_financial_metrics %s failed: %s", s.symbol, e)

        try:
            n = sync_disclosure_dates(db, years=settings.financial_backfill_years)
            logger.info("disclosure dates synced: %d updated", n)
        except Exception as e:
            logger.warning("sync_disclosure_dates failed: %s", e)

        # 2. 跑团
        team = LongTermTeam()
        for s in stocks:
            try:
                label = team.run(s.symbol, s.name, db)
                save_label(label, db)
                logger.info("long-term %s = %s (score=%.0f)",
                            s.symbol, label.label, label.score)
            except Exception as e:
                logger.error("long-term team %s failed: %s", s.symbol, e)
    finally:
        db.close()


def run_weekly_long_term_reflect() -> dict:
    """Weekly long-term decision reflection into layered memory."""
    from backend.data.database import SessionLocal
    from backend.decision.memory_layered import weekly_long_term_reflect

    db = SessionLocal()
    try:
        reflection = weekly_long_term_reflect(db)
        return {"status": "ok", "reflection": reflection}
    finally:
        db.close()


def run_daily_memory_backup() -> None:
    """Daily dump of ai_memory to ~/.mingcang/memory/backups/ (M9.横向)."""
    from backend.data.database import SessionLocal
    from backend.memory.backup import run_daily_backup
    db = SessionLocal()
    try:
        path = run_daily_backup(db)
        logger.info("memory backup written: %s", path)
    except Exception as e:
        logger.error("memory backup failed: %s", e)
    finally:
        db.close()


def run_daily_memory_expire() -> None:
    """Daily cleanup of expired memory rows and stock-memory outcomes."""
    from backend.data.database import SessionLocal
    from backend.memory.ai_memory import expire_stale_memories
    from backend.memory.audit_log import cleanup_audit_log
    from backend.memory.stock_memory import update_judgment_outcomes
    db = SessionLocal()
    try:
        removed = expire_stale_memories(db)
        if removed:
            logger.info("memory expire: removed %d stale rows", removed)
        outcomes = update_judgment_outcomes(db)
        if outcomes:
            logger.info("stock memory outcomes: wrote %d rows", outcomes)
        audit_removed = cleanup_audit_log(db)
        if audit_removed:
            logger.info("audit log cleanup: removed %d old rows", audit_removed)
    except Exception as e:
        logger.error("memory expire failed: %s", e)
    finally:
        db.close()
