"""M57 task capsule persistence for compact cross-session carryover."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from backend.memory.evolution_trace import NAMESPACE_OPERATION_REVIEW, record_trace

MAX_LIST_ITEMS = 5


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True, default=str)


def _load_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _trim_list(values: list[Any] | None) -> list[Any]:
    return list(values or [])[:MAX_LIST_ITEMS]


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 1) // 2)


def ensure_schema(db) -> None:
    bind = db.get_bind()
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_capsules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capsule_id TEXT NOT NULL UNIQUE,
                task_type TEXT NOT NULL,
                user_id TEXT DEFAULT 'owner',
                symbols_json TEXT NOT NULL,
                themes_json TEXT NOT NULL,
                goal TEXT NOT NULL,
                confirmed_facts TEXT,
                decisions TEXT,
                open_loops TEXT,
                next_actions TEXT,
                used_memory_refs TEXT,
                artifact_refs TEXT,
                trust_state TEXT DEFAULT 'draft',
                token_estimate INTEGER NOT NULL,
                as_of TEXT,
                event_time TEXT NOT NULL,
                ingestion_time TEXT NOT NULL,
                invalidated_at TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_task_capsules_user_created
            ON task_capsules(user_id, created_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_task_capsules_as_of
            ON task_capsules(as_of)
        """))


def _row_to_dict(row) -> dict[str, Any]:
    item = dict(row)
    for key in (
        "symbols_json",
        "themes_json",
        "confirmed_facts",
        "decisions",
        "open_loops",
        "next_actions",
        "used_memory_refs",
        "artifact_refs",
    ):
        item[key] = _load_json(item.get(key), [])
    return item


def write_task_capsule(
    db,
    *,
    task_type: str,
    goal: str,
    user_id: str = "owner",
    symbols: list[str] | None = None,
    themes: list[str] | None = None,
    confirmed_facts: list[str] | None = None,
    decisions: list[str] | None = None,
    open_loops: list[str] | None = None,
    next_actions: list[str] | None = None,
    used_memory_refs: list[str] | None = None,
    artifact_refs: list[str] | None = None,
    trust_state: str = "draft",
    as_of: str | None = None,
    capsule_id: str | None = None,
) -> dict[str, Any]:
    ensure_schema(db)
    now = _utc_now().isoformat(timespec="seconds")
    safe_facts = _trim_list(confirmed_facts)
    safe_decisions = _trim_list(decisions)
    safe_open = _trim_list(open_loops)
    safe_next = _trim_list(next_actions)
    capsule_id = capsule_id or f"{task_type}:{as_of or now[:10]}:{abs(hash((goal, now))) % 1000000:06d}"
    token_text = "\n".join([goal, *safe_facts, *safe_decisions, *safe_open, *safe_next])
    params = {
        "capsule_id": capsule_id,
        "task_type": task_type,
        "user_id": user_id,
        "symbols_json": _json(symbols or []),
        "themes_json": _json(themes or []),
        "goal": goal.strip(),
        "confirmed_facts": _json(safe_facts),
        "decisions": _json(safe_decisions),
        "open_loops": _json(safe_open),
        "next_actions": _json(safe_next),
        "used_memory_refs": _json(used_memory_refs or []),
        "artifact_refs": _json(artifact_refs or []),
        "trust_state": trust_state,
        "token_estimate": estimate_tokens(token_text),
        "as_of": as_of,
        "event_time": as_of or now,
        "ingestion_time": now,
        "invalidated_at": None,
        "created_at": now,
    }
    db.execute(text("""
        INSERT INTO task_capsules(
            capsule_id, task_type, user_id, symbols_json, themes_json, goal,
            confirmed_facts, decisions, open_loops, next_actions, used_memory_refs,
            artifact_refs, trust_state, token_estimate, as_of, event_time,
            ingestion_time, invalidated_at, created_at
        )
        VALUES(
            :capsule_id, :task_type, :user_id, :symbols_json, :themes_json, :goal,
            :confirmed_facts, :decisions, :open_loops, :next_actions, :used_memory_refs,
            :artifact_refs, :trust_state, :token_estimate, :as_of, :event_time,
            :ingestion_time, :invalidated_at, :created_at
        )
        ON CONFLICT(capsule_id) DO UPDATE SET
            symbols_json=excluded.symbols_json,
            themes_json=excluded.themes_json,
            goal=excluded.goal,
            confirmed_facts=excluded.confirmed_facts,
            decisions=excluded.decisions,
            open_loops=excluded.open_loops,
            next_actions=excluded.next_actions,
            used_memory_refs=excluded.used_memory_refs,
            artifact_refs=excluded.artifact_refs,
            trust_state=excluded.trust_state,
            token_estimate=excluded.token_estimate,
            as_of=excluded.as_of,
            event_time=excluded.event_time,
            ingestion_time=excluded.ingestion_time,
            invalidated_at=NULL,
            created_at=excluded.created_at
    """), params)
    db.commit()
    row = latest_task_capsule(db, user_id=user_id)
    record_trace(
        db,
        trace_type="task_capsule.write",
        namespace=NAMESPACE_OPERATION_REVIEW,
        subject=capsule_id,
        content=f"Task capsule written: {goal.strip()}",
        symbols=symbols or [],
        themes=themes or [],
        payload={"capsule_id": capsule_id, "task_type": task_type, "trust_state": trust_state},
        source_type="task_capsule",
        source_ref=capsule_id,
        as_of=as_of,
        event_time=as_of or now,
    )
    return row or {**params, "id": None}


def latest_task_capsule(db, *, user_id: str = "owner", task_type: str | None = None) -> dict[str, Any] | None:
    ensure_schema(db)
    params: dict[str, Any] = {"user_id": user_id}
    clauses = ["user_id = :user_id", "invalidated_at IS NULL"]
    if task_type:
        clauses.append("task_type = :task_type")
        params["task_type"] = task_type
    row = db.execute(text(f"""
        SELECT *
        FROM task_capsules
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """), params).mappings().first()
    return _row_to_dict(row) if row else None


def list_task_capsules(db, *, user_id: str = "owner", limit: int = 3) -> list[dict[str, Any]]:
    ensure_schema(db)
    rows = db.execute(text("""
        SELECT *
        FROM task_capsules
        WHERE user_id = :user_id AND invalidated_at IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT :limit
    """), {"user_id": user_id, "limit": limit}).mappings().all()
    return [_row_to_dict(row) for row in rows]
