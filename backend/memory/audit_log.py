"""Layer 3 audit log helpers backed by SQLite FTS5."""
from __future__ import annotations

from datetime import datetime, timezone, timezone

from sqlalchemy import text
from sqlalchemy.exc import OperationalError


def _ensure_schema(db) -> None:
    """Create the audit_log_fts virtual table if it does not exist."""
    bind = db.get_bind()
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS audit_log_fts USING fts5(
                timestamp, event_type, content, related_symbol, related_scope
            )
        """))


def audit_write(
    db,
    event_type: str,
    content: str,
    *,
    related_symbol: str | None = None,
    related_scope: str | None = None,
    timestamp: str | None = None,
) -> None:
    """Append an event to the audit log FTS table."""
    _ensure_schema(db)
    ts = timestamp or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    db.execute(text("""
        INSERT INTO audit_log_fts(timestamp, event_type, content, related_symbol, related_scope)
        VALUES(:timestamp, :event_type, :content, :related_symbol, :related_scope)
    """), {
        "timestamp": ts,
        "event_type": event_type,
        "content": content,
        "related_symbol": related_symbol,
        "related_scope": related_scope,
    })
    db.commit()


def _fts_phrase(query: str) -> str:
    escaped = query.strip().replace('"', '""')
    return f"\"{escaped}\""


def audit_search(db, query: str, *, limit: int = 20) -> list[dict]:
    """Full-text search the audit log and return matching rows."""
    _ensure_schema(db)
    try:
        rows = db.execute(text("""
            SELECT timestamp, event_type, content, related_symbol, related_scope
            FROM audit_log_fts
            WHERE audit_log_fts MATCH :query
            ORDER BY rank
            LIMIT :limit
        """), {"query": _fts_phrase(query), "limit": limit}).all()
    except OperationalError:
        like = f"%{query}%"
        rows = db.execute(text("""
            SELECT timestamp, event_type, content, related_symbol, related_scope
            FROM audit_log_fts
            WHERE content LIKE :like OR event_type LIKE :like
                OR related_symbol LIKE :like OR related_scope LIKE :like
            ORDER BY timestamp DESC
            LIMIT :limit
        """), {"like": like, "limit": limit}).all()
    return [
        {
            "timestamp": row.timestamp,
            "event_type": row.event_type,
            "content": row.content,
            "related_symbol": row.related_symbol,
            "related_scope": row.related_scope,
        }
        for row in rows
    ]


def cleanup_audit_log(db, *, keep_rows: int = 50000) -> int:
    """Keep the newest audit rows and delete older FTS rows."""
    _ensure_schema(db)
    total = db.execute(text("SELECT count(*) FROM audit_log_fts")).scalar() or 0
    if keep_rows < 0:
        keep_rows = 0
    remove_count = max(0, int(total) - int(keep_rows))
    if remove_count == 0:
        return 0
    db.execute(text("""
        DELETE FROM audit_log_fts
        WHERE rowid IN (
            SELECT rowid FROM audit_log_fts
            ORDER BY timestamp ASC, rowid ASC
            LIMIT :remove_count
        )
    """), {"remove_count": remove_count})
    db.commit()
    return remove_count
