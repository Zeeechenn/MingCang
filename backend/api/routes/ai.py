"""Project-scoped AI chat and confirmed action routes."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.agent.action_parser import (
    detect_action,
    name_after_symbol,
    summary_after_marker,
    symbol_from_text,
)
from backend.agent.chat_responder import context_answer, long_term_answer
from backend.agent.http_guard import agent_write_guard, require_http_agent_write_key
from backend.api.schemas import AIChatRequest, AIChatResponse
from backend.data.database import ChatMessage, ChatSession, PendingAIAction, get_db
from backend.memory.chat_store import (
    chat_context_for_session,
    chat_session_to_dict,
    ensure_session,
    message_to_dict,
    save_message,
)

router = APIRouter()



def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {_json(data)}\n\n"


def _text_chunks(text: str, size: int = 24):
    for i in range(0, len(text), size):
        yield text[i:i + size]

def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _parse(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _symbol_from_text(text: str) -> str | None:
    return symbol_from_text(text)


def _name_after_symbol(text: str, symbol: str) -> str | None:
    return name_after_symbol(text, symbol)


def _summary_after_marker(message: str, markers: tuple[str, ...], *, fallback: str) -> str:
    return summary_after_marker(message, markers, fallback=fallback)


def _pending(action: str, payload: dict, user_message: str, db: Session) -> dict:
    from backend.agent.action_registry import action_metadata

    action_id = uuid4().hex
    metadata = action_metadata(action)
    row = PendingAIAction(
        action_id=action_id,
        action=action,
        payload_json=_json(payload),
        status="pending",
        user_message=user_message,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    return {
        "id": action_id,
        "action": action,
        "payload": payload,
        "status": "pending",
        **metadata,
    }


def _detect_action(message: str, db: Session) -> tuple[str, dict] | None:
    return detect_action(message, db)


def _chat_context_for_session(db: Session, session_id: str, tail_limit: int = 12) -> str:
    return chat_context_for_session(db, session_id, tail_limit)


def _context_answer(message: str, db: Session, session_id: str | None = None) -> AIChatResponse:
    return context_answer(
        message,
        db,
        session_id,
        chat_context_for_session=_chat_context_for_session,
    )


def _chat_session_to_dict(row: ChatSession, db: Session) -> dict:
    return chat_session_to_dict(row, db)


def _message_to_dict(row: ChatMessage) -> dict:
    return message_to_dict(row)


def _ensure_session(db: Session, session_id: str | None, mode: str, title: str | None = None) -> ChatSession:
    return ensure_session(db, session_id, mode, title=title)


def _save_message(
    db: Session,
    session: ChatSession,
    role: str,
    content: str,
    payload: dict | None = None,
) -> None:
    save_message(db, session, role, content, payload)


def _long_term_answer(message: str, db: Session) -> AIChatResponse:
    return long_term_answer(message, db)


@router.get("/ai/sessions")
def list_chat_sessions(include_archived: bool = False, db: Session = Depends(get_db)):
    query = db.query(ChatSession)
    if not include_archived:
        query = query.filter(ChatSession.archived_at.is_(None))
    rows = query.order_by(ChatSession.updated_at.desc()).all()
    return [_chat_session_to_dict(row, db) for row in rows]


@router.post(
    "/ai/sessions",
    dependencies=[Depends(agent_write_guard("ai.sessions.create"))],
)
def create_chat_session(payload: dict | None = None, db: Session = Depends(get_db)):
    payload = payload or {}
    row = _ensure_session(
        db,
        None,
        payload.get("mode") or "general",
        title=payload.get("title") or "新对话",
    )
    return _chat_session_to_dict(row, db)


@router.get("/ai/sessions/{session_id}/messages")
def list_chat_messages(session_id: str, db: Session = Depends(get_db)):
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if row is None:
        raise HTTPException(404, "chat session not found")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    return [_message_to_dict(msg) for msg in messages]


@router.post(
    "/ai/sessions/{session_id}/archive",
    dependencies=[Depends(agent_write_guard("ai.sessions.archive"))],
)
def archive_chat_session(session_id: str, db: Session = Depends(get_db)):
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if row is None:
        raise HTTPException(404, "chat session not found")
    row.archived_at = datetime.now(UTC).replace(tzinfo=None)
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return {"status": "archived", "id": session_id}


@router.post(
    "/ai/chat",
    response_model=AIChatResponse,
    dependencies=[Depends(agent_write_guard("ai.chat"))],
)
def chat(request: AIChatRequest, db: Session = Depends(get_db)):
    """Chat with the project-scoped AI assistant."""
    session = _ensure_session(db, request.session_id, request.mode, title=request.message[:24])
    _save_message(db, session, "user", request.message, {"mode": request.mode})

    if request.mode == "long_term_team":
        response = _long_term_answer(request.message, db)
    else:
        action = _detect_action(request.message, db)
        if action:
            action_name, payload = action
            pending = _pending(action_name, payload, request.message, db)
            response = AIChatResponse(
                answer="我已经识别出一个项目操作，请确认后执行。",
                used_resources=["ai_action_parser"],
                pending_action=pending,
            )
        else:
            response = _context_answer(request.message, db, session.id)

    _save_message(
        db,
        session,
        "assistant",
        response.answer,
        {
            "session_id": session.id,
            "used_resources": response.used_resources,
            "citations": response.citations,
            "pending_action": response.pending_action,
        },
    )
    return response


@router.post(
    "/ai/chat/stream",
    dependencies=[Depends(agent_write_guard("ai.chat.stream"))],
)
def chat_stream(request: AIChatRequest, db: Session = Depends(get_db)):
    """SSE streaming chat with real stage events.

    Event sequence:
      prepare  — immediately on receipt (< 50 ms); signals the server is alive
      running  — session created, user message saved, computation starting
      evidence — context / action detection complete, entering LLM or data path
      meta     — full resource / citation / pending_action metadata (before tokens)
      token    — incremental answer chunks (24-char blocks)
      done     — final payload mirrors /ai/chat response JSON
      error    — if an exception occurs; carries {"message": "..."}
    """
    def generate():
        # Stage 1 – immediate acknowledgement before any I/O
        yield _sse("prepare", {"mode": request.mode})

        try:
            session = _ensure_session(
                db, request.session_id, request.mode,
                title=request.message[:24],
            )
            _save_message(db, session, "user", request.message, {"mode": request.mode})

            # Stage 2 – session ready, processing starts
            yield _sse("running", {"session_id": session.id})

            if request.mode == "long_term_team":
                # Long-term team is slow; signal that this path is running
                yield _sse("running", {"stage": "long_term_team", "session_id": session.id})
                response = _long_term_answer(request.message, db)
            else:
                action = _detect_action(request.message, db)
                if action:
                    action_name, payload = action
                    pending = _pending(action_name, payload, request.message, db)
                    response = AIChatResponse(
                        answer="我已经识别出一个项目操作，请确认后执行。",
                        used_resources=["ai_action_parser"],
                        pending_action=pending,
                    )
                else:
                    # Stage 3 – context building (memory + copilot lookup)
                    yield _sse("evidence", {"stage": "context"})
                    response = _context_answer(request.message, db, session.id)

            _save_message(
                db,
                session,
                "assistant",
                response.answer,
                {
                    "session_id": session.id,
                    "used_resources": response.used_resources,
                    "citations": response.citations,
                    "pending_action": response.pending_action,
                },
            )

            payload = response.model_dump()
            yield _sse("meta", {
                "used_resources": response.used_resources,
                "citations": response.citations,
                "pending_action": response.pending_action,
            })
            for chunk in _text_chunks(response.answer):
                yield _sse("token", {"text": chunk})
            yield _sse("done", payload)

        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/ai/actions/{action_id}")
def get_action(action_id: str, db: Session = Depends(get_db)):
    row = db.query(PendingAIAction).filter(PendingAIAction.action_id == action_id).first()
    if row is None:
        raise HTTPException(404, "action not found")
    return {
        "id": row.action_id,
        "action": row.action,
        "payload": _parse(row.payload_json, {}),
        "status": row.status,
        "result": _parse(row.result_json, None),
    }


@router.post("/ai/actions/{action_id}/confirm")
def confirm_action(
    action_id: str,
    mingcang_api_key: str | None = Header(default=None, alias="x-mingcang-agent-api-key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    row = db.query(PendingAIAction).filter(PendingAIAction.action_id == action_id).first()
    if row is None:
        raise HTTPException(404, "action not found")
    if row.status != "pending":
        return get_action(action_id, db)
    require_http_agent_write_key(row.action, api_key=mingcang_api_key, authorization=authorization)

    payload = _parse(row.payload_json, {})
    result = _execute_action(row.action, payload, db)
    row.status = "executed"
    row.result_json = _json(result)
    row.executed_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    return {"status": "executed", "result": result}


def _execute_action(action: str, payload: dict, db: Session) -> dict:
    from backend.agent.action_registry import execute_registered_action

    return execute_registered_action(action, payload, db)
