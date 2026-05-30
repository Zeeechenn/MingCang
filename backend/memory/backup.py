"""Daily backup dump of ai_memory to a dated JSON file (M9.横向).

Layered decision memory (`~/.stock-sage/memory/medium_*.md`,
`long_term_reflection.md`) is **not** dumped here — those files are themselves
the source of truth and live on disk. Once M9.1 migrates them into a DB
table, extend `run_daily_backup` to dump that table as well.

Layout:
  ~/.stock-sage/memory/backups/ai_memory_{YYYY-MM-DD}.json

Retention: drop backup files older than `keep_days` (default 30) on each run.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

DEFAULT_BACKUP_DIR = Path.home() / ".stock-sage" / "memory" / "backups"
DEFAULT_KEEP_DAYS = 30
SCHEMA_VERSION = 1


def _iso(value) -> str | None:
    """Coerce a SQLAlchemy datetime/str column to an ISO string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def dump_ai_memory(db, out_path: Path) -> int:
    """Write every `ai_memory` row (including expired) to a JSON file.

    Backups intentionally include expired rows so that a delete-by-mistake can
    be recovered before TTL would have hidden the row anyway.

    Returns the number of rows written.
    """
    rows = db.execute(text("""
        SELECT id, key, value, category, scope, ttl_days, created_at, updated_at
        FROM ai_memory
        ORDER BY id ASC
    """)).all()
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "rows": [
            {
                "id": r.id,
                "key": r.key,
                "value": r.value,
                "category": r.category,
                "scope": r.scope,
                "ttl_days": r.ttl_days,
                "created_at": _iso(r.created_at),
                "updated_at": _iso(r.updated_at),
            }
            for r in rows
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    return len(payload["rows"])


def cleanup_old_backups(backup_dir: Path, keep_days: int = DEFAULT_KEEP_DAYS) -> int:
    """Delete `ai_memory_*.json` files older than `keep_days`. Returns count deleted."""
    if not backup_dir.exists():
        return 0
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=keep_days)
    removed = 0
    for path in backup_dir.glob("ai_memory_*.json"):
        try:
            stamp = path.stem.removeprefix("ai_memory_")
            file_date = datetime.strptime(stamp, "%Y-%m-%d")
        except ValueError:
            continue  # ignore files that don't match the naming pattern
        if file_date < cutoff:
            path.unlink()
            removed += 1
    return removed


def run_daily_backup(
    db,
    *,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    keep_days: int = DEFAULT_KEEP_DAYS,
    today: str | None = None,
) -> Path:
    """Dump today's `ai_memory` snapshot and prune old backups.

    Audits the dump (`memory.backup`) so the operator can verify in the audit
    log that the daily job ran. Returns the path that was written.
    """
    from backend.memory.audit_log import audit_write

    date_str = today or datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
    out_path = backup_dir / f"ai_memory_{date_str}.json"
    written = dump_ai_memory(db, out_path)
    removed = cleanup_old_backups(backup_dir, keep_days=keep_days)
    audit_write(
        db,
        "memory.backup",
        f"path={out_path} rows={written} pruned={removed} keep_days={keep_days}",
    )
    return out_path
