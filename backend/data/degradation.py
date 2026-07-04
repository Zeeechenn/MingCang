"""Durable degradation event recording helpers."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from backend.data.models.degradation import DegradationEvent
from backend.data.orm import SessionLocal, _utcnow

logger = logging.getLogger(__name__)


def emit_degradation(
    component: str,
    category: str,
    provider: str,
    error: str,
    context: dict | None = None,
    db=None,
) -> None:
    """Persist one degradation event; never raise to the caller."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        event = DegradationEvent(
            component=component,
            category=category,
            provider=provider,
            error=str(error)[:500],
            context_json=json.dumps(context, ensure_ascii=False, default=str) if context is not None else None,
        )
        session.add(event)
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        logger.warning("failed to record degradation event: %s", exc)
    finally:
        if own_session:
            try:
                session.close()
            except Exception:
                logger.warning("failed to close degradation DB session")


def recent_degradations(hours: int = 24, db=None) -> list[dict]:
    """Return recent degradation events as plain dictionaries."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        since = _utcnow() - timedelta(hours=hours)
        rows = (
            session.query(DegradationEvent)
            .filter(DegradationEvent.ts >= since)
            .order_by(DegradationEvent.ts.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "ts": row.ts.isoformat() if row.ts else None,
                "component": row.component,
                "category": row.category,
                "provider": row.provider,
                "error": row.error,
                "context_json": row.context_json,
            }
            for row in rows
        ]
    finally:
        if own_session:
            session.close()
