"""Layer 2 persistent memory helpers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from backend.memory.audit_log import audit_write
from backend.memory.should_remember import should_remember


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC).replace(tzinfo=None)


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
    force: bool = False,
) -> bool:
    """Upsert a key-value memory entry with optional TTL.

    Gated by `should_remember(value, category)` unless `force=True`. Returns
    True when persisted, False when rejected by the gate. Both outcomes write
    an audit log entry (`memory.write` or `memory.skipped`).
    """
    _ensure_schema(db)
    if not force and not should_remember(value, category=category):
        audit_write(
            db,
            "memory.skipped",
            f"key={key} scope={scope} category={category}: rejected by should_remember",
            related_scope=scope,
        )
        return False
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
    audit_write(
        db,
        "memory.write",
        f"key={key} scope={scope} category={category} ttl_days={ttl_days}",
        related_scope=scope,
    )
    return True


def recall(db, key: str, *, scope: str = "global") -> str | None:
    """Retrieve a memory value by key and scope, or None if absent or expired.

    Hits are audited as `memory.recall`. Misses are not audited (would be
    high-volume noise from postmarket scans).
    """
    _ensure_schema(db)
    row = db.execute(text("""
        SELECT key, value, category, scope, ttl_days, updated_at
        FROM ai_memory
        WHERE key = :key AND scope = :scope
    """), {"key": key, "scope": scope}).first()
    if row is None or not _is_active(row, _utc_now()):
        return None
    audit_write(
        db,
        "memory.recall",
        f"key={key} scope={scope}",
        related_scope=scope,
    )
    return row.value


def forget(db, key: str, *, scope: str = "global") -> bool:
    """Delete a memory entry by key and scope; return True if a row was removed."""
    _ensure_schema(db)
    result = db.execute(text("""
        DELETE FROM ai_memory WHERE key = :key AND scope = :scope
    """), {"key": key, "scope": scope})
    db.commit()
    audit_write(
        db,
        "memory.forget",
        f"key={key} scope={scope} removed={result.rowcount > 0}",
        related_scope=scope,
    )
    return result.rowcount > 0


def expire_stale_memories(db) -> int:
    """M9.3 daily cleanup: delete rows past their TTL, audit each removal.

    Audits with event `memory.expire` and the row's full value so the row can
    be reconstructed from `audit_log_fts` within the audit retention window
    (and from daily backups longer-term). Returns count deleted.
    """
    _ensure_schema(db)
    now = _utc_now()
    rows = db.execute(text("""
        SELECT id, key, value, scope, category, ttl_days, updated_at
        FROM ai_memory
        WHERE ttl_days IS NOT NULL
    """)).all()
    removed = 0
    for r in rows:
        if _is_active(r, now):
            continue
        db.execute(text("DELETE FROM ai_memory WHERE id = :id"), {"id": r.id})
        audit_write(
            db,
            "memory.expire",
            f"id={r.id} key={r.key} scope={r.scope} category={r.category} "
            f"ttl_days={r.ttl_days} value={r.value}",
            related_scope=r.scope,
        )
        removed += 1
    if removed:
        db.commit()
    return removed


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
