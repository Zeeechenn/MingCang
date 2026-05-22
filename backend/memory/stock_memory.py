"""Structured stock-memory helpers for cross-session research recall."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from backend.memory.audit_log import audit_write

MEMORY_TYPES = {
    "thesis",
    "risk",
    "event",
    "judgment",
    "outcome",
    "lesson",
    "user_preference",
    "research_pointer",
}
STATUSES = {"active", "watching", "validated", "refuted", "archived"}

_TYPE_ORDER = {
    "user_preference": 0,
    "thesis": 1,
    "risk": 2,
    "event": 3,
    "judgment": 4,
    "outcome": 5,
    "lesson": 6,
    "research_pointer": 7,
}


def _utc_now() -> datetime:
    return datetime.utcnow()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _json(value: dict | list | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _ensure_schema(db) -> None:
    bind = db.get_bind()
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                memory_type TEXT,
                summary TEXT NOT NULL,
                evidence_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                importance INTEGER DEFAULT 3,
                confidence REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                ttl_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                last_used_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_stock_memory_symbol_type
            ON stock_memory_items(symbol, memory_type)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_stock_memory_status_updated
            ON stock_memory_items(status, updated_at)
        """))


def _active(row, now: datetime) -> bool:
    if row.status == "archived":
        return False
    if row.ttl_days is None:
        return True
    try:
        updated_at = _parse_dt(row.updated_at)
    except (TypeError, ValueError):
        return True
    return updated_at + timedelta(days=int(row.ttl_days)) >= now


def _row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "memory_type": row.memory_type,
        "summary": row.summary,
        "evidence_json": row.evidence_json,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "importance": row.importance,
        "confidence": row.confidence,
        "status": row.status,
        "ttl_days": row.ttl_days,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_used_at": _iso(row.last_used_at),
    }


def _validate(memory_type: str | None = None, status: str | None = None) -> None:
    if memory_type is not None and memory_type not in MEMORY_TYPES:
        raise ValueError(f"unsupported memory_type: {memory_type}")
    if status is not None and status not in STATUSES:
        raise ValueError(f"unsupported status: {status}")


def create_stock_memory(
    db,
    *,
    symbol: str | None,
    memory_type: str,
    summary: str,
    evidence: dict | list | None = None,
    source_type: str,
    source_ref: str | None = None,
    importance: int = 3,
    confidence: float = 0.5,
    status: str = "active",
    ttl_days: int | None = None,
) -> dict:
    """Insert one structured stock-memory item and audit the write."""
    _validate(memory_type=memory_type, status=status)
    _ensure_schema(db)
    now = _utc_now().isoformat(timespec="seconds")
    result = db.execute(text("""
        INSERT INTO stock_memory_items(
            symbol, memory_type, summary, evidence_json, source_type, source_ref,
            importance, confidence, status, ttl_days, created_at, updated_at
        )
        VALUES(
            :symbol, :memory_type, :summary, :evidence_json, :source_type, :source_ref,
            :importance, :confidence, :status, :ttl_days, :now, :now
        )
    """), {
        "symbol": symbol,
        "memory_type": memory_type,
        "summary": summary.strip(),
        "evidence_json": _json(evidence),
        "source_type": source_type,
        "source_ref": source_ref,
        "importance": max(1, min(5, int(importance))),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "status": status,
        "ttl_days": ttl_days,
        "now": now,
    })
    db.commit()
    row_id = int(result.lastrowid)
    audit_write(
        db,
        "stock_memory.write",
        f"id={row_id} symbol={symbol} type={memory_type} source={source_type}",
        related_symbol=symbol,
    )
    row = db.execute(text("""
        SELECT * FROM stock_memory_items WHERE id = :id
    """), {"id": row_id}).first()
    return _row_to_dict(row)


def list_stock_memories(
    db,
    *,
    symbol: str | None = None,
    memory_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 100,
    include_archived: bool = False,
) -> list[dict]:
    """List non-expired structured stock memories with simple structured filters."""
    _validate(memory_type=memory_type, status=status)
    _ensure_schema(db)
    clauses = []
    params: dict[str, Any] = {"limit": limit}
    if symbol is not None:
        clauses.append("symbol = :symbol")
        params["symbol"] = symbol
    if memory_type is not None:
        clauses.append("memory_type = :memory_type")
        params["memory_type"] = memory_type
    if status is not None:
        clauses.append("status = :status")
        params["status"] = status
    elif not include_archived:
        clauses.append("status != 'archived'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(text(f"""
        SELECT *
        FROM stock_memory_items
        {where}
        ORDER BY importance DESC, updated_at DESC, id DESC
        LIMIT :limit
    """), params).all()
    now = _utc_now()
    ql = q.lower() if q else None
    out = []
    for row in rows:
        if not _active(row, now):
            continue
        if ql:
            haystack = " ".join(str(v or "") for v in (
                row.symbol, row.memory_type, row.summary, row.evidence_json, row.source_ref,
            )).lower()
            if ql not in haystack:
                continue
        out.append(_row_to_dict(row))
    return out


def patch_stock_memory(
    db,
    row_id: int,
    *,
    status: str | None = None,
    importance: int | None = None,
    ttl_days: int | None = None,
    clear_ttl: bool = False,
) -> dict:
    """Patch governance metadata only; raw summary/evidence stays immutable."""
    _validate(status=status)
    _ensure_schema(db)
    row = db.execute(text("SELECT * FROM stock_memory_items WHERE id = :id"), {"id": row_id}).first()
    if row is None:
        raise KeyError(row_id)
    sets: list[str] = ["updated_at = :now"]
    params: dict[str, Any] = {"id": row_id, "now": _utc_now().isoformat(timespec="seconds")}
    if status is not None:
        sets.append("status = :status")
        params["status"] = status
    if importance is not None:
        sets.append("importance = :importance")
        params["importance"] = max(1, min(5, int(importance)))
    if clear_ttl:
        sets.append("ttl_days = NULL")
    elif ttl_days is not None:
        sets.append("ttl_days = :ttl_days")
        params["ttl_days"] = ttl_days
    if len(sets) == 1:
        raise ValueError("no editable fields supplied")
    db.execute(text(f"""
        UPDATE stock_memory_items SET {', '.join(sets)} WHERE id = :id
    """), params)
    db.commit()
    audit_write(
        db,
        "stock_memory.patch",
        f"id={row_id} sets={sets}",
        related_symbol=row.symbol,
    )
    updated = db.execute(text("SELECT * FROM stock_memory_items WHERE id = :id"), {"id": row_id}).first()
    return _row_to_dict(updated)


def archive_stock_memory(db, row_id: int) -> dict:
    return patch_stock_memory(db, row_id, status="archived")


def delete_stock_memory(db, row_id: int) -> bool:
    _ensure_schema(db)
    row = db.execute(text("SELECT * FROM stock_memory_items WHERE id = :id"), {"id": row_id}).first()
    if row is None:
        raise KeyError(row_id)
    result = db.execute(text("DELETE FROM stock_memory_items WHERE id = :id"), {"id": row_id})
    db.commit()
    audit_write(
        db,
        "stock_memory.delete",
        f"id={row_id} removed={result.rowcount > 0}",
        related_symbol=row.symbol,
    )
    return result.rowcount > 0


def _score_row(row: dict, *, symbol: str | None, query: str | None) -> tuple:
    symbol_score = 2 if symbol and row["symbol"] == symbol else 0
    query_score = 0
    if query:
        ql = query.lower()
        haystack = " ".join(str(row.get(k) or "") for k in ("summary", "evidence_json", "source_ref")).lower()
        query_score = 1 if any(part and part in haystack for part in ql.split()) else 0
    return (
        _TYPE_ORDER.get(row["memory_type"], 99),
        -symbol_score,
        -query_score,
        -int(row["importance"] or 0),
        str(row["updated_at"] or ""),
    )


def _ai_memory_context(db, *, symbol: str | None, query: str | None, limit: int) -> tuple[list[str], list[str]]:
    from backend.memory.ai_memory import list_active

    lines: list[str] = []
    keys: list[str] = []
    for row in list_active(db):
        category = row.get("category")
        scope = row.get("scope")
        value = row.get("value") or ""
        key = row.get("key") or ""
        if category in {"preference", "rule", "risk"}:
            lines.append(f"- [{category}|{scope}] {value}")
            keys.append(key)
        elif scope == "research" and category == "deep_research":
            if (symbol and symbol in value) or (query and query.lower() in (key + value).lower()):
                lines.append(f"- [research] {value[:220]}")
                keys.append(key)
        if len(lines) >= limit:
            break
    return lines, keys


def build_memory_context(
    db,
    *,
    symbol: str | None = None,
    query: str | None = None,
    task_type: str = "research",
    limit: int = 8,
) -> dict:
    """Build a compact prompt-ready memory context across project entry points."""
    try:
        stock_rows = list_stock_memories(db, symbol=symbol, limit=max(limit * 3, 20))
    except OperationalError:
        stock_rows = []
    stock_rows = sorted(stock_rows, key=lambda r: _score_row(r, symbol=symbol, query=query))[:limit]

    ai_lines, ai_keys = _ai_memory_context(db, symbol=symbol, query=query, limit=4)
    stock_lines = [
        f"- [{r['memory_type']}|重要{r['importance']}|{r['status']}] {r['summary']}"
        for r in stock_rows
    ]
    parts: list[str] = []
    if ai_lines:
        parts.append("【用户偏好 / 项目规则 / 研究索引】\n" + "\n".join(ai_lines))
    if stock_lines:
        title = f"【{symbol} 股票长期记忆】" if symbol else "【股票长期记忆】"
        parts.append(title + "\n" + "\n".join(stock_lines))

    layered_text = ""
    if symbol:
        try:
            from backend.decision.memory_layered import get_layered_context
            layered_text = get_layered_context(symbol, db)
        except Exception:
            layered_text = ""
    if layered_text:
        parts.append(layered_text.strip())

    text_value = "\n\n".join(parts)
    used_ids = [int(r["id"]) for r in stock_rows]
    if used_ids:
        now = _utc_now().isoformat(timespec="seconds")
        db.execute(text(
            f"UPDATE stock_memory_items SET last_used_at = :now WHERE id IN ({','.join(str(i) for i in used_ids)})"
        ), {"now": now})
        db.commit()
    audit_write(
        db,
        "stock_memory.recall",
        f"symbol={symbol} task_type={task_type} empty={not bool(text_value)} "
        f"stock_ids={used_ids} ai_keys={ai_keys}",
        related_symbol=symbol,
    )
    return {
        "symbol": symbol,
        "task_type": task_type,
        "text": text_value,
        "used_stock_memory_ids": used_ids,
        "ai_memory_keys": ai_keys,
    }


def _existing_source_ref(db, source_ref: str) -> bool:
    row = db.execute(text("""
        SELECT id FROM stock_memory_items WHERE source_ref = :source_ref LIMIT 1
    """), {"source_ref": source_ref}).first()
    return row is not None


def update_judgment_outcomes(db, *, symbol: str | None = None) -> int:
    """Create outcome/lesson memories for judgment rows that have enough later prices."""
    from backend.decision.signal_policy import is_entry_signal

    _ensure_schema(db)
    clauses = ["memory_type = 'judgment'", "status != 'archived'"]
    params: dict[str, Any] = {}
    if symbol:
        clauses.append("symbol = :symbol")
        params["symbol"] = symbol
    rows = db.execute(text(f"""
        SELECT * FROM stock_memory_items
        WHERE {' AND '.join(clauses)}
        ORDER BY id ASC
    """), params).all()
    written = 0
    for row in rows:
        source_ref = f"outcome:{row.id}"
        if _existing_source_ref(db, source_ref):
            continue
        try:
            evidence = json.loads(row.evidence_json or "{}")
        except json.JSONDecodeError:
            evidence = {}
        decision_date = evidence.get("date")
        recommendation = evidence.get("recommendation") or ""
        if not row.symbol or not decision_date:
            continue
        prices = db.execute(text("""
            SELECT date, close FROM prices
            WHERE symbol = :symbol AND date >= :date
            ORDER BY date ASC
            LIMIT 11
        """), {"symbol": row.symbol, "date": decision_date}).all()
        if len(prices) < 2 or not prices[0].close:
            continue
        base = float(prices[0].close)
        offsets = [1, 3, 5, 10]
        returns = {}
        for offset in offsets:
            if len(prices) > offset and prices[offset].close is not None:
                returns[f"{offset}d"] = round((float(prices[offset].close) - base) / base * 100, 2)
        if not returns:
            continue
        summary_bits = "，".join(f"{k}{v:+.2f}%" for k, v in returns.items())
        create_stock_memory(
            db,
            symbol=row.symbol,
            memory_type="outcome",
            summary=f"{decision_date} 判断后表现：{summary_bits}",
            evidence={"judgment_id": row.id, "returns": returns, "recommendation": recommendation},
            source_type="outcome_update",
            source_ref=source_ref,
            importance=3,
            confidence=0.7,
            status="validated",
        )
        written += 1

        latest_return = next((returns[k] for k in ("10d", "5d", "3d", "1d") if k in returns), None)
        if latest_return is not None and is_entry_signal(recommendation, include_legacy=True) and latest_return < 0:
            lesson_ref = f"lesson:{row.id}"
            if not _existing_source_ref(db, lesson_ref):
                create_stock_memory(
                    db,
                    symbol=row.symbol,
                    memory_type="lesson",
                    summary=f"{decision_date} 正向判断后表现为负，后续同类信号需复核技术确认与新闻兑现。",
                    evidence={"judgment_id": row.id, "latest_return": latest_return},
                    source_type="outcome_update",
                    source_ref=lesson_ref,
                    importance=4,
                    confidence=0.6,
                    status="watching",
                )
                written += 1
    return written
