"""M57 unified FTS5 memory recall across MingCang memory stores."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError

from backend.memory.evolution_trace import (
    NAMESPACE_EXTERNAL_METHOD,
    NAMESPACE_OPERATION_REVIEW,
    NAMESPACE_PERSONAL_PREFERENCE,
    NAMESPACE_RESEARCH_THESIS,
    NAMESPACE_SYSTEM_OPERATIONS,
    NAMESPACE_TRADING_DISCIPLINE,
    normalize_namespace,
)

AS_OF_SUPPORTED_SOURCES = {"evolution_traces", "task_capsules"}

QUERY_ALIASES = {
    "光模块": ["光通信", "CPO", "光器件"],
}


def _table_exists(db, table: str) -> bool:
    return bool(db.execute(
        text("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = :table"),
        {"table": table},
    ).first())


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if item is not None]


def _namespace_for_ai(category: str | None, scope: str | None) -> str:
    if category in {"rule", "risk"}:
        return NAMESPACE_TRADING_DISCIPLINE
    if category == "preference":
        return NAMESPACE_PERSONAL_PREFERENCE
    if category in {"deep_research", "research"} or scope == "research":
        return NAMESPACE_RESEARCH_THESIS
    return NAMESPACE_SYSTEM_OPERATIONS


def _namespace_for_stock(memory_type: str | None) -> str:
    if memory_type == "user_preference":
        return NAMESPACE_PERSONAL_PREFERENCE
    if memory_type in {"outcome", "lesson", "judgment"}:
        return NAMESPACE_OPERATION_REVIEW
    return NAMESPACE_RESEARCH_THESIS


def _namespace_for_scope(scope_type: str | None, memory_type: str | None = None) -> str:
    if scope_type == "user_preference":
        return NAMESPACE_PERSONAL_PREFERENCE
    if scope_type == "methodology":
        return NAMESPACE_EXTERNAL_METHOD
    if memory_type in {"rule", "risk", "discipline"}:
        return NAMESPACE_TRADING_DISCIPLINE
    if scope_type in {"stock", "theme", "sector", "market"}:
        return NAMESPACE_RESEARCH_THESIS
    return NAMESPACE_SYSTEM_OPERATIONS


def _upsert(db, item: dict[str, Any]) -> None:
    db.execute(text("""
        INSERT INTO memory_recall_index(
            source, source_id, namespace, symbol, subject, title, body, tags,
            as_of, event_time, ingestion_time, invalidated_at, supports_as_of, updated_at
        )
        VALUES(
            :source, :source_id, :namespace, :symbol, :subject, :title, :body, :tags,
            :as_of, :event_time, :ingestion_time, :invalidated_at, :supports_as_of, :updated_at
        )
        ON CONFLICT(source, source_id) DO UPDATE SET
            namespace = excluded.namespace,
            symbol = excluded.symbol,
            subject = excluded.subject,
            title = excluded.title,
            body = excluded.body,
            tags = excluded.tags,
            as_of = excluded.as_of,
            event_time = excluded.event_time,
            ingestion_time = excluded.ingestion_time,
            invalidated_at = excluded.invalidated_at,
            supports_as_of = excluded.supports_as_of,
            updated_at = excluded.updated_at
    """), item)


def _delete_missing(db, source: str, source_ids: list[str]) -> None:
    if source_ids:
        stmt = text("""
            DELETE FROM memory_recall_index
            WHERE source = :source AND source_id NOT IN :source_ids
        """).bindparams(bindparam("source_ids", expanding=True))
        db.execute(stmt, {"source": source, "source_ids": source_ids})
    else:
        db.execute(text("""
            DELETE FROM memory_recall_index
            WHERE source = :source
        """), {"source": source})


def _sync_ai_memory(db) -> None:
    if not _table_exists(db, "ai_memory"):
        return
    rows = db.execute(text("""
        SELECT id, key, value, category, scope, created_at, updated_at
        FROM ai_memory
    """)).mappings().all()
    active_ids: list[str] = []
    for row in rows:
        active_ids.append(str(row["id"]))
        _upsert(db, {
            "source": "ai_memory",
            "source_id": str(row["id"]),
            "namespace": _namespace_for_ai(row["category"], row["scope"]),
            "symbol": None,
            "subject": row["key"],
            "title": row["key"],
            "body": row["value"],
            "tags": " ".join(str(v or "") for v in (row["category"], row["scope"])),
            "as_of": _as_text(row["created_at"]),
            "event_time": _as_text(row["created_at"]),
            "ingestion_time": _as_text(row["created_at"] or row["updated_at"]),
            "invalidated_at": None,
            "supports_as_of": 0,
            "updated_at": _as_text(row["updated_at"] or row["created_at"]),
        })
    _delete_missing(db, "ai_memory", active_ids)


def _sync_stock_memory(db) -> None:
    if not _table_exists(db, "stock_memory_items"):
        return
    rows = db.execute(text("""
        SELECT id, symbol, memory_type, summary, evidence_json, source_type, source_ref,
               importance, confidence, status, created_at, updated_at
        FROM stock_memory_items
        WHERE status != 'archived'
    """)).mappings().all()
    active_ids: list[str] = []
    for row in rows:
        active_ids.append(str(row["id"]))
        _upsert(db, {
            "source": "stock_memory_items",
            "source_id": str(row["id"]),
            "namespace": _namespace_for_stock(row["memory_type"]),
            "symbol": row["symbol"],
            "subject": row["symbol"],
            "title": " ".join(str(v or "") for v in (row["symbol"], row["memory_type"])).strip(),
            "body": row["summary"],
            "tags": " ".join(str(v or "") for v in (
                row["memory_type"], row["evidence_json"], row["source_type"], row["source_ref"],
            )),
            "as_of": _as_text(row["created_at"]),
            "event_time": _as_text(row["created_at"]),
            "ingestion_time": _as_text(row["created_at"] or row["updated_at"]),
            "invalidated_at": None,
            "supports_as_of": 0,
            "updated_at": _as_text(row["updated_at"] or row["created_at"]),
        })
    _delete_missing(db, "stock_memory_items", active_ids)


def _sync_decision_memory(db) -> None:
    if not _table_exists(db, "decision_memory_layered"):
        return
    rows = db.execute(text("""
        SELECT id, symbol, layer, content, updated_at
        FROM decision_memory_layered
    """)).mappings().all()
    active_ids: list[str] = []
    for row in rows:
        active_ids.append(str(row["id"]))
        symbol = None if row["symbol"] == "__GLOBAL__" else row["symbol"]
        _upsert(db, {
            "source": "decision_memory_layered",
            "source_id": str(row["id"]),
            "namespace": NAMESPACE_OPERATION_REVIEW,
            "symbol": symbol,
            "subject": symbol or row["layer"],
            "title": " ".join(str(v or "") for v in (symbol, row["layer"])).strip(),
            "body": row["content"],
            "tags": row["layer"],
            "as_of": _as_text(row["updated_at"]),
            "event_time": _as_text(row["updated_at"]),
            "ingestion_time": _as_text(row["updated_at"]),
            "invalidated_at": None,
            "supports_as_of": 0,
            "updated_at": _as_text(row["updated_at"]),
        })
    _delete_missing(db, "decision_memory_layered", active_ids)


def _sync_l0(db) -> None:
    if _table_exists(db, "memory_atoms"):
        rows = db.execute(text("""
            SELECT id, scope_type, scope_key, memory_type, summary, evidence_json,
                   source_type, source_ref, trust_state, valid_from, valid_to,
                   created_at, updated_at
            FROM memory_atoms
            WHERE trust_state != 'archived'
        """)).mappings().all()
        active_ids: list[str] = []
        for row in rows:
            active_ids.append(str(row["id"]))
            _upsert(db, {
                "source": "memory_atoms",
                "source_id": str(row["id"]),
                "namespace": _namespace_for_scope(row["scope_type"], row["memory_type"]),
                "symbol": row["scope_key"] if row["scope_type"] == "stock" else None,
                "subject": row["scope_key"],
                "title": " ".join(str(v or "") for v in (
                    row["scope_type"], row["scope_key"], row["memory_type"],
                )).strip(),
                "body": row["summary"],
                "tags": " ".join(str(v or "") for v in (
                    row["trust_state"], row["evidence_json"], row["source_type"], row["source_ref"],
                )),
                "as_of": _as_text(row["valid_from"] or row["created_at"]),
                "event_time": _as_text(row["valid_from"] or row["created_at"]),
                "ingestion_time": _as_text(row["created_at"] or row["updated_at"]),
                "invalidated_at": _as_text(row["valid_to"]) if row["trust_state"] == "refuted" else None,
                "supports_as_of": 0,
                "updated_at": _as_text(row["updated_at"] or row["created_at"]),
            })
        _delete_missing(db, "memory_atoms", active_ids)
    else:
        _delete_missing(db, "memory_atoms", [])
    if _table_exists(db, "memory_scenarios"):
        rows = db.execute(text("""
            SELECT id, scope_type, scope_key, title, summary, atom_ids_json,
                   trust_state, source_type, source_ref, created_at, updated_at
            FROM memory_scenarios
            WHERE trust_state != 'archived'
        """)).mappings().all()
        active_ids = []
        for row in rows:
            active_ids.append(str(row["id"]))
            _upsert(db, {
                "source": "memory_scenarios",
                "source_id": str(row["id"]),
                "namespace": _namespace_for_scope(row["scope_type"]),
                "symbol": row["scope_key"] if row["scope_type"] == "stock" else None,
                "subject": row["scope_key"],
                "title": row["title"],
                "body": row["summary"],
                "tags": " ".join(str(v or "") for v in (
                    row["trust_state"], row["atom_ids_json"], row["source_type"], row["source_ref"],
                )),
                "as_of": _as_text(row["created_at"]),
                "event_time": _as_text(row["created_at"]),
                "ingestion_time": _as_text(row["created_at"] or row["updated_at"]),
                "invalidated_at": None,
                "supports_as_of": 0,
                "updated_at": _as_text(row["updated_at"] or row["created_at"]),
            })
        _delete_missing(db, "memory_scenarios", active_ids)
    else:
        _delete_missing(db, "memory_scenarios", [])
    if _table_exists(db, "memory_profiles"):
        rows = db.execute(text("""
            SELECT id, profile_type, profile_key, summary, atom_ids_json,
                   trust_state, source_type, source_ref, created_at, updated_at
            FROM memory_profiles
            WHERE trust_state != 'archived'
        """)).mappings().all()
        active_ids = []
        for row in rows:
            active_ids.append(str(row["id"]))
            namespace = (
                NAMESPACE_PERSONAL_PREFERENCE
                if row["profile_type"] in {"user", "preference", "user_preference"}
                else NAMESPACE_EXTERNAL_METHOD
                if row["profile_type"] == "methodology"
                else NAMESPACE_SYSTEM_OPERATIONS
            )
            _upsert(db, {
                "source": "memory_profiles",
                "source_id": str(row["id"]),
                "namespace": namespace,
                "symbol": None,
                "subject": row["profile_key"],
                "title": " ".join(str(v or "") for v in (row["profile_type"], row["profile_key"])).strip(),
                "body": row["summary"],
                "tags": " ".join(str(v or "") for v in (
                    row["trust_state"], row["atom_ids_json"], row["source_type"], row["source_ref"],
                )),
                "as_of": _as_text(row["created_at"]),
                "event_time": _as_text(row["created_at"]),
                "ingestion_time": _as_text(row["created_at"] or row["updated_at"]),
                "invalidated_at": None,
                "supports_as_of": 0,
                "updated_at": _as_text(row["updated_at"] or row["created_at"]),
            })
        _delete_missing(db, "memory_profiles", active_ids)
    else:
        _delete_missing(db, "memory_profiles", [])


def _sync_traces(db) -> None:
    if not _table_exists(db, "evolution_traces"):
        return
    rows = db.execute(text("""
        SELECT id, trace_type, namespace, subject, symbols_json, themes_json, content,
               source_type, source_ref, as_of, event_time, ingestion_time,
               invalidated_at, created_at
        FROM evolution_traces
    """)).mappings().all()
    active_ids: list[str] = []
    for row in rows:
        active_ids.append(str(row["id"]))
        symbols = _loads_list(row["symbols_json"])
        symbol = symbols[0] if symbols else row["subject"]
        _upsert(db, {
            "source": "evolution_traces",
            "source_id": str(row["id"]),
            "namespace": normalize_namespace(row["namespace"]),
            "symbol": symbol,
            "subject": row["subject"],
            "title": " ".join(str(v or "") for v in (row["trace_type"], row["subject"])).strip(),
            "body": row["content"],
            "tags": " ".join([
                *_loads_list(row["themes_json"]),
                str(row["source_type"] or ""),
                str(row["source_ref"] or ""),
            ]),
            "as_of": _as_text(row["as_of"]),
            "event_time": _as_text(row["event_time"]),
            "ingestion_time": _as_text(row["ingestion_time"]),
            "invalidated_at": _as_text(row["invalidated_at"]),
            "supports_as_of": 1,
            "updated_at": _as_text(row["created_at"] or row["ingestion_time"]),
        })
    _delete_missing(db, "evolution_traces", active_ids)


def _sync_task_capsules(db) -> None:
    if not _table_exists(db, "task_capsules"):
        return
    rows = db.execute(text("""
        SELECT id, capsule_id, task_type, symbols_json, themes_json, goal,
               confirmed_facts, decisions, open_loops, next_actions,
               trust_state, as_of, event_time, ingestion_time, invalidated_at, created_at
        FROM task_capsules
    """)).mappings().all()
    active_ids: list[str] = []
    for row in rows:
        active_ids.append(str(row["id"]))
        symbols = _loads_list(row["symbols_json"])
        body = "\n".join(filter(None, [
            row["goal"],
            _json_text(row["confirmed_facts"]),
            _json_text(row["decisions"]),
            _json_text(row["open_loops"]),
            _json_text(row["next_actions"]),
        ]))
        _upsert(db, {
            "source": "task_capsules",
            "source_id": str(row["id"]),
            "namespace": NAMESPACE_OPERATION_REVIEW,
            "symbol": symbols[0] if symbols else None,
            "subject": row["capsule_id"],
            "title": " ".join(str(v or "") for v in (row["task_type"], row["capsule_id"])).strip(),
            "body": body,
            "tags": " ".join([*_loads_list(row["themes_json"]), str(row["trust_state"] or "")]),
            "as_of": _as_text(row["as_of"]),
            "event_time": _as_text(row["event_time"]),
            "ingestion_time": _as_text(row["ingestion_time"]),
            "invalidated_at": _as_text(row["invalidated_at"]),
            "supports_as_of": 1,
            "updated_at": _as_text(row["created_at"] or row["ingestion_time"]),
        })
    _delete_missing(db, "task_capsules", active_ids)


def sync_recall_index(db) -> None:
    """Idempotently sync existing memory rows into the unified recall index."""
    from backend.data.schema_runtime import _ensure_memory_recall_schema

    _ensure_memory_recall_schema(db.get_bind())
    _sync_ai_memory(db)
    _sync_stock_memory(db)
    _sync_decision_memory(db)
    _sync_l0(db)
    _sync_traces(db)
    _sync_task_capsules(db)
    db.commit()


def _fts_query(query: str) -> str:
    escaped = query.strip().replace('"', '""')
    return f'"{escaped}"'


def _where_filters(
    *,
    namespace: str | None,
    symbol: str | None,
    as_of: str | None,
    like_fallback: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if namespace is not None:
        clauses.append("idx.namespace = :namespace")
        params["namespace"] = normalize_namespace(namespace)
    if symbol is not None:
        clauses.append("idx.symbol = :symbol")
        params["symbol"] = symbol
    if as_of is not None:
        params["as_of"] = as_of
        clauses.append("""(
            (
                idx.supports_as_of = 1
                AND coalesce(idx.ingestion_time, idx.event_time, idx.as_of, idx.updated_at) <= :as_of
                AND (idx.invalidated_at IS NULL OR idx.invalidated_at > :as_of)
            )
            OR (
                idx.supports_as_of = 0
                AND coalesce(idx.updated_at, idx.ingestion_time, idx.event_time, idx.as_of) <= :as_of
            )
        )""")
    if like_fallback:
        clauses.append("""(
            idx.title LIKE :like OR idx.body LIKE :like OR idx.tags LIKE :like
        )""")
    return clauses, params


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "namespace": row["namespace"],
        "symbol": row["symbol"],
        "subject": row["subject"],
        "title": row["title"],
        "body": row["body"],
        "tags": row["tags"],
        "as_of": row["as_of"],
        "event_time": row["event_time"],
        "ingestion_time": row["ingestion_time"],
        "invalidated_at": row["invalidated_at"],
        "supports_as_of": bool(row["supports_as_of"]),
        "updated_at": row["updated_at"],
        "recency_note": (
            "dual_timeline"
            if bool(row["supports_as_of"])
            else "created_or_updated_at_fallback"
        ),
        "ref": f"{row['source']}:{row['source_id']}",
    }


def recall(
    db,
    query: str,
    *,
    namespace: str | None = None,
    symbol: str | None = None,
    as_of: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Search unified memory with FTS5 plus namespace/symbol/as-of filters."""
    sync_recall_index(db)
    limit = max(1, min(50, int(limit)))
    queries = [query, *QUERY_ALIASES.get(query.strip(), [])]
    rows = []
    for current_query in queries:
        rows = _recall_once(
            db,
            current_query,
            namespace=namespace,
            symbol=symbol,
            as_of=as_of,
            limit=limit,
        )
        if rows:
            break
    return [_row_to_dict(row) for row in rows]


def _recall_once(
    db,
    query: str,
    *,
    namespace: str | None,
    symbol: str | None,
    as_of: str | None,
    limit: int,
):
    clauses, params = _where_filters(namespace=namespace, symbol=symbol, as_of=as_of)
    where = " AND ".join(["memory_recall_fts MATCH :query", *clauses])
    params.update({"query": _fts_query(query), "limit": limit})
    try:
        rows = db.execute(text(f"""
            SELECT idx.*
            FROM memory_recall_fts
            JOIN memory_recall_index idx ON idx.id = memory_recall_fts.rowid
            WHERE {where}
            ORDER BY rank, idx.supports_as_of DESC, idx.updated_at DESC, idx.id DESC
            LIMIT :limit
        """), params).mappings().all()  # noqa: S608 - WHERE fragments are fixed literals.
    except OperationalError:
        rows = []
    if not rows:
        clauses, params = _where_filters(
            namespace=namespace,
            symbol=symbol,
            as_of=as_of,
            like_fallback=True,
        )
        params.update({"like": f"%{query}%", "limit": limit})
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = db.execute(text(f"""
            SELECT idx.*
            FROM memory_recall_index idx
            {where}
            ORDER BY idx.supports_as_of DESC, idx.updated_at DESC, idx.id DESC
            LIMIT :limit
        """), params).mappings().all()  # noqa: S608 - WHERE fragments are fixed literals.
    return rows


def as_of_support_by_source(db) -> dict[str, bool]:
    """Return current indexed sources and whether each has dual-timeline fields."""
    sync_recall_index(db)
    rows = db.execute(text("""
        SELECT source, max(supports_as_of) AS supports_as_of
        FROM memory_recall_index
        GROUP BY source
        ORDER BY source
    """)).mappings().all()
    return {row["source"]: bool(row["supports_as_of"]) for row in rows}
