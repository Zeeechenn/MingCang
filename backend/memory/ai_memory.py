"""Layer 2 persistent memory helpers."""
from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import text


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.utcnow()


def _ensure_schema(db) -> None:
    """Create the ai_memory table and index if they do not exist."""
    bind = db.get_bind()
    with bind.begin() as conn:
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


def _is_active(row, now: datetime) -> bool:
    """Return True if the memory row has not yet expired."""
    ttl_days = row.ttl_days
    if ttl_days is None:
        return True
    updated_at = datetime.fromisoformat(str(row.updated_at))
    return updated_at + timedelta(days=int(ttl_days)) >= now


def remember(
    db,
    key: str,
    value: str,
    *,
    category: str | None = None,
    scope: str = "global",
    ttl_days: int | None = None,
) -> None:
    """Upsert a key-value memory entry with optional TTL."""
    _ensure_schema(db)
    now = _utc_now().isoformat(timespec="seconds")
    db.execute(text("""
        INSERT INTO ai_memory(key, value, category, scope, ttl_days, created_at, updated_at)
        VALUES(:key, :value, :category, :scope, :ttl_days, :now, :now)
        ON CONFLICT(key, scope) DO UPDATE SET
            value = excluded.value,
            category = excluded.category,
            ttl_days = excluded.ttl_days,
            updated_at = excluded.updated_at
    """), {
        "key": key,
        "value": value,
        "category": category,
        "scope": scope,
        "ttl_days": ttl_days,
        "now": now,
    })
    db.commit()


def recall(db, key: str, *, scope: str = "global") -> str | None:
    """Retrieve a memory value by key and scope, or None if absent or expired."""
    _ensure_schema(db)
    row = db.execute(text("""
        SELECT key, value, category, scope, ttl_days, updated_at
        FROM ai_memory
        WHERE key = :key AND scope = :scope
    """), {"key": key, "scope": scope}).first()
    if row is None or not _is_active(row, _utc_now()):
        return None
    return row.value


def forget(db, key: str, *, scope: str = "global") -> bool:
    """Delete a memory entry by key and scope; return True if a row was removed."""
    _ensure_schema(db)
    result = db.execute(text("""
        DELETE FROM ai_memory WHERE key = :key AND scope = :scope
    """), {"key": key, "scope": scope})
    db.commit()
    return result.rowcount > 0


def list_active(
    db,
    *,
    scope: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Return all non-expired memory entries, optionally filtered by scope and category."""
    _ensure_schema(db)
    clauses = []
    params = {}
    if scope is not None:
        clauses.append("scope = :scope")
        params["scope"] = scope
    if category is not None:
        clauses.append("category = :category")
        params["category"] = category
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(text(f"""
        SELECT id, key, value, category, scope, ttl_days, created_at, updated_at
        FROM ai_memory
        {where}
        ORDER BY updated_at DESC, id DESC
    """), params).all()
    now = _utc_now()
    return [
        {
            "id": row.id,
            "key": row.key,
            "value": row.value,
            "category": row.category,
            "scope": row.scope,
            "ttl_days": row.ttl_days,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
        if _is_active(row, now)
    ]
