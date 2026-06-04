"""StockSage L0 memory helpers.

This is a local-first memory contract inspired by TencentDB-Agent-Memory's
atom/scenario/profile layering.  It deliberately keeps StockSage SQLite as the
source of truth and keeps trusted writes behind explicit gates.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text

from backend.memory.audit_log import audit_write

TRUST_STATES = {
    "raw",
    "pending",
    "trusted",
    "refuted",
    "archived",
    "legacy_import_pending",
}
PROMOTABLE_STATES = {"raw", "pending", "legacy_import_pending"}
CALLER_CREATABLE_STATES = {"raw", "pending", "legacy_import_pending"}
SCOPE_TYPES = {
    "stock",
    "theme",
    "sector",
    "market",
    "global",
    "user_preference",
    "methodology",
}

_TRUST_ORDER = {
    "trusted": 0,
    "pending": 1,
    "raw": 2,
    "legacy_import_pending": 3,
    "refuted": 4,
    "archived": 5,
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: dict | list | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _validate(scope_type: str | None = None, trust_state: str | None = None) -> None:
    if scope_type is not None and scope_type not in SCOPE_TYPES:
        raise ValueError(f"unsupported scope_type: {scope_type}")
    if trust_state is not None and trust_state not in TRUST_STATES:
        raise ValueError(f"unsupported trust_state: {trust_state}")


def _ensure_schema(db) -> None:
    bind = db.get_bind()
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_atoms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_type TEXT,
                scope_key TEXT,
                memory_type TEXT,
                summary TEXT NOT NULL,
                evidence_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                trust_state TEXT DEFAULT 'raw',
                importance INTEGER DEFAULT 3,
                confidence REAL DEFAULT 0.5,
                valid_from TEXT,
                valid_to TEXT,
                ttl_days INTEGER,
                review_case_id INTEGER,
                stock_memory_item_id INTEGER,
                promoted_by TEXT,
                refuted_by TEXT,
                refutation_reason TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                last_used_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_atoms_scope_trust
            ON memory_atoms(scope_type, scope_key, trust_state)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_atoms_source_ref
            ON memory_atoms(source_ref)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_atoms_review_case
            ON memory_atoms(review_case_id)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_type TEXT,
                scope_key TEXT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                atom_ids_json TEXT,
                trust_state TEXT DEFAULT 'pending',
                source_type TEXT DEFAULT 'manual',
                source_ref TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_scenarios_scope_trust
            ON memory_scenarios(scope_type, scope_key, trust_state)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_type TEXT,
                profile_key TEXT,
                summary TEXT NOT NULL,
                atom_ids_json TEXT,
                trust_state TEXT DEFAULT 'pending',
                source_type TEXT DEFAULT 'manual',
                source_ref TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_profiles_type_trust
            ON memory_profiles(profile_type, profile_key, trust_state)
        """))


def _active(row, now: datetime) -> bool:
    if row.trust_state == "archived":
        return False
    if row.ttl_days is None:
        return True
    try:
        updated_at = datetime.fromisoformat(str(row.updated_at))
    except (TypeError, ValueError):
        return True
    return updated_at + timedelta(days=int(row.ttl_days)) >= now


def _row_to_atom(row) -> dict:
    return {
        "id": row.id,
        "scope_type": row.scope_type,
        "scope_key": row.scope_key,
        "memory_type": row.memory_type,
        "summary": row.summary,
        "evidence": _loads(row.evidence_json),
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "trust_state": row.trust_state,
        "importance": row.importance,
        "confidence": row.confidence,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "ttl_days": row.ttl_days,
        "review_case_id": row.review_case_id,
        "stock_memory_item_id": row.stock_memory_item_id,
        "promoted_by": row.promoted_by,
        "refuted_by": row.refuted_by,
        "refutation_reason": row.refutation_reason,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_used_at": _iso(row.last_used_at),
    }


def _id_by_source_ref(db, source_ref: str) -> int | None:
    row = db.execute(text(
        "SELECT id FROM memory_atoms WHERE source_ref = :source_ref "
        "ORDER BY id ASC LIMIT 1"
    ), {"source_ref": source_ref}).first()
    return int(row.id) if row else None


def create_memory_atom(
    db,
    *,
    scope_type: str,
    scope_key: str | None,
    memory_type: str,
    summary: str,
    source_type: str,
    source_ref: str | None = None,
    trust_state: str = "raw",
    evidence: dict | list | None = None,
    importance: int = 3,
    confidence: float = 0.5,
    valid_from: str | None = None,
    valid_to: str | None = None,
    ttl_days: int | None = None,
    review_case_id: int | None = None,
    stock_memory_item_id: int | None = None,
    promoted_by: str | None = None,
    refuted_by: str | None = None,
    refutation_reason: str | None = None,
) -> dict:
    """Create or upsert one L0 atom.

    source_ref is the idempotency key.  LLM/tool callers should use raw/pending;
    trusted/refuted should be written only from explicit gate functions.
    """
    _validate(scope_type=scope_type, trust_state=trust_state)
    if trust_state not in CALLER_CREATABLE_STATES:
        raise ValueError(
            f"create_memory_atom cannot create {trust_state!r}; use promote/refute gates"
        )
    _ensure_schema(db)
    now = _utc_now().isoformat(timespec="seconds")
    params = {
        "scope_type": scope_type,
        "scope_key": scope_key,
        "memory_type": memory_type,
        "summary": summary.strip(),
        "evidence_json": _json(evidence),
        "source_type": source_type,
        "source_ref": source_ref,
        "trust_state": trust_state,
        "importance": max(1, min(5, int(importance))),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "ttl_days": ttl_days,
        "review_case_id": review_case_id,
        "stock_memory_item_id": stock_memory_item_id,
        "promoted_by": promoted_by,
        "refuted_by": refuted_by,
        "refutation_reason": refutation_reason,
        "now": now,
    }
    existing_id = _id_by_source_ref(db, source_ref) if source_ref else None
    if existing_id is not None:
        existing = db.execute(
            text("SELECT trust_state FROM memory_atoms WHERE id = :id"),
            {"id": existing_id},
        ).first()
        if existing and existing.trust_state not in CALLER_CREATABLE_STATES:
            raise ValueError(
                f"memory atom {existing_id} is {existing.trust_state!r}; "
                "use promote/refute gates for trust-state changes"
            )
        params["id"] = existing_id
        db.execute(text("""
            UPDATE memory_atoms SET
                scope_type = :scope_type, scope_key = :scope_key,
                memory_type = :memory_type, summary = :summary,
                evidence_json = :evidence_json, source_type = :source_type,
                trust_state = :trust_state, importance = :importance,
                confidence = :confidence, valid_from = :valid_from,
                valid_to = :valid_to, ttl_days = :ttl_days,
                review_case_id = :review_case_id,
                stock_memory_item_id = :stock_memory_item_id,
                promoted_by = :promoted_by, refuted_by = :refuted_by,
                refutation_reason = :refutation_reason, updated_at = :now
            WHERE id = :id
        """), params)
        row_id = existing_id
        mode = "upsert"
    else:
        result = db.execute(text("""
            INSERT INTO memory_atoms(
                scope_type, scope_key, memory_type, summary, evidence_json,
                source_type, source_ref, trust_state, importance, confidence,
                valid_from, valid_to, ttl_days, review_case_id,
                stock_memory_item_id, promoted_by, refuted_by,
                refutation_reason, created_at, updated_at
            )
            VALUES(
                :scope_type, :scope_key, :memory_type, :summary, :evidence_json,
                :source_type, :source_ref, :trust_state, :importance, :confidence,
                :valid_from, :valid_to, :ttl_days, :review_case_id,
                :stock_memory_item_id, :promoted_by, :refuted_by,
                :refutation_reason, :now, :now
            )
        """), params)
        row_id = int(result.lastrowid)
        mode = "insert"
    db.commit()
    audit_write(
        db,
        "l0_memory.atom_write",
        f"id={row_id} scope={scope_type}:{scope_key} trust={trust_state} mode={mode}",
        related_symbol=scope_key if scope_type == "stock" else None,
        related_scope=scope_type,
    )
    row = db.execute(text("SELECT * FROM memory_atoms WHERE id = :id"), {"id": row_id}).first()
    return _row_to_atom(row)


def list_memory_atoms(
    db,
    *,
    scope_type: str | None = None,
    scope_key: str | None = None,
    trust_state: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
) -> list[dict]:
    _validate(scope_type=scope_type, trust_state=trust_state)
    _ensure_schema(db)
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if scope_type is not None:
        clauses.append("scope_type = :scope_type")
        params["scope_type"] = scope_type
    if scope_key is not None:
        clauses.append("scope_key = :scope_key")
        params["scope_key"] = scope_key
    if trust_state is not None:
        clauses.append("trust_state = :trust_state")
        params["trust_state"] = trust_state
    elif not include_archived:
        clauses.append("trust_state != 'archived'")
    if q:
        clauses.append("""(
            lower(coalesce(scope_key, '')) LIKE :q_like OR
            lower(coalesce(memory_type, '')) LIKE :q_like OR
            lower(coalesce(summary, '')) LIKE :q_like OR
            lower(coalesce(evidence_json, '')) LIKE :q_like OR
            lower(coalesce(source_ref, '')) LIKE :q_like
        )""")
        params["q_like"] = f"%{q.lower()}%"
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT *
        FROM memory_atoms
        {where}
        ORDER BY importance DESC, updated_at DESC, id DESC
        LIMIT :limit
    """  # noqa: S608 - WHERE clauses are allowlisted literals plus bound params.
    rows = db.execute(text(query), params).all()
    now = _utc_now()
    atoms = []
    for row in rows:
        if not _active(row, now):
            continue
        atom = _row_to_atom(row)
        atoms.append(atom)
    return sorted(
        atoms,
        key=lambda atom: (
            _TRUST_ORDER.get(atom["trust_state"], 99),
            -int(atom.get("importance") or 0),
            str(atom.get("updated_at") or ""),
        ),
    )


def promote_atom(db, atom_id: int, *, confirmed_by: str) -> dict:
    """Promote a raw/pending/legacy atom to trusted."""
    _ensure_schema(db)
    row = db.execute(text("SELECT * FROM memory_atoms WHERE id = :id"), {"id": atom_id}).first()
    if row is None:
        raise ValueError(f"memory atom {atom_id} not found")
    if row.trust_state not in PROMOTABLE_STATES:
        raise ValueError(f"atom {atom_id} cannot be promoted from {row.trust_state!r}")
    now = _utc_now().isoformat(timespec="seconds")
    db.execute(text("""
        UPDATE memory_atoms
        SET trust_state = 'trusted', promoted_by = :confirmed_by, updated_at = :now
        WHERE id = :id
    """), {"id": atom_id, "confirmed_by": confirmed_by, "now": now})
    db.commit()
    audit_write(
        db,
        "l0_memory.atom_promote",
        f"id={atom_id} promoted_by={confirmed_by!r}",
        related_symbol=row.scope_key if row.scope_type == "stock" else None,
        related_scope=row.scope_type,
    )
    updated = db.execute(text("SELECT * FROM memory_atoms WHERE id = :id"), {"id": atom_id}).first()
    return _row_to_atom(updated)


def refute_atom(
    db,
    atom_id: int,
    *,
    confirmed_by: str,
    reason: str | None = None,
) -> dict:
    """Mark an atom as refuted."""
    _ensure_schema(db)
    row = db.execute(text("SELECT * FROM memory_atoms WHERE id = :id"), {"id": atom_id}).first()
    if row is None:
        raise ValueError(f"memory atom {atom_id} not found")
    if row.trust_state == "archived":
        raise ValueError(f"atom {atom_id} is archived")
    now = _utc_now().isoformat(timespec="seconds")
    db.execute(text("""
        UPDATE memory_atoms
        SET trust_state = 'refuted', refuted_by = :confirmed_by,
            refutation_reason = :reason, updated_at = :now
        WHERE id = :id
    """), {"id": atom_id, "confirmed_by": confirmed_by, "reason": reason, "now": now})
    db.commit()
    audit_write(
        db,
        "l0_memory.atom_refute",
        f"id={atom_id} refuted_by={confirmed_by!r}",
        related_symbol=row.scope_key if row.scope_type == "stock" else None,
        related_scope=row.scope_type,
    )
    updated = db.execute(text("SELECT * FROM memory_atoms WHERE id = :id"), {"id": atom_id}).first()
    return _row_to_atom(updated)


def _legacy_stock_rows(db, *, scope_type: str | None, scope_key: str | None, q: str | None, limit: int) -> list[dict]:
    if scope_type not in (None, "stock"):
        return []
    from backend.memory.stock_memory import list_stock_memories

    rows = list_stock_memories(db, symbol=scope_key, q=q, limit=limit)
    return [
        {
            "legacy_source": "stock_memory_items",
            "legacy_id": row["id"],
            "scope_type": "stock",
            "scope_key": row["symbol"],
            "memory_type": row["memory_type"],
            "summary": row["summary"],
            "trust_state": "legacy_import_pending",
            "source_ref": row["source_ref"],
        }
        for row in rows
    ]


def _legacy_ai_rows(db, *, scope_type: str | None, scope_key: str | None, q: str | None, limit: int) -> list[dict]:
    if scope_type not in (None, "global", "user_preference", "methodology"):
        return []
    from backend.memory.ai_memory import list_active

    ql = q.lower() if q else None
    rows = []
    for row in list_active(db):
        value = row.get("value") or ""
        key = row.get("key") or ""
        if scope_key and scope_key not in f"{key} {value}":
            continue
        if ql and ql not in f"{key} {value}".lower():
            continue
        category = row.get("category") or "memory"
        legacy_scope = "user_preference" if category == "preference" else "global"
        rows.append({
            "legacy_source": "ai_memory",
            "legacy_id": row["id"],
            "scope_type": legacy_scope,
            "scope_key": row.get("scope"),
            "memory_type": category,
            "summary": value,
            "trust_state": "legacy_import_pending",
            "source_ref": key,
        })
        if len(rows) >= limit:
            break
    return rows


def legacy_memory_adapter(
    db,
    *,
    scope_type: str | None = None,
    scope_key: str | None = None,
    q: str | None = None,
    limit: int = 12,
) -> list[dict]:
    """Expose old memory surfaces as legacy_import_pending without rewriting them."""
    rows = []
    rows.extend(_legacy_stock_rows(db, scope_type=scope_type, scope_key=scope_key, q=q, limit=limit))
    if len(rows) < limit:
        rows.extend(_legacy_ai_rows(
            db, scope_type=scope_type, scope_key=scope_key, q=q, limit=limit - len(rows)
        ))
    return rows[:limit]


def _scenario_rows(db, *, scope_type: str | None, scope_key: str | None, limit: int) -> list[dict]:
    _ensure_schema(db)
    clauses = ["trust_state != 'archived'"]
    params: dict[str, Any] = {"limit": limit}
    if scope_type is not None:
        clauses.append("scope_type = :scope_type")
        params["scope_type"] = scope_type
    if scope_key is not None:
        clauses.append("scope_key = :scope_key")
        params["scope_key"] = scope_key
    rows = db.execute(text(f"""
        SELECT id, scope_type, scope_key, title, summary, atom_ids_json, trust_state
        FROM memory_scenarios
        WHERE {' AND '.join(clauses)}
        ORDER BY updated_at DESC, id DESC
        LIMIT :limit
    """), params).all()  # noqa: S608 - clauses are fixed literals plus bound params.
    return [
        {
            "id": row.id,
            "scope_type": row.scope_type,
            "scope_key": row.scope_key,
            "title": row.title,
            "summary": row.summary,
            "atom_ids": _loads(row.atom_ids_json) or [],
            "trust_state": row.trust_state,
        }
        for row in rows
    ]


def _profile_rows(db, *, limit: int) -> list[dict]:
    _ensure_schema(db)
    rows = db.execute(text("""
        SELECT id, profile_type, profile_key, summary, atom_ids_json, trust_state
        FROM memory_profiles
        WHERE trust_state != 'archived'
        ORDER BY updated_at DESC, id DESC
        LIMIT :limit
    """), {"limit": limit}).all()
    return [
        {
            "id": row.id,
            "profile_type": row.profile_type,
            "profile_key": row.profile_key,
            "summary": row.summary,
            "atom_ids": _loads(row.atom_ids_json) or [],
            "trust_state": row.trust_state,
        }
        for row in rows
    ]


def _format_section(title: str, rows: list[dict], *, id_key: str = "id") -> str:
    if not rows:
        return ""
    lines = [title]
    for row in rows:
        ref = row.get(id_key)
        trust = row.get("trust_state", "-")
        kind = row.get("memory_type") or row.get("title") or row.get("profile_type") or "-"
        lines.append(f"- [{kind}|{trust}|id={ref}] {row.get('summary', '')}")
    return "\n".join(lines)


def build_l0_context(
    db,
    *,
    scope_type: str | None = None,
    scope_key: str | None = None,
    query: str | None = None,
    limit: int = 8,
    include_pending: bool = True,
    include_legacy: bool = True,
    record_usage: bool = True,
) -> dict:
    """Build a structured L0 context with explicit trust-state separation."""
    _validate(scope_type=scope_type)
    atoms = list_memory_atoms(
        db,
        scope_type=scope_type,
        scope_key=scope_key,
        q=query,
        limit=max(limit * 3, 20),
    )
    trusted = [a for a in atoms if a["trust_state"] == "trusted"][:limit]
    pending = [
        a for a in atoms if a["trust_state"] in {"pending", "raw"}
    ][:limit] if include_pending else []
    legacy = legacy_memory_adapter(
        db, scope_type=scope_type, scope_key=scope_key, q=query, limit=limit
    ) if include_legacy else []
    scenarios = _scenario_rows(db, scope_type=scope_type, scope_key=scope_key, limit=4)
    profiles = _profile_rows(db, limit=4)

    used_atom_ids = [int(a["id"]) for a in trusted + pending]
    if record_usage and used_atom_ids:
        now = _utc_now().isoformat(timespec="seconds")
        stmt = text(
            "UPDATE memory_atoms SET last_used_at = :now WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        db.execute(stmt, {"now": now, "ids": used_atom_ids})
        db.commit()
    if record_usage:
        audit_write(
            db,
            "l0_memory.recall",
            (
                f"scope={scope_type}:{scope_key} trusted={len(trusted)} "
                f"pending={len(pending)} legacy={len(legacy)}"
            ),
            related_symbol=scope_key if scope_type == "stock" else None,
            related_scope=scope_type,
        )

    sections = [
        _format_section("【L0 trusted memory】", trusted),
        _format_section("【L0 pending/raw memory】", pending),
        _format_section("【L0 scenario summaries】", scenarios),
        _format_section("【L0 profiles】", profiles),
        _format_section("【L0 legacy memory（未默认可信）】", legacy, id_key="legacy_id"),
    ]
    text_value = "\n\n".join(section for section in sections if section)
    return {
        "scope_type": scope_type,
        "scope_key": scope_key,
        "trusted_memory": trusted,
        "pending_memory": pending,
        "legacy_memory": legacy,
        "scenario_summaries": scenarios,
        "profile_summaries": profiles,
        "drilldown_refs": [
            {"type": "memory_atom", "id": atom_id} for atom_id in used_atom_ids
        ],
        "text": text_value,
        "used_memory_atom_ids": used_atom_ids,
    }
