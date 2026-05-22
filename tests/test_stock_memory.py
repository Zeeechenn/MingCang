"""M12 structured stock memory: cross-entry recall and governance."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text


def test_stock_memory_filters_archived_expired_and_symbol(test_db):
    from backend.memory.stock_memory import create_stock_memory, list_stock_memories

    keep = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="300308 订单兑现节奏是核心风险",
        source_type="test",
        importance=4,
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="event",
        summary="这条事件已经归档",
        source_type="test",
        status="archived",
    )
    expired = create_stock_memory(
        test_db,
        symbol="600519",
        memory_type="risk",
        summary="过期风险",
        source_type="test",
        ttl_days=1,
    )
    test_db.execute(
        text("UPDATE stock_memory_items SET updated_at = :old WHERE id = :id"),
        {"old": (datetime.utcnow() - timedelta(days=3)).isoformat(timespec="seconds"),
         "id": expired["id"]},
    )
    test_db.commit()

    rows = list_stock_memories(test_db, symbol="300308", limit=20)

    assert [r["id"] for r in rows] == [keep["id"]]
    assert rows[0]["summary"] == "300308 订单兑现节奏是核心风险"


def test_build_memory_context_prioritizes_user_rules_stock_items_and_research(test_db):
    from backend.memory.ai_memory import remember
    from backend.memory.research_memory import remember_deep_research
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    remember(test_db, "pref:risk", "用户偏好：不追高，仓位先轻后重", category="preference")
    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="算力链重点观察光模块订单兑现",
        symbols=["300308"],
        report_path="/tmp/ai.md",
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="300308 需要跟踪海外客户资本开支变化",
        source_type="test",
        importance=5,
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="上次判断：高分但等待技术确认",
        source_type="test",
        importance=3,
    )

    ctx = build_memory_context(test_db, symbol="300308", query="算力 订单", limit=8)
    text_value = ctx["text"]

    assert "用户偏好：不追高" in text_value
    assert "300308 需要跟踪海外客户资本开支变化" in text_value
    assert "上次判断：高分但等待技术确认" in text_value
    assert "算力链重点观察光模块订单兑现" in text_value
    assert text_value.index("用户偏好") < text_value.index("300308 需要跟踪")
    assert ctx["used_stock_memory_ids"]


def test_build_memory_context_audits_and_marks_used(test_db):
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    row = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="300308 长期 thesis 是高速光模块升级",
        source_type="test",
    )

    ctx = build_memory_context(test_db, symbol="300308", limit=5)

    used = test_db.execute(
        text("SELECT last_used_at FROM stock_memory_items WHERE id = :id"),
        {"id": row["id"]},
    ).scalar()
    audits = test_db.execute(
        text("SELECT count(*) FROM audit_log_fts WHERE event_type='stock_memory.recall'")
    ).scalar()
    assert row["id"] in ctx["used_stock_memory_ids"]
    assert used is not None
    assert audits == 1


def test_stock_memory_api_context_list_archive_and_patch(test_db):
    from backend.api.routes.memory import (
        StockMemoryPatchPayload,
        stock_memory_archive,
        stock_memory_context,
        stock_memory_items,
        stock_memory_patch,
    )
    from backend.memory.stock_memory import create_stock_memory

    row = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="供应链风险需要复核",
        source_type="test",
        importance=2,
    )

    listed = stock_memory_items(symbol="300308", type=None, status=None, q="供应链", limit=10, db=test_db)
    assert listed["count"] == 1
    assert listed["rows"][0]["id"] == row["id"]

    patched = stock_memory_patch(row["id"], StockMemoryPatchPayload(importance=5, status="watching"), db=test_db)
    assert patched["patched"] is True
    ctx = stock_memory_context("300308", task_type="research", q=None, limit=5, db=test_db)
    assert "供应链风险需要复核" in ctx["text"]

    archived = stock_memory_archive(row["id"], db=test_db)
    assert archived["archived"] is True
    after = stock_memory_items(symbol="300308", type=None, status=None, q=None, limit=10, db=test_db)
    assert after["count"] == 0


def test_chat_answer_uses_cross_session_stock_memory(test_db, sample_stocks):
    from backend.api.routes.ai import _context_answer
    from backend.memory.stock_memory import create_stock_memory

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="300308 历史记忆：订单兑现不足时降低新闻权重",
        source_type="test",
        importance=5,
    )

    response = _context_answer("帮我看一下 300308", test_db, session_id=None)

    assert "订单兑现不足时降低新闻权重" in response.answer
    assert "stock_memory" in response.used_resources


def test_deep_research_memory_writes_stock_research_pointer(test_db):
    from backend.memory.research_memory import remember_deep_research
    from backend.memory.stock_memory import list_stock_memories

    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="报告摘要，不包含原始长文正文",
        symbols=["300308"],
        report_path="/tmp/report.md",
    )

    rows = list_stock_memories(test_db, symbol="300308", memory_type="research_pointer")
    assert len(rows) == 1
    assert rows[0]["summary"] == "报告摘要，不包含原始长文正文"
    assert rows[0]["source_ref"] == "/tmp/report.md"
    thesis_rows = list_stock_memories(test_db, symbol="300308", memory_type="thesis")
    assert len(thesis_rows) == 1
    assert thesis_rows[0]["source_type"] == "deep_research_candidate"


def test_update_judgment_outcomes_writes_outcome_and_lesson(test_db):
    from backend.data.database import Price
    from backend.memory.stock_memory import (
        create_stock_memory,
        list_stock_memories,
        update_judgment_outcomes,
    )

    for i, close in enumerate([100, 99, 98, 97, 96, 95]):
        test_db.add(Price(
            symbol="300308",
            date=f"2026-05-{20 + i:02d}",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
        ))
    test_db.commit()
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="2026-05-20 建议可小仓试错，综合分+30",
        evidence={"date": "2026-05-20", "recommendation": "可小仓试错"},
        source_type="postmarket_signal",
        source_ref="300308:2026-05-20",
    )

    written = update_judgment_outcomes(test_db, symbol="300308")

    outcomes = list_stock_memories(test_db, symbol="300308", memory_type="outcome")
    lessons = list_stock_memories(test_db, symbol="300308", memory_type="lesson")
    assert written == 2
    assert "1d-1.00%" in outcomes[0]["summary"]
    assert "技术确认与新闻兑现" in lessons[0]["summary"]
