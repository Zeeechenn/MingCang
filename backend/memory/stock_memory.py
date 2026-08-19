"""Structured stock-memory helpers for cross-session research recall."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError

from backend.memory.audit_log import audit_write

logger = logging.getLogger(__name__)

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
    "risk": 1,
    "lesson": 2,
    "outcome": 3,
    "thesis": 4,
    "event": 5,
    "judgment": 6,
    "research_pointer": 7,
}

_SUPPRESS_USAGE_RECORDING: ContextVar[bool] = ContextVar(
    "stock_memory_suppress_usage_recording",
    default=False,
)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@contextmanager
def suppress_memory_usage_recording():
    """Temporarily make memory recall read-only for nested context builders."""
    token = _SUPPRESS_USAGE_RECORDING.set(True)
    try:
        yield
    finally:
        _SUPPRESS_USAGE_RECORDING.reset(token)


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


def _id_by_source_ref(db, source_ref: str) -> int | None:
    """Return the id of an existing memory row with this source_ref, or None."""
    row = db.execute(text(
        "SELECT id FROM stock_memory_items WHERE source_ref = :source_ref "
        "ORDER BY id ASC LIMIT 1"
    ), {"source_ref": source_ref}).first()
    return int(row.id) if row else None


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
    """Insert or upsert one structured stock-memory item and audit the write.

    ``source_ref`` is the idempotency key: when it is provided and a row with
    that ref already exists, the existing row is updated in place (id and
    created_at preserved) instead of inserting a duplicate. This keeps
    re-runnable writers — postmarket judgments, deep-research candidates,
    outcome backfill — from accumulating duplicate rows on re-run.
    """
    _validate(memory_type=memory_type, status=status)
    _ensure_schema(db)
    now = _utc_now().isoformat(timespec="seconds")
    params = {
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
    }
    existing_id = _id_by_source_ref(db, source_ref) if source_ref else None
    if existing_id is not None:
        params["id"] = existing_id
        db.execute(text("""
            UPDATE stock_memory_items SET
                symbol = :symbol, memory_type = :memory_type, summary = :summary,
                evidence_json = :evidence_json, source_type = :source_type,
                importance = :importance, confidence = :confidence,
                status = :status, ttl_days = :ttl_days, updated_at = :now
            WHERE id = :id
        """), params)
        db.commit()
        row_id = existing_id
        mode = "upsert"
    else:
        result = db.execute(text("""
            INSERT INTO stock_memory_items(
                symbol, memory_type, summary, evidence_json, source_type, source_ref,
                importance, confidence, status, ttl_days, created_at, updated_at
            )
            VALUES(
                :symbol, :memory_type, :summary, :evidence_json, :source_type, :source_ref,
                :importance, :confidence, :status, :ttl_days, :now, :now
            )
        """), params)
        db.commit()
        row_id = int(result.lastrowid)
        mode = "insert"
    audit_write(
        db,
        "stock_memory.write",
        f"id={row_id} symbol={symbol} type={memory_type} source={source_type} mode={mode}",
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
    if q:
        clauses.append("""(
            lower(coalesce(symbol, '')) LIKE :query
            OR lower(coalesce(memory_type, '')) LIKE :query
            OR lower(coalesce(summary, '')) LIKE :query
            OR lower(coalesce(evidence_json, '')) LIKE :query
            OR lower(coalesce(source_ref, '')) LIKE :query
        )""")
        params["query"] = f"%{q.lower()}%"
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT *
        FROM stock_memory_items
        {where}
        ORDER BY importance DESC, updated_at DESC, id DESC
        LIMIT :limit
    """  # noqa: S608 - WHERE fragments come only from the fixed filters above.
    rows = db.execute(text(query), params).all()
    now = _utc_now()
    out = []
    for row in rows:
        if not _active(row, now):
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
    sets: list[str] = []
    params: dict[str, Any] = {"id": row_id}
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
    if not sets:
        raise ValueError("no editable fields supplied")
    query = "UPDATE stock_memory_items SET " + ", ".join(sets) + " WHERE id = :id"  # noqa: S608
    db.execute(text(query), params)
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
        query_score = sum(1 for part in ql.split() if part and part in haystack)
    try:
        updated_score = _parse_dt(row.get("updated_at")).timestamp()
    except (TypeError, ValueError):
        updated_score = 0.0
    return (
        -symbol_score,
        -query_score,
        _TYPE_ORDER.get(row["memory_type"], 99),
        -int(row["importance"] or 0),
        -updated_score,
    )


def _select_prompt_rows(
    rows: list[dict],
    *,
    symbol: str | None,
    query: str | None,
    limit: int,
    has_calibration: bool,
    has_recent_reflection: bool,
) -> list[dict]:
    """Keep a diverse, quality-first prompt set instead of a signal-log dump."""
    caps = {
        "user_preference": 2,
        "risk": 2,
        "lesson": 2,
        "outcome": 0 if has_calibration else 2,
        "thesis": 2,
        "event": 1,
        "research_pointer": 1,
        "judgment": 0 if (has_calibration or has_recent_reflection) else 1,
    }
    selected: list[dict] = []
    used_per_type: dict[str, int] = {}
    for row in sorted(rows, key=lambda item: _score_row(item, symbol=symbol, query=query)):
        memory_type = str(row.get("memory_type") or "")
        if used_per_type.get(memory_type, 0) >= caps.get(memory_type, 1):
            continue
        selected.append(row)
        used_per_type[memory_type] = used_per_type.get(memory_type, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _ai_memory_relevant(row: dict, *, symbol: str | None, query: str | None) -> bool:
    if symbol is None:
        return True
    category = row.get("category")
    value = row.get("value") or ""
    key = row.get("key") or ""
    haystack = f"{key} {value}".lower()
    if symbol in haystack:
        return True
    if query:
        parts = [part for part in query.lower().split() if part]
        if any(part in haystack for part in parts):
            return True
    if category in {"rule", "risk"}:
        return True
    broad_preference_hints = ("不追高", "仓位", "止损", "止盈", "回撤", "高负债")
    if category == "preference" and any(hint in value for hint in broad_preference_hints):
        return True
    return False


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
            if not _ai_memory_relevant(row, symbol=symbol, query=query):
                continue
            lines.append(f"- [{category}|{scope}] {value}")
            keys.append(key)
        elif symbol is None and scope == "research" and category == "deep_research":
            if (symbol and symbol in value) or (query and query.lower() in (key + value).lower()):
                lines.append(f"- [research] {value[:220]}")
                keys.append(key)
        if len(lines) >= limit:
            break
    return lines, keys


def _empty_l0_context() -> dict:
    return {
        "text": "",
        "trusted_memory": [],
        "pending_memory": [],
        "legacy_memory": [],
        "scenario_summaries": [],
        "profile_summaries": [],
        "drilldown_refs": [],
        "used_memory_atom_ids": [],
    }


def build_memory_context(
    db,
    *,
    symbol: str | None = None,
    query: str | None = None,
    task_type: str = "research",
    limit: int = 8,
    record_usage: bool = True,
    include_l0: bool | None = None,
) -> dict:
    """Build a compact prompt-ready memory context across project entry points."""
    record_usage = record_usage and not _SUPPRESS_USAGE_RECORDING.get()
    if include_l0 is None:
        from backend.config import settings
        include_l0 = settings.atlas_enabled
    l0_context = _empty_l0_context()
    if include_l0:
        try:
            from backend.memory.l0_memory import build_l0_context
            l0_context = build_l0_context(
                db,
                scope_type="stock" if symbol else None,
                scope_key=symbol,
                query=query,
                limit=limit,
                include_pending=True,
                include_legacy=False,
                record_usage=record_usage,
            )
        except Exception:
            logger.warning("stock_memory.build_memory_context: building L0 context failed, using fallback", exc_info=True)
            l0_context = _empty_l0_context()
    try:
        stock_candidates = list_stock_memories(
            db,
            symbol=symbol,
            limit=max(limit * 12, 100),
        )
    except OperationalError:
        stock_candidates = []

    calibration: dict[str, Any] = {"text": "", "memory_ids": [], "sample_count": 0}
    if symbol:
        try:
            from backend.memory.experience import build_outcome_calibration

            calibration = build_outcome_calibration(db, symbol=symbol)
        except OperationalError:
            calibration = {"text": "", "memory_ids": [], "sample_count": 0}

    layered_text = ""
    if symbol:
        try:
            from backend.decision.memory_layered import get_layered_context
            layered_text = get_layered_context(symbol, db, record_usage=record_usage)
        except Exception:
            logger.warning("stock_memory.build_memory_context: reading layered memory failed, using fallback", exc_info=True)
            layered_text = ""

    stock_rows = _select_prompt_rows(
        stock_candidates,
        symbol=symbol,
        query=query,
        limit=limit,
        has_calibration=bool(calibration.get("text")),
        has_recent_reflection=any(
            marker in layered_text
            for marker in ("【历史决策复盘", "【长期反思】")
        ),
    )

    ai_lines, ai_keys = _ai_memory_context(db, symbol=symbol, query=query, limit=4)
    stock_lines = [
        f"- [{r['memory_type']}|重要{r['importance']}|{r['status']}] {r['summary']}"
        for r in stock_rows
    ]
    parts: list[str] = []
    if ai_lines:
        parts.append("【用户偏好 / 项目规则 / 研究索引】\n" + "\n".join(ai_lines))
    if l0_context.get("text"):
        parts.append(l0_context["text"])
    if calibration.get("text"):
        parts.append(str(calibration["text"]))
    if stock_lines:
        title = f"【{symbol} 股票长期记忆】" if symbol else "【股票长期记忆】"
        parts.append(title + "\n" + "\n".join(stock_lines))
    if layered_text:
        parts.append(layered_text.strip())

    text_value = "\n\n".join(parts)
    used_ids = list(dict.fromkeys([
        *[int(r["id"]) for r in stock_rows],
        *[int(row_id) for row_id in calibration.get("memory_ids", [])],
    ]))
    if record_usage and used_ids:
        now = _utc_now().isoformat(timespec="seconds")
        stmt = text(
            "UPDATE stock_memory_items SET last_used_at = :now WHERE id IN :used_ids"
        ).bindparams(bindparam("used_ids", expanding=True))
        db.execute(stmt, {"now": now, "used_ids": used_ids})
        db.commit()
    if record_usage:
        audit_write(
            db,
            "stock_memory.recall",
            f"symbol={symbol} task_type={task_type} empty={not bool(text_value)} "
            f"stock_ids={used_ids[:12]} stock_count={len(used_ids)} "
            f"outcome_samples={calibration.get('sample_count', 0)} ai_keys={ai_keys}",
            related_symbol=symbol,
        )
    return {
        "symbol": symbol,
        "task_type": task_type,
        "text": text_value,
        "used_stock_memory_ids": used_ids,
        "ai_memory_keys": ai_keys,
        "used_memory_atom_ids": l0_context.get("used_memory_atom_ids", []),
        "l0_context": l0_context,
        "outcome_sample_count": int(calibration.get("sample_count", 0)),
    }


def build_decision_memory_context(
    db,
    *,
    symbol: str | None = None,
    query: str | None = None,
    task_type: str = "research",
    limit: int = 8,
    record_usage: bool = True,
    include_l0: bool | None = None,
) -> dict:
    """Return memory only when its production decision gate is promoted.

    Outcome accrual, maintenance, explicit memory inspection, and PIT replay
    continue to use their dedicated paths.  This helper is intentionally used
    by prompt/signal consumers so the default shadow-only mode cannot leak a
    remembered prior into AI judgment or official action.
    """
    from backend.config import settings

    if not settings.memory_decision_context_enabled:
        return {
            "symbol": symbol,
            "task_type": task_type,
            "text": "",
            "used_stock_memory_ids": [],
            "ai_memory_keys": [],
            "used_memory_atom_ids": [],
            "l0_context": _empty_l0_context(),
            "outcome_sample_count": 0,
            "memory_mode": "shadow_only",
            "decision_context_enabled": False,
            "suppression_reason": "corrected_pit_replay_not_promoted",
        }

    context = build_memory_context(
        db,
        symbol=symbol,
        query=query,
        task_type=task_type,
        limit=limit,
        record_usage=record_usage,
        include_l0=include_l0,
    )
    return {
        **context,
        "memory_mode": "decision_context_enabled",
        "decision_context_enabled": True,
        "suppression_reason": None,
    }


def update_judgment_outcomes(db, *, symbol: str | None = None) -> int:
    """Create outcome/lesson memories for judgment rows with a full 10-day horizon.

    An outcome is only written once the decision has at least 10 later trading
    days of prices, so the 1d/3d/5d/10d return picture is complete before the
    row is frozen as ``validated`` (and never silently stuck at a 1-day view).
    """
    from backend.decision.signal_policy import is_entry_signal

    _ensure_schema(db)
    clauses = [
        "j.memory_type = 'judgment'",
        "j.status != 'archived'",
        "NOT EXISTS ("
        "SELECT 1 FROM stock_memory_items o WHERE o.source_ref = 'outcome:' || j.id"
        ")",
    ]
    params: dict[str, Any] = {}
    if symbol:
        clauses.append("j.symbol = :symbol")
        params["symbol"] = symbol
    query = f"""
        SELECT j.* FROM stock_memory_items j
        WHERE {' AND '.join(clauses)}
        ORDER BY j.id ASC
    """  # noqa: S608 - clauses are fixed literals plus a bound symbol predicate.
    rows = db.execute(text(query), params).all()
    written = 0
    for row in rows:
        source_ref = f"outcome:{row.id}"
        try:
            evidence = json.loads(row.evidence_json or "{}")
        except json.JSONDecodeError:
            evidence = {}
        decision_date = str(evidence.get("date") or "")[:10]
        recommendation = evidence.get("recommendation") or ""
        if not row.symbol or len(decision_date) != 10:
            continue
        prices = db.execute(text("""
            SELECT date, close FROM prices
            WHERE symbol = :symbol AND date >= :date
            ORDER BY date ASC
            LIMIT 11
        """), {"symbol": row.symbol, "date": decision_date}).all()
        if len(prices) < 11 or prices[0].date != decision_date or not prices[0].close:
            continue
        # M15.3 outcome 基准化：用沪深 300 同期收益做相对强弱判断，避免 A 股高 beta
        # 大盘下跌日把所有正向判断系统性记为"失败"
        bench_rows = db.execute(text("""
            SELECT date, close FROM index_prices
            WHERE symbol = :bench AND date >= :date
            ORDER BY date ASC
            LIMIT 11
        """), {"bench": "sh000300", "date": decision_date}).all()
        bench_close: dict[str, float] = {r.date: float(r.close) for r in bench_rows if r.close is not None}
        bench_base = bench_close.get(prices[0].date) if bench_rows else None
        base = float(prices[0].close)
        offsets = [1, 3, 5, 10]
        returns = {}
        excess_returns: dict[str, float] = {}
        for offset in offsets:
            if len(prices) > offset and prices[offset].close is not None:
                stock_ret = (float(prices[offset].close) - base) / base * 100
                returns[f"{offset}d"] = round(stock_ret, 2)
                if bench_base:
                    bench_close_at = bench_close.get(prices[offset].date)
                    if bench_close_at is not None:
                        bench_ret = (bench_close_at - bench_base) / bench_base * 100
                        excess_returns[f"{offset}d"] = round(stock_ret - bench_ret, 2)
        if not returns:
            continue
        summary_bits = "，".join(f"{k}{v:+.2f}%" for k, v in returns.items())
        if excess_returns:
            summary_bits += "（vs HS300："
            summary_bits += "，".join(f"{k}{v:+.2f}%" for k, v in excess_returns.items())
            summary_bits += "）"
        create_stock_memory(
            db,
            symbol=row.symbol,
            memory_type="outcome",
            summary=f"{decision_date} 判断后表现：{summary_bits}",
            evidence={
                "judgment_id": row.id,
                "returns": returns,
                "excess_returns": excess_returns,
                "benchmark": "sh000300" if excess_returns else None,
                "recommendation": recommendation,
                "judgment_evidence": evidence,
            },
            source_type="outcome_update",
            source_ref=source_ref,
            importance=3,
            confidence=0.7,
            status="validated",
        )
        written += 1

        # M15.3：lesson 触发改用超额收益（excess vs HS300），无基准数据时回退裸收益
        judgement_returns = excess_returns or returns
        latest_return = next((judgement_returns[k] for k in ("10d", "5d", "3d", "1d") if k in judgement_returns), None)
        if (
            latest_return is not None
            and is_entry_signal(recommendation, include_legacy=True)
            and latest_return <= -5.0
        ):
            lesson_ref = f"lesson:{row.id}"
            if _id_by_source_ref(db, lesson_ref) is None:
                basis = "相对沪深300" if excess_returns else "绝对收益"
                create_stock_memory(
                    db,
                    symbol=row.symbol,
                    memory_type="lesson",
                    summary=(
                        f"{decision_date} 正向判断在完整窗口{basis}{latest_return:+.2f}%，"
                        "属于显著失效样本；再次出现同类信号时必须核对当时因子与新证据。"
                    ),
                    evidence={
                        "judgment_id": row.id,
                        "latest_return": latest_return,
                        "basis": basis,
                        "judgment_evidence": evidence,
                    },
                    source_type="outcome_update",
                    source_ref=lesson_ref,
                    importance=4,
                    confidence=0.6,
                    status="watching",
                )
                written += 1
    return written
