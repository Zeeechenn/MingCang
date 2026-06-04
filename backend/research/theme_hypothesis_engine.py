"""
M36 Theme Hypothesis Engine — pure storage layer.

Exposes nine injectable-Session functions:
  create_theme, get_theme, list_themes,
  create_hypothesis, get_hypothesis, list_hypotheses,
  update_hypothesis_status, set_beneficiary_tiers, attach_forward_evidence

No LLM calls. No writes to Signal / DecisionRun / M29 / quant-weight / ai_memory tables.
Beneficiary-tier labels are advisory display metadata only and must not be passed to
aggregate(), aggregate_v2(), run_pipeline(), or apply_research_constraints().
Routes deferred to M40.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.memory.audit_log import audit_write

THEME_STATUSES = {"active", "watch", "archived"}
HYPOTHESIS_STATUSES = {"proposed", "supported", "contradicted", "invalidated"}

_HYPOTHESIS_TRANSITIONS: set[tuple[str, str]] = {
    ("proposed", "supported"),
    ("proposed", "contradicted"),
    ("proposed", "invalidated"),
    ("supported", "contradicted"),
    ("supported", "invalidated"),
    ("contradicted", "supported"),
    ("contradicted", "invalidated"),
}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _theme_to_dict(row) -> dict:
    return {
        "id": row.id,
        "theme_name": row.theme_name,
        "description": row.description,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _hyp_to_dict(row) -> dict:
    return {
        "id": row.id,
        "theme_id": row.theme_id,
        "statement": row.statement,
        "status": row.status,
        "beneficiary_tiers": json.loads(row.beneficiary_tiers_json) if row.beneficiary_tiers_json else [],
        "evidence_gaps": json.loads(row.evidence_gaps_json) if row.evidence_gaps_json else [],
        "invalidation_conditions": json.loads(row.invalidation_conditions_json) if row.invalidation_conditions_json else [],
        "ai_supply_chain": json.loads(row.ai_supply_chain_json) if row.ai_supply_chain_json else None,
        "forward_evidence_ref": json.loads(row.forward_evidence_ref_json) if row.forward_evidence_ref_json else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


# --- theme functions ---

def create_theme(db, *, theme_name: str, description: str | None = None, status: str = "active") -> dict:
    """Create a new theme record, or return the existing one if theme_name already exists (idempotent)."""
    if status not in THEME_STATUSES:
        raise ValueError(f"invalid status: {status!r}; must be one of {THEME_STATUSES}")
    from backend.data.database import ThemeRecord
    existing = db.query(ThemeRecord).filter(ThemeRecord.theme_name == theme_name).first()
    if existing is not None:
        return _theme_to_dict(existing)
    now = _utc_now()
    row = ThemeRecord(
        theme_name=theme_name,
        description=description,
        status=status,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(db, "theme_engine.create_theme", f"theme created: {theme_name!r}")
    db.commit()
    return _theme_to_dict(row)


def get_theme(db, theme_id: int) -> dict | None:
    """Return a theme dict by id, or None if not found."""
    from backend.data.database import ThemeRecord
    row = db.query(ThemeRecord).filter(ThemeRecord.id == theme_id).first()
    return _theme_to_dict(row) if row is not None else None


def list_themes(db, *, status: str | None = None, limit: int = 50) -> list[dict]:
    """List themes, optionally filtered by status, ordered by updated_at desc."""
    from backend.data.database import ThemeRecord
    q = db.query(ThemeRecord)
    if status is not None:
        q = q.filter(ThemeRecord.status == status)
    return [_theme_to_dict(r) for r in q.order_by(ThemeRecord.updated_at.desc()).limit(limit).all()]


# --- hypothesis functions ---

def create_hypothesis(
    db,
    *,
    theme_id: int,
    statement: str,
    beneficiary_tiers: list | None = None,
    evidence_gaps: list | None = None,
    invalidation_conditions: list | None = None,
    ai_supply_chain: dict | None = None,
    status: str = "proposed",
) -> dict:
    """Create a new hypothesis under a theme, or return existing one if (theme_id, statement) already exists (idempotent)."""
    if status not in HYPOTHESIS_STATUSES:
        raise ValueError(f"invalid status: {status!r}; must be one of {HYPOTHESIS_STATUSES}")
    from backend.data.database import ThemeHypothesis, ThemeRecord
    theme = db.query(ThemeRecord).filter(ThemeRecord.id == theme_id).first()
    if theme is None:
        raise ValueError(f"theme {theme_id} not found")
    existing = db.query(ThemeHypothesis).filter(
        ThemeHypothesis.theme_id == theme_id,
        ThemeHypothesis.statement == statement,
    ).first()
    if existing is not None:
        return _hyp_to_dict(existing)
    normalized_ai_supply_chain = None
    if ai_supply_chain is not None:
        from backend.research.ai_supply_chain_template import (
            hypothesis_fields_from_payload,
            normalize_ai_supply_chain_payload,
        )
        normalized_ai_supply_chain = normalize_ai_supply_chain_payload(ai_supply_chain)
        mapped = hypothesis_fields_from_payload(normalized_ai_supply_chain)
        beneficiary_tiers = beneficiary_tiers if beneficiary_tiers is not None else mapped["beneficiary_tiers"]
        evidence_gaps = evidence_gaps if evidence_gaps is not None else mapped["evidence_gaps"]
        invalidation_conditions = (
            invalidation_conditions
            if invalidation_conditions is not None
            else mapped["invalidation_conditions"]
        )
    now = _utc_now()
    row = ThemeHypothesis(
        theme_id=theme_id,
        statement=statement,
        status=status,
        beneficiary_tiers_json=json.dumps(beneficiary_tiers or [], ensure_ascii=False),
        evidence_gaps_json=json.dumps(evidence_gaps or [], ensure_ascii=False),
        invalidation_conditions_json=json.dumps(invalidation_conditions or [], ensure_ascii=False),
        ai_supply_chain_json=json.dumps(normalized_ai_supply_chain, ensure_ascii=False) if normalized_ai_supply_chain else None,
        forward_evidence_ref_json=None,  # populated by M39 when M29 promotion gate passes
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(db, "theme_engine.create_hypothesis", f"hypothesis created for theme_id={theme_id}: {statement[:60]!r}")
    db.commit()
    return _hyp_to_dict(row)


def get_hypothesis(db, hypothesis_id: int) -> dict | None:
    """Return a hypothesis dict by id, or None if not found."""
    from backend.data.database import ThemeHypothesis
    row = db.query(ThemeHypothesis).filter(ThemeHypothesis.id == hypothesis_id).first()
    return _hyp_to_dict(row) if row is not None else None


def list_hypotheses(db, *, theme_id: int | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    """List hypotheses, optionally filtered by theme_id and/or status, ordered by updated_at desc."""
    from backend.data.database import ThemeHypothesis
    q = db.query(ThemeHypothesis)
    if theme_id is not None:
        q = q.filter(ThemeHypothesis.theme_id == theme_id)
    if status is not None:
        q = q.filter(ThemeHypothesis.status == status)
    return [_hyp_to_dict(r) for r in q.order_by(ThemeHypothesis.updated_at.desc()).limit(limit).all()]


def update_hypothesis_status(db, hypothesis_id: int, new_status: str, *, note: str | None = None) -> dict:
    """Transition hypothesis status according to the allowed state machine.

    Allowed transitions:
      proposed -> supported | contradicted | invalidated
      supported -> contradicted | invalidated
      contradicted -> supported | invalidated

    Raises ValueError for unknown statuses, unknown hypothesis id, or disallowed transitions.
    """
    if new_status not in HYPOTHESIS_STATUSES:
        raise ValueError(f"invalid status: {new_status!r}; must be one of {HYPOTHESIS_STATUSES}")
    from backend.data.database import ThemeHypothesis
    row = db.query(ThemeHypothesis).filter(ThemeHypothesis.id == hypothesis_id).first()
    if row is None:
        raise ValueError(f"hypothesis {hypothesis_id} not found")
    if (row.status, new_status) not in _HYPOTHESIS_TRANSITIONS:
        raise ValueError(f"transition {row.status!r} -> {new_status!r} is not allowed")
    old_status = row.status
    row.status = new_status
    row.updated_at = _utc_now()
    db.flush()
    detail = f"{old_status} -> {new_status}"
    if note:
        detail += f"; {note}"
    audit_write(db, "theme_engine.hypothesis_status", detail)
    db.commit()
    return _hyp_to_dict(row)


def set_beneficiary_tiers(db, hypothesis_id: int, *, tiers: list[dict]) -> dict:
    """Replace beneficiary tiers on a hypothesis (advisory display only).

    tiers: list of {symbol: str, tier: int (1|2|3), rationale: str}.
    Raises ValueError if hypothesis not found or any tier value is outside 1-3.

    NOTE: These tiers are advisory display metadata only and must NOT be passed to
    aggregate(), aggregate_v2(), run_pipeline(), or apply_research_constraints().
    """
    from backend.data.database import ThemeHypothesis
    row = db.query(ThemeHypothesis).filter(ThemeHypothesis.id == hypothesis_id).first()
    if row is None:
        raise ValueError(f"hypothesis {hypothesis_id} not found")
    for t in tiers:
        if t.get("tier") not in (1, 2, 3):
            raise ValueError(f"tier must be 1, 2, or 3; got {t.get('tier')!r}")
    row.beneficiary_tiers_json = json.dumps(tiers, ensure_ascii=False)
    row.updated_at = _utc_now()
    db.flush()
    symbols = [t.get("symbol", "?") for t in tiers]
    audit_write(db, "theme_engine.set_tiers", f"beneficiary tiers set for hypothesis_id={hypothesis_id}: {symbols}")
    db.commit()
    return _hyp_to_dict(row)


def attach_forward_evidence(
    db,
    hypothesis_id: int,
    *,
    evidence_payload: dict,
    as_of: str,
) -> dict:
    """Populate ThemeHypothesis.forward_evidence_ref_json with the given evidence payload dict.

    Mirrors attach_review_case from thesis_ledger.py.  The forward_evidence_ref_json
    column was reserved as a nullable stub in M36 and is now populated by M39.

    The evidence_payload dict passed by M39 callers should contain at minimum:
      {forward_thesis_id: int, universe_snapshot_id: int, attached_at: ISO-string,
       schema_version: 'm39.v1'}

    No related_symbol kwarg is passed to audit_write because ThemeHypothesis spans
    multiple symbols.

    Raises ValueError if hypothesis_id does not exist.
    Always calls audit_write on success.
    """
    from backend.data.database import ThemeHypothesis

    row = db.query(ThemeHypothesis).filter(ThemeHypothesis.id == hypothesis_id).first()
    if row is None:
        raise ValueError(f"hypothesis {hypothesis_id} not found")

    row.forward_evidence_ref_json = json.dumps(evidence_payload, ensure_ascii=False, default=str)
    row.updated_at = _utc_now()
    db.flush()
    audit_write(
        db,
        "theme_engine.forward_evidence",
        f"forward_evidence attached as_of={as_of}",
    )
    db.commit()
    return _hyp_to_dict(row)
