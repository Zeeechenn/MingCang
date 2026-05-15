"""
2026-05 长期分析师团 first batch 数据库迁移（幂等）

执行：
  PYTHONPATH=. python -m backend.data.migrations.add_long_term

变更：
  1. stocks 表加 industry 列（如不存在）
  2. 创建 financial_metrics + long_term_labels 表（create_all 跳过已存在）
  3. 调 sync_industry 回填现有 active CN 股的 industry
"""
import logging
from sqlalchemy import text

from backend.data.database import engine, init_db, SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    """Apply long-term analyst team schema migration (idempotent)."""
    # Step 1: stocks.industry 列
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(stocks)")).fetchall()]
        if "industry" in cols:
            logger.info("stocks.industry 已存在，跳过")
        else:
            conn.execute(text("ALTER TABLE stocks ADD COLUMN industry TEXT"))
            logger.info("✅ ALTER stocks ADD COLUMN industry")

    # Step 2: create_all 自动建新表
    init_db()
    logger.info("✅ financial_metrics + long_term_labels 已就绪")

    # Step 3: 回填 industry（首次需要联网）
    from backend.data.fundamentals import sync_industry
    db = SessionLocal()
    try:
        n = sync_industry(db)
        logger.info("✅ 行业回填 %d 只股", n)
    except Exception as e:
        logger.warning("⚠️ 行业回填失败（可稍后手动重试）: %s", e)
    finally:
        db.close()


if __name__ == "__main__":
    run()
