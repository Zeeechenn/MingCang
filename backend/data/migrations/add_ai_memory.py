"""
2026-05 AI memory schema migration（幂等）

执行：
  PYTHONPATH=. python -m backend.data.migrations.add_ai_memory
"""
import logging
from sqlalchemy import text

from backend.data.database import engine, init_db, SessionLocal
from backend.memory.audit_log import audit_write

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    """Apply AI memory schema migration (idempotent)."""
    init_db()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT,
                scope TEXT DEFAULT 'global',
                ttl_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(key, scope)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_memory_scope_cat
            ON ai_memory(scope, category)
        """))
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS audit_log_fts USING fts5(
                timestamp, event_type, content, related_symbol, related_scope
            )
        """))

    db = SessionLocal()
    try:
        audit_write(db, "migration", "AI memory schema migration completed", related_scope="global")
    finally:
        db.close()
    logger.info("✅ ai_memory + audit_log_fts 已就绪")


if __name__ == "__main__":
    run()
