"""Layer 3 audit log helpers backed by SQLite FTS5."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import text


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
    ts = timestamp or datetime.utcnow().isoformat(timespec="seconds")
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


def audit_search(db, query: str, *, limit: int = 20) -> list[dict]:
    """Full-text search the audit log and return matching rows."""
    _ensure_schema(db)
    rows = db.execute(text("""
        SELECT timestamp, event_type, content, related_symbol, related_scope
        FROM audit_log_fts
        WHERE audit_log_fts MATCH :query
        ORDER BY rank
        LIMIT :limit
    """), {"query": query, "limit": limit}).all()
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
