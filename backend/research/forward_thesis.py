"""
M39 Forward Thesis Beta — pure storage layer.

Exposes six injectable-Session functions:
  create_forward_thesis, get_forward_thesis, list_forward_theses,
  update_forward_thesis_status, update_confidence_band, attach_evidence_manifest

No LLM calls.  No writes to Signal / DecisionRun / M29 / quant-weight / ai_memory / scoring tables.
Routes deferred to M40.

confidence_low / confidence_high are a bounded-judgment band only — they are NOT a buy score,
NOT a signal score, NOT a composite_score, and are NEVER read by the scoring path.

evidence_manifest_json stores pointer references only; it never copies or mutates source
artifacts (UniverseSnapshot rows, ReviewCase rows, m27/m29 shadow files).
The actual artifacts remain in their source storage.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.config import settings
from backend.memory.audit_log import audit_write

# ---------------------------------------------------------------------------
# Status state machine
# ---------------------------------------------------------------------------

FORWARD_THESIS_STATUSES: set[str] = {
    "draft",
    "active",
    "watch",
    "superseded",
    "invalidated",
}

FORWARD_THESIS_TRANSITIONS: set[tuple[str, str]] = {
    ("draft", "active"),
    ("draft", "watch"),
    ("draft", "invalidated"),
    ("active", "watch"),
    ("active", "superseded"),
    ("active", "invalidated"),
    ("watch", "active"),
    ("watch", "superseded"),
    ("watch", "invalidated"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _row_to_dict(row) -> dict:
    """Serialize a ForwardThesis ORM row to a plain dict.

    Fields emitted: id, symbol, statement, status, horizon_date,
    confidence_low, confidence_high, evidence_manifest,
    invalidation_conditions, follow_up_metrics, next_review_date,
    review_cadence_days, thesis_id, theme_hypothesis_id,
    universe_snapshot_id, created_at, updated_at.

    NOTE: No field named buy_score, composite_score, recommendation,
    signal_score, entry_signal, price_target, direction, or
    predicted_move is emitted.  confidence_low / confidence_high are
    a bounded-judgment band only — NOT buy scores.
    """
    return {
        "id": row.id,
        "symbol": row.symbol,
        "statement": row.statement,
        "status": row.status,
        "horizon_date": row.horizon_date,
        "confidence_low": row.confidence_low,
        "confidence_high": row.confidence_high,
        "evidence_manifest": json.loads(row.evidence_manifest_json) if row.evidence_manifest_json else [],
        "invalidation_conditions": json.loads(row.invalidation_conditions_json) if row.invalidation_conditions_json else [],
        "follow_up_metrics": json.loads(row.follow_up_metrics_json) if row.follow_up_metrics_json else [],
        "next_review_date": row.next_review_date,
        "review_cadence_days": row.review_cadence_days,
        "thesis_id": row.thesis_id,
        "theme_hypothesis_id": row.theme_hypothesis_id,
        "universe_snapshot_id": row.universe_snapshot_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


# ---------------------------------------------------------------------------
# Storage functions
# ---------------------------------------------------------------------------

def create_forward_thesis(
    db,
    *,
    statement: str,
    horizon_date: str | None = None,
    thesis_id: int | None = None,
    theme_hypothesis_id: int | None = None,
    universe_snapshot_id: int | None = None,
    confidence_low: float | None = None,
    confidence_high: float | None = None,
    invalidation_conditions: list | None = None,
    follow_up_metrics: list | None = None,
    evidence_manifest: list | None = None,
    next_review_date: str | None = None,
    review_cadence_days: int | None = None,
    symbol: str | None = None,
    status: str = "draft",
) -> dict:
    """Create a ForwardThesis row, or return the existing one if (symbol, statement, horizon_date) already exists.

    Validates:
      - status is in FORWARD_THESIS_STATUSES
      - confidence_low <= confidence_high when both are provided

    confidence_low and confidence_high are clamped to [0.0, 1.0] at write time.
    Raises ValueError on invalid status or band ordering violation.
    Always calls audit_write after a successful insert.
    Returns {} when forward_thesis_enabled=False.
    """
    if not settings.forward_thesis_enabled:
        return {}

    if status not in FORWARD_THESIS_STATUSES:
        raise ValueError(f"invalid status: {status!r}; must be one of {FORWARD_THESIS_STATUSES}")

    # Validate and clamp confidence band
    cl: float | None = None
    ch: float | None = None
    if confidence_low is not None:
        cl = _clamp(confidence_low)
    if confidence_high is not None:
        ch = _clamp(confidence_high)
    if cl is not None and ch is not None and cl > ch:
        raise ValueError(
            f"confidence_low ({cl}) must not exceed confidence_high ({ch})"
        )

    from backend.data.database import ForwardThesis

    horizon_filter = (
        ForwardThesis.horizon_date.is_(None)
        if horizon_date is None
        else ForwardThesis.horizon_date == horizon_date
    )
    existing = (
        db.query(ForwardThesis)
        .filter(
            ForwardThesis.symbol == symbol,
            ForwardThesis.statement == statement,
            horizon_filter,
        )
        .first()
    )
    if existing is not None:
        return _row_to_dict(existing)

    now = _utc_now()
    row = ForwardThesis(
        symbol=symbol,
        statement=statement,
        status=status,
        horizon_date=horizon_date,
        confidence_low=cl,
        confidence_high=ch,
        evidence_manifest_json=json.dumps(evidence_manifest or [], ensure_ascii=False, default=str),
        invalidation_conditions_json=json.dumps(invalidation_conditions or [], ensure_ascii=False, default=str),
        follow_up_metrics_json=json.dumps(follow_up_metrics or [], ensure_ascii=False, default=str),
        next_review_date=next_review_date,
        review_cadence_days=review_cadence_days,
        thesis_id=thesis_id,
        theme_hypothesis_id=theme_hypothesis_id,
        universe_snapshot_id=universe_snapshot_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(
        db,
        "forward_thesis.create",
        f"forward_thesis created: {statement[:80]!r} horizon={horizon_date}",
    )
    db.commit()
    return _row_to_dict(row)


def get_forward_thesis(db, forward_thesis_id: int) -> dict | None:
    """Return a ForwardThesis dict by id, or None if not found. (read-only, no audit)"""
    from backend.data.database import ForwardThesis

    row = db.query(ForwardThesis).filter(ForwardThesis.id == forward_thesis_id).first()
    return _row_to_dict(row) if row is not None else None


def list_forward_theses(
    db,
    *,
    symbol: str | None = None,
    status: str | None = None,
    theme_hypothesis_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return ForwardThesis rows filtered by symbol, status, and/or theme_hypothesis_id,
    sorted by updated_at DESC."""
    from backend.data.database import ForwardThesis

    q = db.query(ForwardThesis)
    if symbol is not None:
        q = q.filter(ForwardThesis.symbol == symbol)
    if status is not None:
        q = q.filter(ForwardThesis.status == status)
    if theme_hypothesis_id is not None:
        q = q.filter(ForwardThesis.theme_hypothesis_id == theme_hypothesis_id)
    rows = q.order_by(ForwardThesis.updated_at.desc()).limit(limit).all()
    return [_row_to_dict(r) for r in rows]


def update_forward_thesis_status(
    db,
    forward_thesis_id: int,
    new_status: str,
    *,
    note: str | None = None,
) -> dict:
    """Transition a ForwardThesis to a new status.

    Validates:
      - new_status is in FORWARD_THESIS_STATUSES
      - (current_status, new_status) is in FORWARD_THESIS_TRANSITIONS

    Raises ValueError on validation failure or missing row.
    Always calls audit_write on success.
    """
    if not settings.forward_thesis_enabled:
        return {}

    if new_status not in FORWARD_THESIS_STATUSES:
        raise ValueError(f"invalid status: {new_status!r}; must be one of {FORWARD_THESIS_STATUSES}")

    from backend.data.database import ForwardThesis

    row = db.query(ForwardThesis).filter(ForwardThesis.id == forward_thesis_id).first()
    if row is None:
        raise ValueError(f"forward_thesis {forward_thesis_id} not found")

    if (row.status, new_status) not in FORWARD_THESIS_TRANSITIONS:
        raise ValueError(
            f"transition {row.status!r} -> {new_status!r} is not allowed"
        )

    old_status = row.status
    row.status = new_status
    row.updated_at = _utc_now()
    db.flush()

    detail = f"{old_status} -> {new_status}"
    if note:
        detail += f"; {note}"
    audit_write(db, "forward_thesis.status", detail)
    db.commit()
    return _row_to_dict(row)


def update_confidence_band(
    db,
    forward_thesis_id: int,
    *,
    confidence_low: float,
    confidence_high: float,
    as_of: str,
) -> dict:
    """Update the confidence band on a ForwardThesis row.

    Both values are clamped to [0.0, 1.0].
    Raises ValueError if confidence_low > confidence_high after clamping, or if row not found.
    Always calls audit_write on success.
    """
    if not settings.forward_thesis_enabled:
        return {}

    cl = _clamp(confidence_low)
    ch = _clamp(confidence_high)
    if cl > ch:
        raise ValueError(
            f"confidence_low ({cl}) must not exceed confidence_high ({ch})"
        )

    from backend.data.database import ForwardThesis

    row = db.query(ForwardThesis).filter(ForwardThesis.id == forward_thesis_id).first()
    if row is None:
        raise ValueError(f"forward_thesis {forward_thesis_id} not found")

    row.confidence_low = cl
    row.confidence_high = ch
    row.updated_at = _utc_now()
    db.flush()
    audit_write(
        db,
        "forward_thesis.confidence_band",
        f"band updated low={cl:.3f} high={ch:.3f} as_of={as_of}",
    )
    db.commit()
    return _row_to_dict(row)


def attach_evidence_manifest(
    db,
    forward_thesis_id: int,
    *,
    manifest: list[dict],
    as_of: str,
) -> dict:
    """Replace the evidence_manifest_json on a ForwardThesis row with the given pointer list.

    Each element in manifest should be a pointer dict with shape:
      {kind: str, ref: str|int, as_of: str|None, summary: str|None}

    Valid kind values: 'universe_snapshot', 'review_case', 'm29_ledger_entry', 'ledger_snapshot'.
    M39 stores ONLY pointer fields — no artifact payload is copied into the DB.

    Raises ValueError if forward_thesis_id not found.
    Always calls audit_write on success.
    """
    if not settings.forward_thesis_enabled:
        return {}

    from backend.data.database import ForwardThesis

    row = db.query(ForwardThesis).filter(ForwardThesis.id == forward_thesis_id).first()
    if row is None:
        raise ValueError(f"forward_thesis {forward_thesis_id} not found")

    row.evidence_manifest_json = json.dumps(manifest, ensure_ascii=False, default=str)
    row.updated_at = _utc_now()
    db.flush()
    audit_write(
        db,
        "forward_thesis.evidence_manifest",
        f"evidence_manifest updated as_of={as_of} n_items={len(manifest)}",
    )
    db.commit()
    return _row_to_dict(row)
