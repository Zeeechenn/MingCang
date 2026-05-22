from __future__ import annotations

from datetime import datetime


def test_chat_context_uses_summary_plus_tail(test_db):
    from backend.api.routes.ai import _chat_context_for_session
    from backend.data.database import ChatMessage, ChatSession

    session = ChatSession(
        id="sess1",
        title="预算测试",
        mode="general",
        summary="用户偏好稳健仓位；不碰高负债公司。",
        summary_until_id=2,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    test_db.add(session)
    test_db.add_all([
        ChatMessage(id=1, session_id="sess1", role="user", content="旧消息1", created_at=datetime.utcnow()),
        ChatMessage(id=2, session_id="sess1", role="assistant", content="旧回答", created_at=datetime.utcnow()),
        ChatMessage(id=3, session_id="sess1", role="user", content="最近关注 300308", created_at=datetime.utcnow()),
        ChatMessage(id=4, session_id="sess1", role="assistant", content="收到", created_at=datetime.utcnow()),
    ])
    test_db.commit()

    context = _chat_context_for_session(test_db, "sess1", tail_limit=6)

    assert "窗口摘要：用户偏好稳健仓位；不碰高负债公司。" in context
    assert "user: 最近关注 300308" in context
    assert "旧消息1" not in context
