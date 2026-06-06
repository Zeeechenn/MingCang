"""SQLAlchemy engine, session, and declarative Base — the ORM infrastructure.

Source of truth for the DB engine / session factory / declarative Base and the
shared ``_utcnow`` helper.  ``backend.data.database`` re-exports these for
backward compatibility; new code may import them from here directly.
"""
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import BASE_DIR, settings


def _utcnow() -> datetime:
    """Return current UTC time as timezone-naive datetime (SQLite compatible).

    M21.4: 替代已弃用的 datetime.utcnow()，保持存储格式不变（naive UTC）。
    """
    return datetime.now(UTC).replace(tzinfo=None)


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
_DEFAULT_DB_PATH = (BASE_DIR / "mingcang.db").resolve()


@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_conn, _) -> None:
    """开启 WAL 模式，避免 APScheduler + FastAPI 并发写锁冲突"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Base(DeclarativeBase):
    pass
