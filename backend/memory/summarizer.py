"""M9.3 chat window summarizer.

Compress old messages of a chat session into a single `chat_sessions.summary`
once the message count crosses a threshold. The compressed messages stay in
`chat_messages` for audit, but downstream code that builds chat context should
prefer the summary + tail rather than re-injecting the full history.
"""
from __future__ import annotations

from sqlalchemy import text

SUMMARY_TOOL = {
    "name": "compress_chat",
    "description": "把多轮聊天压缩为一段简明的摘要，保留对后续决策有意义的事实、规则、用户偏好。",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "≤200 字的中文摘要，列出用户偏好、已定规则、关键事实；省略寒暄和一次性查询。",
            },
        },
        "required": ["summary"],
    },
}


DEFAULT_THRESHOLD = 50      # 触发摘要的最小消息数
KEEP_RECENT = 10            # 摘要后保留尾部多少条不压缩


def _count_messages(db, session_id: str) -> int:
    return db.execute(text(
        "SELECT count(*) FROM chat_messages WHERE session_id = :sid"
    ), {"sid": session_id}).scalar() or 0


def _fetch_window_for_summary(db, session_id: str, *, until_id: int | None, head_keep: int):
    """Return (rows, last_id) for messages to compress.

    Compresses messages with id > until_id (or all) up to but excluding the
    last `head_keep` rows (kept verbatim).
    """
    if until_id is not None:
        query = """
            SELECT id, role, content FROM chat_messages
            WHERE session_id = :sid AND id > :until
            ORDER BY id ASC
        """
        params: dict = {"sid": session_id, "until": until_id}
    else:
        query = """
            SELECT id, role, content FROM chat_messages
            WHERE session_id = :sid
            ORDER BY id ASC
        """
        params = {"sid": session_id}
    rows = db.execute(text(query), params).all()
    if len(rows) <= head_keep:
        return [], None
    to_compress = rows[:-head_keep]
    return to_compress, to_compress[-1].id


def _build_prompt(prior_summary: str | None, rows) -> str:
    parts: list[str] = []
    if prior_summary:
        parts.append("【已有摘要】\n" + prior_summary + "\n")
    parts.append("【待压缩对话】")
    for r in rows:
        parts.append(f"- {r.role}: {r.content}")
    return "\n".join(parts)


def summarize_if_needed(
    db,
    session_id: str,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    keep_recent: int = KEEP_RECENT,
    provider=None,
) -> bool:
    """If session crosses `threshold`, compress old messages into `summary`.

    Returns True when a summary was (re)generated. Provider is injected for
    tests; production uses `backend.llm.get_provider()`.
    """
    from backend.memory.audit_log import audit_write

    n = _count_messages(db, session_id)
    if n < threshold:
        return False

    prior = db.execute(text(
        "SELECT summary, summary_until_id FROM chat_sessions WHERE id = :sid"
    ), {"sid": session_id}).first()
    prior_summary = prior.summary if prior else None
    prior_until = prior.summary_until_id if prior else None

    rows, last_id = _fetch_window_for_summary(
        db, session_id, until_id=prior_until, head_keep=keep_recent,
    )
    if not rows or last_id is None:
        return False

    if provider is None:
        from backend.llm import get_provider
        provider = get_provider()

    prompt = _build_prompt(prior_summary, rows)
    data = provider.complete_structured(
        prompt=prompt,
        tool=SUMMARY_TOOL,
        max_tokens=600,
        model_tier="fast",
    ) or {}
    try:
        import json as _json

        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("chat", prompt, _json.dumps(data))
    except Exception:
        pass
    new_summary = (data.get("summary") or "").strip()
    if not new_summary:
        return False

    db.execute(text(
        "UPDATE chat_sessions SET summary = :s, summary_until_id = :uid "
        "WHERE id = :sid"
    ), {"s": new_summary, "uid": last_id, "sid": session_id})
    db.commit()
    audit_write(
        db,
        "chat.summary",
        f"session={session_id} compressed_count={len(rows)} until_id={last_id}",
    )
    return True
