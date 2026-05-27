"""Project-scoped AI chat and confirmed action routes."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard, require_http_agent_write_key
from backend.api.schemas import AIChatRequest, AIChatResponse
from backend.data.database import ChatMessage, ChatSession, PendingAIAction, Position, Stock, get_db

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


def _fmt_score(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{n:+.1f}"


def _fmt_pct(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{n * 100:.1f}%"


def _symbol_from_text(text: str) -> str | None:
    match = re.search(r"\b(\d{6})\b", text)
    return match.group(1) if match else None


def _name_after_symbol(text: str, symbol: str) -> str | None:
    tail = text.split(symbol, 1)[-1].strip()
    if not tail:
        return None
    tail = re.split(r"[，,。；;\s]+", tail)[0].strip()
    return tail or None


def _summary_after_marker(message: str, markers: tuple[str, ...], *, fallback: str) -> str:
    for marker in markers:
        if marker in message:
            tail = message.split(marker, 1)[-1].strip(" ：:，,。；;")
            if tail:
                return tail
    return fallback


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
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
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
    symbol = _symbol_from_text(message)
    lower = message.lower()

    threshold_match = re.search(r"(?:阈值|threshold)\D*(\d+(?:\.\d+)?)", message, flags=re.I)
    if threshold_match and any(word in message for word in ("设置", "改", "调整", "update", "set")):
        return "config.update", {
            "new_framework_entry_threshold": float(threshold_match.group(1)),
        }

    bool_map = {
        "多 Agent": "multi_agent_enabled",
        "多agent": "multi_agent_enabled",
        "长期分析师团": "long_term_team_enabled",
        "风险经理": "risk_manager_enabled",
        "移动止损": "trailing_stop_enabled",
        "大盘择时": "regime_filter_enabled",
        "ADX": "adx_filter_enabled",
    }
    for label, key in bool_map.items():
        if label in message and any(word in message for word in ("开启", "打开", "启用", "关闭", "禁用")):
            enabled = any(word in message for word in ("开启", "打开", "启用"))
            return "config.update", {key: enabled}

    if "每日复盘" in message and any(word in message for word in ("触发", "生成", "运行", "跑")):
        return "review.daily.ensure", {}
    if "长期复盘" in message and any(word in message for word in ("触发", "生成", "运行", "跑")):
        return "review.long_term.ensure", {}

    # M9.4：用户说"记住 X" / "把 X 记下来" → memory.write 候选，需用户确认
    mem_match = re.match(
        r"^\s*(?:请\s*)?(?:把|帮我)?\s*(?:记住|记下来|存进记忆|存到记忆|保存为记忆)\s*[:：，,]?\s*(.+)$",
        message,
    )
    if mem_match:
        body = mem_match.group(1).strip()
        if body:
            # category 启发：包含"规则"/"偏好"/"风险" 优先归类
            if any(w in body for w in ("规则", "rule")):
                category = "rule"
            elif any(w in body for w in ("偏好", "preference")):
                category = "preference"
            elif any(w in body for w in ("风险", "risk", "预警")):
                category = "risk"
            else:
                category = "preference"
            # key 用截断 body 自动生成；确保 UNIQUE
            from hashlib import sha1
            key = f"chat:{category}:{sha1(body.encode('utf-8')).hexdigest()[:10]}"
            return "memory.write", {
                "key": key,
                "value": body,
                "category": category,
                "scope": "global",
                "symbol": symbol,
            }

    if not symbol:
        return None

    if any(word in message for word in ("调研过", "研究过", "做过调研", "做了调研", "调研了")):
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "research_pointer",
            "summary": message.strip(),
            "status": "watching",
            "importance": 4,
            "confidence": 0.75,
        }

    thesis_markers = ("投资逻辑是", "逻辑是", "结论是", "thesis is", "thesis 是")
    if any(marker in lower for marker in ("thesis is",)) or any(marker in message for marker in thesis_markers):
        summary = _summary_after_marker(message, thesis_markers, fallback=message.strip())
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "thesis",
            "summary": f"{symbol} thesis：{summary}",
            "status": "watching",
            "importance": 4,
            "confidence": 0.75,
        }

    risk_markers = ("风险是", "风险点是", "担心点是", "预警是")
    if any(marker in message for marker in risk_markers) or any(word in message for word in ("风险", "预警", "担心")):
        summary = _summary_after_marker(message, risk_markers, fallback=message.strip())
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "risk",
            "summary": f"{symbol} 风险：{summary}",
            "status": "watching",
            "importance": 4,
            "confidence": 0.75,
        }

    if any(word in message for word in ("催化", "公告", "订单", "事件")) and any(word in message for word in ("有", "出现", "发生", "发布", "披露")):
        summary = _summary_after_marker(message, ("有", "出现", "发生", "发布", "披露"), fallback=message.strip())
        return "stock_memory.write", {
            "symbol": symbol,
            "memory_type": "event",
            "summary": f"{symbol} 事件：{summary}",
            "status": "watching",
            "importance": 3,
            "confidence": 0.7,
        }

    if any(word in message for word in ("删除自选", "移除自选", "取消关注")):
        return "watchlist.remove", {"symbol": symbol}

    if any(word in message for word in ("添加持仓", "新增持仓", "买入了", "已买入", "持仓")):
        qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:股|shares?)", message, flags=re.I)
        cost_match = re.search(r"(?:成本|均价|avg|price)\s*[:：]?\s*(\d+(?:\.\d+)?)", message, flags=re.I)
        # schema 现在要求 quantity/avg_cost > 0；若用户没说清数量或成本，不构造
        # 不完整的 pending（避免弹一张报 0 的待执行卡），让 chat 层自然反问。
        if not qty_match or not cost_match:
            return None
        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        return "position.add", {
            "symbol": symbol,
            "name": stock.name if stock else _name_after_symbol(message, symbol),
            "market": stock.market if stock else "CN",
            "quantity": float(qty_match.group(1)),
            "avg_cost": float(cost_match.group(1)),
        }

    if any(word in message for word in ("添加自选", "加入自选", "关注", "重点跟踪")) or "add watch" in lower:
        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        return "watchlist.add", {
            "symbol": symbol,
            "name": stock.name if stock else (_name_after_symbol(message, symbol) or symbol),
            "market": stock.market if stock else "CN",
        }

    return None


def _chat_context_for_session(db: Session, session_id: str, tail_limit: int = 12) -> str:
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


def _copilot_context_section(db: Session, symbol: str) -> tuple[str | None, bool]:
    try:
        from backend.decision.harness import get_research_state
        state = get_research_state(db, symbol)
    except Exception:
        return None, False
    copilot = state.get("copilot") if isinstance(state, dict) else None
    if not copilot:
        return None, False
    official = copilot.get("official") or {}
    lines = [
        "双轨影子副驾驶：",
        "官方规则：",
        f"- 建议：{official.get('recommendation', '-')}",
        f"- 综合分：{_fmt_score(official.get('composite_score'))}",
        f"- 技术：{_fmt_score(official.get('technical_score') or official.get('breakdown', {}).get('technical'))}",
        f"- 情绪：{_fmt_score(official.get('sentiment_score') or official.get('breakdown', {}).get('sentiment'))}",
        f"- 官方仓位：{_fmt_pct(official.get('position_pct'))}",
        "LLM 副驾驶：",
        f"- 立场：{copilot.get('stance', '-')}",
        f"- 影子仓位：{_fmt_pct(copilot.get('shadow_position_pct'))}",
        f"- 结论：{copilot.get('summary_opinion', '-')}",
    ]
    if copilot.get("risk_conflict"):
        lines.append("- 标记：逆风控影子建议")
    risks = (copilot.get("risks") or [])[:2]
    if risks:
        lines.append("- 风险：" + "、".join(risks))
    questions = (copilot.get("validation_questions") or [])[:2]
    if questions:
        lines.append("- 待验证：" + "、".join(questions))
    return "\n".join(lines), True


def _context_answer(message: str, db: Session, session_id: str | None = None) -> AIChatResponse:
    """Deterministic fallback answer using internal StockSage resources."""
    symbol = _symbol_from_text(message)
    stocks = db.query(Stock).filter(Stock.active).limit(6).all()
    positions = db.query(Position).filter(Position.status == "open").limit(6).all()
    parts = ["我会在 StockSage 项目内回答：已读取自选股、持仓、信号、复盘和研究记忆。"]
    used_resources = ["stocks", "positions", "project_research"]
    if session_id:
        chat_context = _chat_context_for_session(db, session_id)
        if chat_context:
            parts.append("本窗口上下文：\n" + chat_context)
    if symbol:
        try:
            from backend.memory.stock_memory import build_memory_context
            memory_context = build_memory_context(
                db,
                symbol=symbol,
                query=message,
                task_type="chat",
            )
        except Exception:
            memory_context = {"text": ""}
        if memory_context.get("text"):
            parts.append("项目长期记忆：\n" + memory_context["text"])
            used_resources.append("stock_memory")
        copilot_section, has_copilot = _copilot_context_section(db, symbol)
        if has_copilot and copilot_section:
            parts.append(copilot_section)
            used_resources.append("research_copilot")
    if stocks:
        parts.append("当前自选股包括：" + "、".join(f"{s.name or s.symbol}({s.symbol})" for s in stocks))
    if positions:
        parts.append("当前持仓包括：" + "、".join(f"{p.name or p.symbol}({p.symbol})" for p in positions))
    parts.append("需要联网调研时，我会优先走项目内新闻、行情、深度研究和长期研究团队链路。")
    return AIChatResponse(
        answer="\n".join(parts),
        used_resources=used_resources,
    )


def _chat_session_to_dict(row: ChatSession, db: Session) -> dict:
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


def _message_to_dict(row: ChatMessage) -> dict:
    payload = _parse(row.payload_json, {})
    data = {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }
    data.update(payload)
    return data


def _ensure_session(db: Session, session_id: str | None, mode: str, title: str | None = None) -> ChatSession:
    if session_id:
        row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if row:
            return row
    row = ChatSession(
        id=uuid4().hex,
        title=title or "新对话",
        mode=mode,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    return row


def _save_message(
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
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    try:
        from backend.memory.summarizer import summarize_if_needed
        summarize_if_needed(db, session.id)
    except Exception:
        pass  # 摘要失败不应阻塞写入


def _long_term_answer(message: str, db: Session) -> AIChatResponse:
    symbol = _symbol_from_text(message)
    if not symbol:
        return AIChatResponse(
            answer="请告诉我要研究的股票代码，或说明要研究“自选股”还是“持仓”。",
            used_resources=["long_term_team"],
        )
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock is None:
        raise HTTPException(404, f"stock {symbol} not found")
    from backend.agents.long_term.storage import save_label
    from backend.agents.long_term.team import LongTermTeam

    label = LongTermTeam().run(stock.symbol, stock.name, db)
    save_label(label, db)
    findings = "；".join(label.key_findings[:3]) if label.key_findings else "暂无关键发现"
    try:
        from backend.memory.stock_memory import build_memory_context
        memory_context = build_memory_context(
            db,
            symbol=stock.symbol,
            query=message,
            task_type="long_term_team",
        )
    except Exception:
        memory_context = {"text": ""}
    memory_text = f"\n项目长期记忆：\n{memory_context['text']}" if memory_context.get("text") else ""
    quality_note = "可约束官方动作" if label.constraint_eligible else "仅展示，不约束官方动作"
    return AIChatResponse(
        answer=(
            f"{stock.name}({stock.symbol}) 长期研究团队结论：{label.label}，评分 {label.score:.1f}。"
            f"质量：{label.quality}（{quality_note}）。{findings}{memory_text}"
        ),
        citations=[f"long_term:{stock.symbol}:{label.date}"],
        used_resources=["long_term_team"] + (["stock_memory"] if memory_context.get("text") else []),
    )


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
    row.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
    api_key: str | None = Header(default=None, alias="x-stocksage-agent-api-key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    row = db.query(PendingAIAction).filter(PendingAIAction.action_id == action_id).first()
    if row is None:
        raise HTTPException(404, "action not found")
    if row.status != "pending":
        return get_action(action_id, db)
    require_http_agent_write_key(row.action, api_key=api_key, authorization=authorization)

    payload = _parse(row.payload_json, {})
    result = _execute_action(row.action, payload, db)
    row.status = "executed"
    row.result_json = _json(result)
    row.executed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"status": "executed", "result": result}


def _execute_action(action: str, payload: dict, db: Session) -> dict:
    from backend.agent.action_registry import execute_registered_action

    return execute_registered_action(action, payload, db)
