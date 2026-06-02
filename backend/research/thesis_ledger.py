"""
M35 Thesis Ledger — pure storage layer.

Exposes five injectable-Session functions:
  create_thesis, get_thesis, list_theses, update_thesis_status, append_confidence

No LLM calls. No writes to Signal / DecisionRun / M29 / ai_memory tables.
Routes deferred to M40.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.memory.audit_log import audit_write

THESIS_STATUSES = {"active", "watch", "broken", "retired"}

# Allowed (from_status, to_status) pairs — all others are rejected.
_ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    ("active", "watch"),
    ("active", "broken"),
    ("active", "retired"),
    ("watch", "active"),
    ("watch", "broken"),
    ("watch", "retired"),
    ("broken", "retired"),
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "title": row.title,
        "status": row.status,
        "kill_conditions": json.loads(row.kill_conditions_json) if row.kill_conditions_json else [],
        "update_cadence_days": row.update_cadence_days,
        "research_case_symbol": row.research_case_symbol,
        "research_case_as_of": row.research_case_as_of,
        "review_case_ref": json.loads(row.review_case_ref_json) if row.review_case_ref_json else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _entry_to_dict(entry) -> dict:
    return {
        "id": entry.id,
        "thesis_id": entry.thesis_id,
        "score": entry.score,
        "as_of": entry.as_of,
        "note": entry.note,
        "created_at": _iso(entry.created_at),
    }


def create_thesis(
    db,
    *,
    symbol: str,
    title: str,
    kill_conditions: list[str],
    update_cadence_days: int | None = None,
    research_case_as_of: str | None = None,
    status: str = "active",
) -> dict:
    """Insert a new ThesisRecord.

    Idempotent: if a thesis with the same symbol+title already exists
    (UniqueConstraint) it returns the existing row without modification.
    Raises ValueError on invalid status.
    Always calls audit_write after a successful insert.
    """
    if status not in THESIS_STATUSES:
        raise ValueError(f"invalid status: {status!r}; must be one of {THESIS_STATUSES}")

    from backend.data.database import ThesisRecord

    now = _utc_now()
    existing = (
        db.query(ThesisRecord)
        .filter(ThesisRecord.symbol == symbol, ThesisRecord.title == title)
        .first()
    )
    if existing is not None:
        return _row_to_dict(existing)

    row = ThesisRecord(
        symbol=symbol,
        title=title,
        status=status,
        kill_conditions_json=json.dumps(kill_conditions, ensure_ascii=False),
        update_cadence_days=update_cadence_days,
        research_case_symbol=symbol,
        research_case_as_of=research_case_as_of,
        review_case_ref_json=None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(db, "thesis_ledger.create", f"thesis created: {title!r}", related_symbol=symbol)
    db.commit()
    return _row_to_dict(row)


def get_thesis(db, thesis_id: int) -> dict | None:
    """Return the ThesisRecord with the given id, or None if not found. (read-only, no audit)"""
    from backend.data.database import ThesisRecord

    row = db.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).first()
    return _row_to_dict(row) if row is not None else None


def list_theses(
    db,
    *,
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return theses filtered by symbol and/or status, sorted by updated_at DESC."""
    from backend.data.database import ThesisRecord

    q = db.query(ThesisRecord)
    if symbol is not None:
        q = q.filter(ThesisRecord.symbol == symbol)
    if status is not None:
        q = q.filter(ThesisRecord.status == status)
    rows = q.order_by(ThesisRecord.updated_at.desc()).limit(limit).all()
    return [_row_to_dict(r) for r in rows]


def update_thesis_status(db, thesis_id: int, new_status: str, *, note: str | None = None) -> dict:
    """Transition a thesis to a new status.

    Validates:
      - new_status is in THESIS_STATUSES
      - (current_status, new_status) is in the allowed-transitions allow-list

    Raises ValueError on validation failure or missing thesis.
    Always calls audit_write on success.
    """
    from backend.data.database import ThesisRecord

    if new_status not in THESIS_STATUSES:
        raise ValueError(f"invalid status: {new_status!r}; must be one of {THESIS_STATUSES}")

    row = db.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).first()
    if row is None:
        raise ValueError(f"thesis {thesis_id} not found")

    if (row.status, new_status) not in _ALLOWED_TRANSITIONS:
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
    audit_write(db, "thesis_ledger.status", detail, related_symbol=row.symbol)
    db.commit()
    return _row_to_dict(row)


def append_confidence(
    db,
    thesis_id: int,
    *,
    score: float,
    as_of: str,
    note: str | None = None,
) -> dict:
    """Append a new ThesisConfidenceEntry (append-only — never updates existing entries).

    score is clamped to [0.0, 1.0].
    Raises ValueError if thesis_id does not exist.
    Always calls audit_write on success.
    """
    from backend.data.database import ThesisConfidenceEntry, ThesisRecord

    thesis = db.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).first()
    if thesis is None:
        raise ValueError(f"thesis {thesis_id} not found")

    clamped = max(0.0, min(1.0, float(score)))
    entry = ThesisConfidenceEntry(
        thesis_id=thesis_id,
        score=clamped,
        as_of=as_of,
        note=note,
        created_at=_utc_now(),
    )
    db.add(entry)
    db.flush()
    audit_write(
        db,
        "thesis_ledger.confidence",
        f"confidence={clamped:.3f} as_of={as_of}",
        related_symbol=thesis.symbol,
    )
    db.commit()
    return _entry_to_dict(entry)


def attach_review_case(db, thesis_id: int, *, review_payload: dict, as_of: str) -> dict:
    """Populate ThesisRecord.review_case_ref_json with the given review payload dict.

    Raises ValueError if thesis_id does not exist.
    Always calls audit_write on success.
    The bidirectional link is: ReviewCase.thesis_id -> ThesisRecord.id (bare int),
    and ThesisRecord.review_case_ref_json stores the full review payload dict.
    """
    from backend.data.database import ThesisRecord

    row = db.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).first()
    if row is None:
        raise ValueError(f"thesis {thesis_id} not found")

    row.review_case_ref_json = json.dumps(review_payload, ensure_ascii=False, default=str)
    row.updated_at = _utc_now()
    db.flush()

    audit_write(
        db,
        "thesis_ledger.review_case",
        f"review_case attached as_of={as_of}",
        related_symbol=row.symbol,
    )
    db.commit()
    return _row_to_dict(row)
