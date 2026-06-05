"""M9.1/M9.2 memory management API.

Read-only endpoints (M9.1):
  GET  /api/memory/overview      — counts, scopes, categories, last updated.
  GET  /api/memory/list          — paginated active rows with filters.
  GET  /api/memory/audit         — FTS5 search over audit_log_fts.
  GET  /api/memory/layered       — list rows from decision_memory_layered.

Mutating endpoints (M9.2 — receiver-controlled metadata edits only):
  DELETE /api/memory/{id}        — forget by id.
  POST   /api/memory/{id}/pin    — set ttl_days=NULL (pin forever).
  PATCH  /api/memory/{id}        — update ttl_days and/or category.

Editing raw `value` text is **not exposed** by design: it would break
`UNIQUE(key, scope)` and the structured-category contract.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.agent.security import agent_mode
from backend.data.database import get_db
from backend.memory.ai_memory import list_active
from backend.memory.audit_log import audit_search, audit_write
from backend.memory.l0_memory import (
    build_l0_context,
    list_memory_atoms,
    promote_atom,
    refute_atom,
)
from backend.memory.stock_memory import (
    archive_stock_memory,
    build_memory_context,
    delete_stock_memory,
    list_stock_memories,
)
from backend.memory.stock_memory import (
    patch_stock_memory as patch_stock_memory_item,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _iso(value) -> str | None:
    if value is None:
        return None
    return str(value)


def local_human_l0_gate(request: Request) -> None:
    """Allow L0 trust decisions only from local human-operated paths."""
    if agent_mode() == "remote":
        raise HTTPException(
            status_code=403,
            detail="L0 memory promote/refute is local human gated",
        )


@router.get("/overview")
def memory_overview(db: Session = Depends(get_db)) -> dict:
    """Aggregate counts of active ai_memory rows by scope and category."""
    rows = list_active(db)
    by_scope: dict[str, int] = {}
    by_category: dict[str, int] = {}
    last_updated: str | None = None
    for r in rows:
        by_scope[r["scope"]] = by_scope.get(r["scope"], 0) + 1
        cat = r["category"] or "(none)"
        by_category[cat] = by_category.get(cat, 0) + 1
        ts = _iso(r["updated_at"])
        if ts and (last_updated is None or ts > last_updated):
            last_updated = ts
    layered_count = db.execute(text(
        "SELECT count(*) FROM decision_memory_layered"
    )).scalar() or 0
    return {
        "total_active": len(rows),
        "by_scope": by_scope,
        "by_category": by_category,
        "last_updated": last_updated,
        "layered_rows": layered_count,
    }


@router.get("/list")
def memory_list(
    scope: str | None = None,
    category: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Paginated active rows with optional scope/category/key-substring filters."""
    rows = list_active(db, scope=scope, category=category)
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["key"] or "").lower() or ql in (r["value"] or "").lower()]
    rows = rows[:limit]
    for r in rows:
        r["created_at"] = _iso(r["created_at"])
        r["updated_at"] = _iso(r["updated_at"])
    return {"rows": rows, "count": len(rows)}


@router.get("/audit")
def memory_audit(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """FTS5 search over audit_log_fts."""
    results = audit_search(db, q, limit=limit)
    return {"rows": results, "count": len(results)}


@router.get("/layered")
def memory_layered(db: Session = Depends(get_db)) -> dict:
    """List decision_memory_layered rows with content size only (not full text)."""
    from backend.decision.memory_layered import _GLOBAL_SENTINEL
    rows = db.execute(text(
        "SELECT id, symbol, layer, length(content) AS size, updated_at "
        "FROM decision_memory_layered ORDER BY layer, symbol"
    )).all()
    return {
        "rows": [
            {
                "id": r.id,
                "symbol": None if r.symbol == _GLOBAL_SENTINEL else r.symbol,
                "layer": r.layer,
                "size": r.size,
                "updated_at": _iso(r.updated_at),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/l0/context")
def l0_memory_context(
    scope_type: str | None = None,
    scope_key: str | None = None,
    q: str | None = None,
    limit: int = Query(default=8, ge=1, le=50),
    include_pending: bool = True,
    include_legacy: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    """Prompt-ready L0 context with trusted/pending/legacy separated."""
    try:
        return build_l0_context(
            db,
            scope_type=scope_type,
            scope_key=scope_key,
            query=q,
            limit=limit,
            include_pending=include_pending,
            include_legacy=include_legacy,
            record_usage=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/l0/atoms")
def l0_memory_atoms(
    scope_type: str | None = None,
    scope_key: str | None = None,
    trust_state: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """List L0 memory atoms."""
    try:
        rows = list_memory_atoms(
            db,
            scope_type=scope_type,
            scope_key=scope_key,
            trust_state=trust_state,
            q=q,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": rows, "count": len(rows)}


class L0TrustPayload(BaseModel):
    confirmed_by: str
    reason: str | None = None


@router.post(
    "/l0/atoms/{atom_id}/promote",
    dependencies=[
        Depends(agent_write_guard("l0_memory.promote")),
        Depends(local_human_l0_gate),
    ],
)
def l0_memory_atom_promote(
    atom_id: int,
    payload: L0TrustPayload,
    db: Session = Depends(get_db),
) -> dict:
    """HUMAN-GATED: promote a raw/pending/legacy atom to trusted."""
    if not payload.confirmed_by.strip():
        raise HTTPException(status_code=400, detail="confirmed_by must be non-empty")
    try:
        return promote_atom(db, atom_id, confirmed_by=payload.confirmed_by)
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post(
    "/l0/atoms/{atom_id}/refute",
    dependencies=[
        Depends(agent_write_guard("l0_memory.refute")),
        Depends(local_human_l0_gate),
    ],
)
def l0_memory_atom_refute(
    atom_id: int,
    payload: L0TrustPayload,
    db: Session = Depends(get_db),
) -> dict:
    """HUMAN-GATED: mark an L0 atom refuted."""
    if not payload.confirmed_by.strip():
        raise HTTPException(status_code=400, detail="confirmed_by must be non-empty")
    try:
        return refute_atom(
            db,
            atom_id,
            confirmed_by=payload.confirmed_by,
            reason=payload.reason,
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/stock/{symbol}/context")
def stock_memory_context(
    symbol: str,
    task_type: str = "research",
    q: str | None = None,
    limit: int = Query(default=8, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """Prompt-ready structured memory context for one stock."""
    if not isinstance(limit, int):
        limit = 8
    return build_memory_context(
        db,
        symbol=symbol,
        query=q,
        task_type=task_type,
        limit=limit,
        record_usage=False,
        include_l0=True,
    )


@router.get("/stock-items")
def stock_memory_items(
    symbol: str | None = None,
    type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """List structured stock-memory rows."""
    rows = list_stock_memories(
        db,
        symbol=symbol,
        memory_type=type,
        status=status,
        q=q,
        limit=limit,
    )
    return {"rows": rows, "count": len(rows)}


class StockMemoryPatchPayload(BaseModel):
    status: str | None = None
    importance: int | None = None
    ttl_days: int | None = None
    clear_ttl: bool = False


@router.post(
    "/stock-items/{row_id}/archive",
    dependencies=[Depends(agent_write_guard("stock_memory.archive"))],
)
def stock_memory_archive(row_id: int, db: Session = Depends(get_db)) -> dict:
    """Archive a structured stock-memory row."""
    try:
        archive_stock_memory(db, row_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"stock memory id {row_id} not found",
        ) from exc
    return {"archived": True, "id": row_id}


@router.patch(
    "/stock-items/{row_id}",
    dependencies=[Depends(agent_write_guard("stock_memory.patch"))],
)
def stock_memory_patch(
    row_id: int,
    payload: StockMemoryPatchPayload,
    db: Session = Depends(get_db),
) -> dict:
    """Patch status, importance and/or TTL for a structured stock-memory row."""
    try:
        row = patch_stock_memory_item(
            db,
            row_id,
            status=payload.status,
            importance=payload.importance,
            ttl_days=payload.ttl_days,
            clear_ttl=payload.clear_ttl,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"stock memory id {row_id} not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"patched": True, "id": row_id, "row": row}


@router.delete(
    "/stock-items/{row_id}",
    dependencies=[Depends(agent_write_guard("stock_memory.delete"))],
)
def stock_memory_delete(row_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete a structured stock-memory row."""
    try:
        delete_stock_memory(db, row_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"stock memory id {row_id} not found",
        ) from exc
    return {"deleted": True, "id": row_id}


class PatchPayload(BaseModel):
    ttl_days: int | None = None
    category: str | None = None
    clear_ttl: bool = False


def _row_by_id(db: Session, row_id: int):
    row = db.execute(text(
        "SELECT id, key, scope, category, ttl_days FROM ai_memory WHERE id = :id"
    ), {"id": row_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"memory id {row_id} not found")
    return row


@router.delete(
    "/{row_id}",
    dependencies=[Depends(agent_write_guard("memory.forget"))],
)
def memory_delete(row_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete an ai_memory row by id. Backups make this recoverable."""
    row = _row_by_id(db, row_id)
    db.execute(text("DELETE FROM ai_memory WHERE id = :id"), {"id": row_id})
    db.commit()
    audit_write(
        db,
        "memory.forget",
        f"id={row_id} key={row.key} scope={row.scope} removed=True via=api",
        related_scope=row.scope,
    )
    return {"deleted": True, "id": row_id}


@router.post(
    "/{row_id}/pin",
    dependencies=[Depends(agent_write_guard("memory.pin"))],
)
def memory_pin(row_id: int, db: Session = Depends(get_db)) -> dict:
    """Pin a memory row (clear ttl_days so it never expires)."""
    row = _row_by_id(db, row_id)
    db.execute(text("UPDATE ai_memory SET ttl_days = NULL WHERE id = :id"),
               {"id": row_id})
    db.commit()
    audit_write(
        db,
        "memory.pin",
        f"id={row_id} key={row.key} scope={row.scope}",
        related_scope=row.scope,
    )
    return {"pinned": True, "id": row_id}


@router.patch(
    "/{row_id}",
    dependencies=[Depends(agent_write_guard("memory.patch"))],
)
def memory_patch(
    row_id: int,
    payload: PatchPayload,
    db: Session = Depends(get_db),
) -> dict:
    """Patch ttl_days and/or category. Raw value cannot be edited via API."""
    row = _row_by_id(db, row_id)
    sets: list[str] = []
    params: dict = {"id": row_id}
    if payload.clear_ttl:
        sets.append("ttl_days = NULL")
    elif payload.ttl_days is not None:
        sets.append("ttl_days = :ttl")
        params["ttl"] = payload.ttl_days
    if payload.category is not None:
        sets.append("category = :cat")
        params["cat"] = payload.category
    if not sets:
        raise HTTPException(status_code=400, detail="no editable fields supplied")
    query = "UPDATE ai_memory SET " + ", ".join(sets) + " WHERE id = :id"  # noqa: S608
    db.execute(text(query), params)
    db.commit()
    audit_write(
        db,
        "memory.patch",
        f"id={row_id} key={row.key} scope={row.scope} sets={sets}",
        related_scope=row.scope,
    )
    return {"patched": True, "id": row_id, "fields": sets}
