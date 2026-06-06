"""Chat session persistence helpers for AI routes."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.data.database import ChatMessage, ChatSession

logger = logging.getLogger(__name__)


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _parse(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def chat_context_for_session(db: Session, session_id: str, tail_limit: int = 12) -> str:
    """Build chat context from persisted summary plus recent uncompressed tail."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        return ""

    parts: list[str] = []
    if session.summary:
        parts.append(f"窗口摘要：{session.summary}")

    query = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
    if session.summary_until_id:
        query = query.filter(ChatMessage.id > session.summary_until_id)
    tail = (
        query
        .order_by(ChatMessage.id.desc())
        .limit(tail_limit)
        .all()
    )
    for row in reversed(tail):
        parts.append(f"{row.role}: {row.content}")
    return "\n".join(parts)


def chat_session_to_dict(row: ChatSession, db: Session) -> dict:
    last = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == row.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .first()
    )
    return {
        "id": row.id,
        "title": row.title or "新对话",
        "mode": row.mode or "general",
        "archived": row.archived_at is not None,
        "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else None,
        "last_message": last.content[:80] if last else "",
    }


def message_to_dict(row: ChatMessage) -> dict:
    payload = _parse(row.payload_json, {})
    data = {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }
    data.update(payload)
    return data


def ensure_session(
    db: Session,
    session_id: str | None,
    mode: str,
    title: str | None = None,
) -> ChatSession:
    if session_id:
        row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if row:
            return row
    row = ChatSession(
        id=session_id or uuid4().hex,
        title=title or "新对话",
        mode=mode,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    return row


def save_message(
    db: Session,
    session: ChatSession,
    role: str,
    content: str,
    payload: dict | None = None,
) -> None:
    db.add(ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
        payload_json=_json(payload or {}),
        created_at=datetime.now(UTC).replace(tzinfo=None),
    ))
    session.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    try:
        from backend.memory.summarizer import summarize_if_needed
        summarize_if_needed(db, session.id)
    except Exception as exc:
        logger.warning("summarize_if_needed failed for session %s: %s", session.id, exc)
        try:
            db.rollback()
        except Exception:
            pass
