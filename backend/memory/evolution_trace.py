"""M57 raw memory-evolution trace helpers.

Trace rows are observability only. They do not promote memory, change signals,
or alter scoring policy.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

NAMESPACE_TRADING_DISCIPLINE = "交易纪律"
NAMESPACE_RESEARCH_THESIS = "研究论点"
NAMESPACE_PERSONAL_PREFERENCE = "个人偏好与约束"
NAMESPACE_OPERATION_REVIEW = "操作复盘"
NAMESPACE_EXTERNAL_METHOD = "外部方法论"
NAMESPACE_DATA_SOURCE = "数据源经验"
NAMESPACE_SYSTEM_OPERATIONS = "系统运维"

NAMESPACES = {
    NAMESPACE_TRADING_DISCIPLINE,
    NAMESPACE_RESEARCH_THESIS,
    NAMESPACE_PERSONAL_PREFERENCE,
    NAMESPACE_OPERATION_REVIEW,
    NAMESPACE_EXTERNAL_METHOD,
    NAMESPACE_DATA_SOURCE,
    NAMESPACE_SYSTEM_OPERATIONS,
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def normalize_namespace(namespace: str | None) -> str:
    value = str(namespace or NAMESPACE_SYSTEM_OPERATIONS).strip()
    if value == "UX偏好":
        value = NAMESPACE_PERSONAL_PREFERENCE
    if value not in NAMESPACES:
        raise ValueError(f"unsupported memory namespace: {value}")
    return value


def ensure_schema(db) -> None:
    bind = db.get_bind()
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS evolution_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_type TEXT NOT NULL,
                namespace TEXT NOT NULL,
                subject TEXT,
                symbols_json TEXT,
                themes_json TEXT,
                content TEXT NOT NULL,
                payload_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                as_of TEXT,
                stale_after TEXT,
                event_time TEXT NOT NULL,
                ingestion_time TEXT NOT NULL,
                invalidated_at TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_evolution_traces_namespace_as_of
            ON evolution_traces(namespace, as_of)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_evolution_traces_type_ingestion
            ON evolution_traces(trace_type, ingestion_time)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_evolution_traces_invalidated
            ON evolution_traces(invalidated_at)
        """))


def record_trace(
    db,
    *,
    trace_type: str,
    namespace: str,
    content: str,
    subject: str | None = None,
    symbols: list[str] | None = None,
    themes: list[str] | None = None,
    payload: Any = None,
    source_type: str | None = None,
    source_ref: str | None = None,
    as_of: str | None = None,
    stale_after: str | None = None,
    event_time: datetime | str | None = None,
    ingestion_time: datetime | str | None = None,
    invalidated_at: datetime | str | None = None,
) -> dict[str, Any]:
    ensure_schema(db)
    now = _utc_now()
    event_value = _iso(event_time) or _iso(as_of) or now.isoformat(timespec="seconds")
    ingestion_value = _iso(ingestion_time) or now.isoformat(timespec="seconds")
    created_value = now.isoformat(timespec="seconds")
    params = {
        "trace_type": trace_type,
        "namespace": normalize_namespace(namespace),
        "subject": subject,
        "symbols_json": _json(symbols or []),
        "themes_json": _json(themes or []),
        "content": content.strip(),
        "payload_json": _json(payload),
        "source_type": source_type,
        "source_ref": source_ref,
        "as_of": as_of,
        "stale_after": stale_after,
        "event_time": event_value,
        "ingestion_time": ingestion_value,
        "invalidated_at": _iso(invalidated_at),
        "created_at": created_value,
    }
    result = db.execute(text("""
        INSERT INTO evolution_traces(
            trace_type, namespace, subject, symbols_json, themes_json, content,
            payload_json, source_type, source_ref, as_of, stale_after,
            event_time, ingestion_time, invalidated_at, created_at
        )
        VALUES(
            :trace_type, :namespace, :subject, :symbols_json, :themes_json, :content,
            :payload_json, :source_type, :source_ref, :as_of, :stale_after,
            :event_time, :ingestion_time, :invalidated_at, :created_at
        )
    """), params)
    db.commit()
    row_id = int(result.lastrowid)
    return {"id": row_id, **params}


def list_traces(db, *, limit: int = 50, trace_type: str | None = None) -> list[dict[str, Any]]:
    ensure_schema(db)
    params: dict[str, Any] = {"limit": limit}
    where = ""
    if trace_type:
        where = "WHERE trace_type = :trace_type"
        params["trace_type"] = trace_type
    rows = db.execute(text(f"""
        SELECT *
        FROM evolution_traces
        {where}
        ORDER BY ingestion_time DESC, id DESC
        LIMIT :limit
    """), params).mappings().all()
    return [dict(row) for row in rows]
