"""Memory health audit and reversible maintenance operations."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError

from backend.memory.audit_log import audit_write


def _scalar(db, sql: str, params: dict[str, Any] | None = None) -> int:
    try:
        return int(db.execute(text(sql), params or {}).scalar() or 0)
    except OperationalError:
        return 0


def memory_health_snapshot(db, *, memory_dir: Path | None = None) -> dict[str, Any]:
    """Measure whether stored rows have become validated, prompt-eligible experience."""
    memory_dir = memory_dir or (Path.home() / ".mingcang" / "memory")
    judgments = _scalar(db, "SELECT count(*) FROM stock_memory_items WHERE memory_type='judgment'")
    active_judgments = _scalar(
        db,
        "SELECT count(*) FROM stock_memory_items "
        "WHERE memory_type='judgment' AND status!='archived'",
    )
    outcomes = _scalar(
        db,
        "SELECT count(*) FROM stock_memory_items "
        "WHERE memory_type='outcome' AND status='validated'",
    )
    resolved = _scalar(db, """
        SELECT count(*)
        FROM stock_memory_items j
        WHERE j.memory_type='judgment'
          AND EXISTS (
              SELECT 1 FROM stock_memory_items o
              WHERE o.source_ref = 'outcome:' || j.id
          )
    """)
    trusted_atoms = _scalar(
        db,
        "SELECT count(*) FROM memory_atoms WHERE trust_state='trusted'",
    )
    recall_rows = _scalar(
        db,
        "SELECT count(*) FROM memory_recall_index WHERE source='stock_memory_items'",
    )
    active_source_rows = _scalar(db, """
        SELECT count(*) FROM stock_memory_items WHERE status!='archived'
    """)
    recall_missing = _scalar(db, """
        SELECT count(*)
        FROM stock_memory_items s
        LEFT JOIN memory_recall_index idx
          ON idx.source='stock_memory_items' AND idx.source_id=CAST(s.id AS TEXT)
        WHERE s.status!='archived' AND idx.id IS NULL
    """)
    recall_stale = _scalar(db, """
        SELECT count(*)
        FROM memory_recall_index idx
        LEFT JOIN stock_memory_items s
          ON idx.source='stock_memory_items' AND idx.source_id=CAST(s.id AS TEXT)
        WHERE idx.source='stock_memory_items'
          AND (s.id IS NULL OR s.status='archived')
    """)
    unresolvable = _scalar(db, """
        SELECT count(*)
        FROM stock_memory_items j
        WHERE j.memory_type='judgment'
          AND NOT EXISTS (
              SELECT 1 FROM stock_memory_items o
              WHERE o.source_ref='outcome:' || j.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          )
          AND (
              SELECT count(*) FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date>=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          ) >= 11
    """)
    active_unresolvable = _scalar(db, """
        SELECT count(*)
        FROM stock_memory_items j
        WHERE j.memory_type='judgment'
          AND j.status!='archived'
          AND NOT EXISTS (
              SELECT 1 FROM stock_memory_items o
              WHERE o.source_ref='outcome:' || j.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          )
          AND (
              SELECT count(*) FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date>=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          ) >= 11
    """)
    mature_unresolved = _scalar(db, """
        SELECT count(*)
        FROM stock_memory_items j
        WHERE j.memory_type='judgment'
          AND NOT EXISTS (
              SELECT 1 FROM stock_memory_items o
              WHERE o.source_ref='outcome:' || j.id
          )
          AND EXISTS (
              SELECT 1 FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          )
          AND (
              SELECT count(*) FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date>=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          ) >= 11
    """)
    resolvable = max(0, judgments - unresolvable)
    plain = {path.stem for path in memory_dir.glob("*.md") if not path.name.startswith("medium_")}
    medium = {
        path.stem.removeprefix("medium_")
        for path in memory_dir.glob("medium_*.md")
    }
    return {
        "judgments_total": judgments,
        "judgments_active": active_judgments,
        "validated_outcomes": outcomes,
        "resolved_judgments": resolved,
        "outcome_coverage": round(outcomes / judgments, 4) if judgments else 0.0,
        "resolvable_outcome_coverage": round(outcomes / resolvable, 4) if resolvable else 0.0,
        "unresolvable_judgments": unresolvable,
        "active_unresolvable_judgments": active_unresolvable,
        "mature_unresolved_judgments": mature_unresolved,
        "trusted_memory_atoms": trusted_atoms,
        "indexed_stock_memory_rows": recall_rows,
        "active_stock_memory_rows": active_source_rows,
        "recall_index_gap": recall_missing,
        "recall_index_stale_rows": recall_stale,
        "recall_index_exact": recall_missing == 0 and recall_stale == 0,
        "duplicate_legacy_markdown_pairs": len(plain & medium),
    }


def archive_resolved_judgments(db, *, retention_days: int = 30) -> int:
    """Archive old raw judgments once a validated outcome exists.

    Archiving is reversible and keeps the audit/outcome lineage intact while
    preventing raw signal logs from crowding prompt recall.
    """
    cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=retention_days)).isoformat(
        timespec="seconds"
    )
    rows = db.execute(text("""
        SELECT j.id
        FROM stock_memory_items j
        WHERE j.memory_type='judgment'
          AND j.status!='archived'
          AND j.created_at < :cutoff
          AND EXISTS (
              SELECT 1 FROM stock_memory_items o
              WHERE o.source_ref = 'outcome:' || j.id
                AND o.status = 'validated'
          )
        ORDER BY j.id ASC
    """), {"cutoff": cutoff}).all()
    ids = [int(row.id) for row in rows]
    if not ids:
        return 0
    stmt = text("""
        UPDATE stock_memory_items
        SET status='archived'
        WHERE id IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    db.execute(stmt, {"ids": ids})
    db.commit()
    audit_write(
        db,
        "stock_memory.maintenance",
        f"archived_resolved_judgments={len(ids)} retention_days={retention_days}",
        related_scope="memory",
    )
    return len(ids)


def archive_unresolvable_judgments(db) -> int:
    """Reversibly archive mature judgments whose date is not a trading session.

    These rows can never satisfy the outcome contract because there is no exact
    decision-date close.  We fail closed instead of silently rebasing them to a
    prior or later bar, which would change the historical decision.
    """
    rows = db.execute(text("""
        SELECT j.id
        FROM stock_memory_items j
        WHERE j.memory_type='judgment'
          AND j.status!='archived'
          AND NOT EXISTS (
              SELECT 1 FROM stock_memory_items o
              WHERE o.source_ref='outcome:' || j.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          )
          AND (
              SELECT count(*) FROM prices p
              WHERE p.symbol=j.symbol
                AND p.date>=substr(json_extract(j.evidence_json, '$.date'), 1, 10)
          ) >= 11
        ORDER BY j.id
    """)).all()
    ids = [int(row.id) for row in rows]
    if not ids:
        return 0
    stmt = text("""
        UPDATE stock_memory_items SET status='archived' WHERE id IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    db.execute(stmt, {"ids": ids})
    db.commit()
    audit_write(
        db,
        "stock_memory.maintenance",
        f"archived_unresolvable_judgments={len(ids)} reason=no_exact_decision_date_price",
        related_scope="memory",
    )
    return len(ids)


def normalize_research_pointer_topics(db) -> int:
    """Add the durable research topic to legacy per-symbol pointer summaries."""
    rows = db.execute(text("""
        SELECT id, symbol, summary, evidence_json
        FROM stock_memory_items
        WHERE memory_type='research_pointer'
          AND source_type='deep_research'
          AND status!='archived'
    """)).all()
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    changed = 0
    for row in rows:
        if "《" in str(row.summary or ""):
            continue
        try:
            evidence = json.loads(row.evidence_json or "{}")
        except json.JSONDecodeError:
            continue
        topic = str(evidence.get("topic") or "").strip()
        if not topic:
            continue
        summary = str(row.summary or "")
        body = summary.split("研究索引：", 1)[-1].strip()
        normalized = f"{row.symbol} 研究索引《{topic}》：{body}"
        db.execute(text("""
            UPDATE stock_memory_items
            SET summary=:summary, updated_at=:now
            WHERE id=:id
        """), {"summary": normalized, "now": now, "id": row.id})
        changed += 1
    if changed:
        db.commit()
        audit_write(
            db,
            "stock_memory.maintenance",
            f"normalized_research_pointer_topics={changed}",
            related_scope="memory",
        )
    return changed


def run_memory_maintenance(db, *, retention_days: int = 30) -> dict[str, Any]:
    """Backfill outcomes, archive resolved/invalid raw logs, and sync recall."""
    from backend.memory.recall import sync_recall_index
    from backend.memory.stock_memory import update_judgment_outcomes

    before = memory_health_snapshot(db)
    memory_rows_written = update_judgment_outcomes(db)
    judgments_archived = archive_resolved_judgments(db, retention_days=retention_days)
    unresolvable_archived = archive_unresolvable_judgments(db)
    research_pointers_normalized = normalize_research_pointer_topics(db)
    sync_recall_index(db)
    after = memory_health_snapshot(db)
    return {
        "memory_rows_written": memory_rows_written,
        "validated_outcomes_added": (
            after["validated_outcomes"] - before["validated_outcomes"]
        ),
        "judgments_archived": judgments_archived,
        "unresolvable_judgments_archived": unresolvable_archived,
        "research_pointers_normalized": research_pointers_normalized,
        "before": before,
        "after": after,
    }
