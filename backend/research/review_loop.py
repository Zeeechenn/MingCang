"""
M37 Review / Calibration / Memory Loop — pure storage layer.

Exposes eight injectable-Session functions:
  create_review_case, get_review_case, list_review_cases,
  create_memory_candidate, get_memory_candidate, list_memory_candidates,
  promote_memory, reject_memory_candidate

No LLM calls. No writes to Signal / DecisionRun / M29 / ai_memory tables.
Memory candidates are ALWAYS created in 'pending' state.
Promotion to 'trusted' is only possible via the explicit gated promote_memory
function, which is never called from any LLM agent code path.
Routes deferred to M40.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.memory.audit_log import audit_write
from backend.memory.stock_memory import MEMORY_TYPES

CANDIDATE_TRUST_VALUES = {"pending", "trusted", "rejected"}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _rc_to_dict(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "as_of": row.as_of,
        "signal_id": row.signal_id,
        "thesis_id": row.thesis_id,
        "research_case_symbol": row.research_case_symbol,
        "research_case_as_of": row.research_case_as_of,
        "position_case_ref_json": row.position_case_ref_json,
        "outcome_correct": row.outcome_correct,
        "next_day_return": row.next_day_return,
        "composite_score": row.composite_score,
        "recommendation": row.recommendation,
        "attribution": json.loads(row.attribution_json) if row.attribution_json else None,
        "review_payload": json.loads(row.review_payload_json) if row.review_payload_json else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _cand_to_dict(row) -> dict:
    return {
        "id": row.id,
        "review_case_id": row.review_case_id,
        "memory_atom_id": row.memory_atom_id,
        "stock_memory_item_id": row.stock_memory_item_id,
        "symbol": row.symbol,
        "summary": row.summary,
        "memory_type": row.memory_type,
        "source_trust": row.source_trust,
        "source_ref": row.source_ref,
        "importance": row.importance,
        "confidence": row.confidence,
        "promoted_at": _iso(row.promoted_at),
        "rejected_at": _iso(row.rejected_at),
        "note": row.note,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


# ── ReviewCase CRUD ──────────────────────────────────────────────────────────

def create_review_case(
    db,
    *,
    symbol: str,
    as_of: str,
    signal_id: int | None = None,
    thesis_id: int | None = None,
    research_case_as_of: str | None = None,
    review_payload: dict | None = None,
) -> dict:
    """Insert a ReviewCase row and return its dict representation.

    Idempotent: if a row with the same (symbol, as_of) already exists
    (UniqueConstraint) the existing row is returned without modification.
    Outcome data (outcome_correct, next_day_return, composite_score,
    recommendation, attribution_json, review_payload_json) is extracted
    from review_payload when provided.
    Always calls audit_write after a successful insert.
    """
    from backend.data.database import ReviewCase

    existing = (
        db.query(ReviewCase)
        .filter(ReviewCase.symbol == symbol, ReviewCase.as_of == as_of)
        .first()
    )
    if existing is not None:
        return _rc_to_dict(existing)

    # Extract outcome fields from review_payload if present
    outcome_correct = None
    next_day_return = None
    composite_score = None
    recommendation = None
    attribution_json = None
    review_payload_json = None

    if review_payload is not None:
        outcome_correct = review_payload.get("correct")
        next_day_return = review_payload.get("next_day_return")
        composite_score = review_payload.get("composite_score")
        recommendation = review_payload.get("recommendation")
        attribution = review_payload.get("attribution")
        if attribution is not None:
            attribution_json = json.dumps(attribution, ensure_ascii=False)
        review_payload_json = json.dumps(review_payload, ensure_ascii=False, default=str)

    now = _utc_now()
    row = ReviewCase(
        symbol=symbol,
        as_of=as_of,
        signal_id=signal_id,
        thesis_id=thesis_id,
        research_case_symbol=symbol,
        research_case_as_of=research_case_as_of,
        outcome_correct=outcome_correct,
        next_day_return=next_day_return,
        composite_score=composite_score,
        recommendation=recommendation,
        attribution_json=attribution_json,
        review_payload_json=review_payload_json,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(
        db,
        "review_loop.create_review_case",
        f"review_case created symbol={symbol} as_of={as_of}",
        related_symbol=symbol,
    )
    db.commit()
    return _rc_to_dict(row)


def get_review_case(db, review_case_id: int) -> dict | None:
    """Return the ReviewCase with the given id, or None. (read-only, no audit)"""
    from backend.data.database import ReviewCase

    row = db.query(ReviewCase).filter(ReviewCase.id == review_case_id).first()
    return _rc_to_dict(row) if row is not None else None


def list_review_cases(
    db,
    *,
    symbol: str | None = None,
    thesis_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return review cases filtered by symbol and/or thesis_id, sorted by as_of DESC."""
    from backend.data.database import ReviewCase

    q = db.query(ReviewCase)
    if symbol is not None:
        q = q.filter(ReviewCase.symbol == symbol)
    if thesis_id is not None:
        q = q.filter(ReviewCase.thesis_id == thesis_id)
    rows = q.order_by(ReviewCase.as_of.desc()).limit(limit).all()
    return [_rc_to_dict(r) for r in rows]


# ── MemoryPromotionCandidate CRUD ─────────────────────────────────────────────

def create_memory_candidate(
    db,
    *,
    review_case_id: int | None = None,
    symbol: str,
    summary: str,
    memory_type: str,
    importance: int = 3,
    confidence: float = 0.5,
    source_ref: str | None = None,
    note: str | None = None,
) -> dict:
    """Insert a MemoryPromotionCandidate with source_trust='pending' (hardcoded).

    source_trust is NOT accepted as a parameter — callers cannot override it.
    The only path to 'trusted' is the gated promote_memory function.

    Idempotent only when review_case_id or source_ref provides an explicit key.
    When a key is present, both review_case_id and source_ref participate in the
    match, with NULL matched explicitly. This prevents a broad source_ref rerun
    from swallowing a later case-specific lesson. Calls without either key
    always create a new candidate so unrelated lessons are not merged broadly.
    Raises ValueError on invalid memory_type.
    Always calls audit_write after a successful insert.
    """
    if memory_type not in MEMORY_TYPES:
        raise ValueError(
            f"invalid memory_type: {memory_type!r}; must be one of {MEMORY_TYPES}"
        )

    from backend.data.database import MemoryPromotionCandidate

    if review_case_id is not None or source_ref is not None:
        q = (
            db.query(MemoryPromotionCandidate)
            .filter(
                MemoryPromotionCandidate.symbol == symbol,
                MemoryPromotionCandidate.memory_type == memory_type,
                MemoryPromotionCandidate.source_trust == "pending",
            )
        )
        if review_case_id is not None:
            q = q.filter(MemoryPromotionCandidate.review_case_id == review_case_id)
        else:
            q = q.filter(MemoryPromotionCandidate.review_case_id.is_(None))
        if source_ref is not None:
            q = q.filter(MemoryPromotionCandidate.source_ref == source_ref)
        else:
            q = q.filter(MemoryPromotionCandidate.source_ref.is_(None))
        existing = q.first()
        if existing is not None:
            return _cand_to_dict(existing)

    now = _utc_now()
    row = MemoryPromotionCandidate(
        review_case_id=review_case_id,
        symbol=symbol,
        summary=summary,
        memory_type=memory_type,
        source_trust="pending",  # hardcoded — no caller override possible
        source_ref=source_ref,
        importance=max(1, min(5, int(importance))),
        confidence=max(0.0, min(1.0, float(confidence))),
        note=note,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(
        db,
        "review_loop.create_memory_candidate",
        f"candidate created symbol={symbol} type={memory_type} trust=pending",
        related_symbol=symbol,
    )
    db.commit()
    return _cand_to_dict(row)


def get_memory_candidate(db, candidate_id: int) -> dict | None:
    """Return the MemoryPromotionCandidate with the given id, or None. (read-only)"""
    from backend.data.database import MemoryPromotionCandidate

    row = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.id == candidate_id)
        .first()
    )
    return _cand_to_dict(row) if row is not None else None


def list_memory_candidates(
    db,
    *,
    symbol: str | None = None,
    source_trust: str | None = None,
    review_case_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return candidates filtered by symbol, source_trust, and/or review_case_id,
    sorted by created_at DESC."""
    from backend.data.database import MemoryPromotionCandidate

    q = db.query(MemoryPromotionCandidate)
    if symbol is not None:
        q = q.filter(MemoryPromotionCandidate.symbol == symbol)
    if source_trust is not None:
        q = q.filter(MemoryPromotionCandidate.source_trust == source_trust)
    if review_case_id is not None:
        q = q.filter(MemoryPromotionCandidate.review_case_id == review_case_id)
    rows = q.order_by(MemoryPromotionCandidate.created_at.desc()).limit(limit).all()
    return [_cand_to_dict(r) for r in rows]


# ── Gated promotion / rejection ───────────────────────────────────────────────
# These functions are the ONLY path to 'trusted' / 'rejected'.
# They are NOT imported or called from any LLM agent code path
# (backend/agents/, backend/decision/harness.py, backend/skills/).
# Routes that call them are deferred to M40.

def promote_memory(db, candidate_id: int, *, confirmed_by: str) -> dict:
    """GATED: Promote a pending candidate to 'trusted' and materialise a StockMemoryItem.

    This is the ONLY function that writes source_trust='trusted'.
    It also creates/updates a StockMemoryItem with status='active' and stores
    the returned row id in stock_memory_item_id.
    Raises ValueError if the candidate is not in 'pending' state.
    Always calls audit_write on success.

    confirmed_by: str identifying the human actor confirming this promotion.
    """
    from backend.data.database import MemoryPromotionCandidate
    from backend.memory.stock_memory import create_stock_memory

    row = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.id == candidate_id)
        .first()
    )
    if row is None:
        raise ValueError(f"memory candidate {candidate_id} not found")
    if row.source_trust != "pending":
        raise ValueError(
            f"candidate {candidate_id} is already in state {row.source_trust!r}; "
            "only 'pending' candidates can be promoted"
        )

    atom_source_ref = (
        row.source_ref
        or f"m37_candidate_{candidate_id}_{row.symbol}_{row.memory_type}"
    )
    from backend.memory.l0_memory import create_memory_atom, promote_atom

    atom = create_memory_atom(
        db,
        scope_type="stock",
        scope_key=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_promotion_candidate",
        source_ref=f"l0:{atom_source_ref}",
        trust_state="pending",
        evidence={
            "candidate_id": candidate_id,
            "review_case_id": row.review_case_id,
            "candidate_source_ref": row.source_ref,
            "confirmed_by": confirmed_by,
        },
        importance=row.importance,
        confidence=row.confidence,
        review_case_id=row.review_case_id,
    )

    # Materialise the candidate as a legacy StockMemoryItem for compatibility.
    source_ref = (
        row.source_ref
        or f"m37_promotion_{candidate_id}_{row.symbol}_{row.memory_type}"
    )
    mem = create_stock_memory(
        db,
        symbol=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_promotion",
        source_ref=source_ref,
        importance=row.importance,
        confidence=row.confidence,
        status="active",
        evidence={"memory_atom_id": atom["id"], "review_case_id": row.review_case_id},
    )
    atom = create_memory_atom(
        db,
        scope_type="stock",
        scope_key=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_promotion_candidate",
        source_ref=f"l0:{atom_source_ref}",
        trust_state="pending",
        evidence={
            "candidate_id": candidate_id,
            "review_case_id": row.review_case_id,
            "candidate_source_ref": row.source_ref,
            "confirmed_by": confirmed_by,
            "stock_memory_item_id": mem["id"],
        },
        importance=row.importance,
        confidence=row.confidence,
        review_case_id=row.review_case_id,
        stock_memory_item_id=mem["id"],
    )
    atom = promote_atom(db, atom["id"], confirmed_by=confirmed_by)

    now = _utc_now()
    row.source_trust = "trusted"
    row.memory_atom_id = atom["id"]
    row.stock_memory_item_id = mem["id"]
    row.promoted_at = now
    row.updated_at = now
    db.flush()

    audit_write(
        db,
        "memory_promotion.confirm",
        (
            f"candidate {candidate_id} promoted by {confirmed_by!r}; "
            f"memory_atom_id={atom['id']} stock_memory_item_id={mem['id']} "
            f"symbol={row.symbol}"
        ),
        related_symbol=row.symbol,
    )
    db.commit()
    return _cand_to_dict(row)


def reject_memory_candidate(
    db,
    candidate_id: int,
    *,
    confirmed_by: str,
    note: str | None = None,
) -> dict:
    """GATED: Reject a pending candidate (terminal state — no further transitions).

    This is the ONLY function that writes source_trust='rejected'.
    Raises ValueError if the candidate is not in 'pending' state.
    Always calls audit_write on success.

    confirmed_by: str identifying the human actor confirming this rejection.
    """
    from backend.data.database import MemoryPromotionCandidate

    row = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.id == candidate_id)
        .first()
    )
    if row is None:
        raise ValueError(f"memory candidate {candidate_id} not found")
    if row.source_trust != "pending":
        raise ValueError(
            f"candidate {candidate_id} is already in state {row.source_trust!r}; "
            "only 'pending' candidates can be rejected"
        )

    atom_source_ref = (
        row.source_ref
        or f"m37_rejected_{candidate_id}_{row.symbol}_{row.memory_type}"
    )
    from backend.memory.l0_memory import create_memory_atom, refute_atom

    atom = create_memory_atom(
        db,
        scope_type="stock",
        scope_key=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_rejected_candidate",
        source_ref=f"l0:{atom_source_ref}",
        trust_state="pending",
        evidence={
            "candidate_id": candidate_id,
            "review_case_id": row.review_case_id,
            "candidate_source_ref": row.source_ref,
            "confirmed_by": confirmed_by,
        },
        importance=row.importance,
        confidence=row.confidence,
        review_case_id=row.review_case_id,
    )
    atom = refute_atom(db, atom["id"], confirmed_by=confirmed_by, reason=note)

    now = _utc_now()
    row.source_trust = "rejected"
    row.memory_atom_id = atom["id"]
    row.rejected_at = now
    row.updated_at = now
    if note:
        row.note = note
    db.flush()

    audit_write(
        db,
        "memory_promotion.reject",
        (
            f"candidate {candidate_id} rejected by {confirmed_by!r}; "
            f"symbol={row.symbol}"
            + (f"; note={note!r}" if note else "")
        ),
        related_symbol=row.symbol,
    )
    db.commit()
    return _cand_to_dict(row)
