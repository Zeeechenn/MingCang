from __future__ import annotations

from sqlalchemy import text


def test_recall_schema_is_idempotent_and_indexes_existing_rows(test_db):
    from backend.data.schema_runtime import _ensure_memory_recall_schema
    from backend.memory.recall import recall
    from backend.memory.stock_memory import create_stock_memory

    _ensure_memory_recall_schema(test_db.get_bind())
    _ensure_memory_recall_schema(test_db.get_bind())
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="光模块 CPO 订单兑现需要跟踪毛利率。",
        source_type="unit",
        source_ref="m57-recall:1",
    )

    rows = recall(test_db, "光模块", symbol="300308", limit=5)

    assert rows
    assert rows[0]["source"] == "stock_memory_items"
    assert rows[0]["namespace"] == "研究论点"
    assert rows[0]["symbol"] == "300308"
    assert "光模块" in rows[0]["body"]


def test_recall_filters_namespace_and_symbol(test_db):
    from backend.memory.ai_memory import remember
    from backend.memory.recall import recall
    from backend.memory.stock_memory import create_stock_memory

    remember(test_db, "risk:global", "光模块 不追高规则", category="risk", scope="global", force=True)
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="光模块 800G 放量跟踪。",
        source_type="unit",
        source_ref="m57-recall:2",
    )
    create_stock_memory(
        test_db,
        symbol="600519",
        memory_type="thesis",
        summary="光模块 误配到其他股票。",
        source_type="unit",
        source_ref="m57-recall:3",
    )

    rows = recall(test_db, "光模块", namespace="研究论点", symbol="300308", limit=10)

    assert rows
    assert {row["source"] for row in rows} == {"stock_memory_items"}
    assert {row["symbol"] for row in rows} == {"300308"}


def test_recall_as_of_filters_dual_timeline_sources(test_db):
    from backend.memory.evolution_trace import NAMESPACE_RESEARCH_THESIS, record_trace
    from backend.memory.recall import recall

    record_trace(
        test_db,
        trace_type="unit.memory",
        namespace=NAMESPACE_RESEARCH_THESIS,
        subject="300308",
        symbols=["300308"],
        themes=["CPO"],
        content="旧光模块论点，系统已知道。",
        as_of="2026-07-01",
        event_time="2026-07-01T09:00:00",
        ingestion_time="2026-07-01T10:00:00",
    )
    record_trace(
        test_db,
        trace_type="unit.memory",
        namespace=NAMESPACE_RESEARCH_THESIS,
        subject="300308",
        symbols=["300308"],
        themes=["CPO"],
        content="新光模块论点，as-of 之后才知道。",
        as_of="2026-07-03",
        event_time="2026-07-03T09:00:00",
        ingestion_time="2026-07-03T10:00:00",
    )
    record_trace(
        test_db,
        trace_type="unit.memory",
        namespace=NAMESPACE_RESEARCH_THESIS,
        subject="300308",
        symbols=["300308"],
        themes=["CPO"],
        content="失效光模块论点。",
        as_of="2026-06-30",
        event_time="2026-06-30T09:00:00",
        ingestion_time="2026-06-30T10:00:00",
        invalidated_at="2026-07-01T12:00:00",
    )

    rows = recall(test_db, "光模块", symbol="300308", as_of="2026-07-02T00:00:00", limit=10)
    bodies = [row["body"] for row in rows]

    assert any("旧光模块论点" in body for body in bodies)
    assert not any("新光模块论点" in body for body in bodies)
    assert not any("失效光模块论点" in body for body in bodies)
    assert all(row["supports_as_of"] for row in rows)


def test_context_governor_uses_recall_block(test_db):
    from backend.memory.context_governor import ContextBudget, build_agent_context
    from backend.memory.stock_memory import create_stock_memory

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="光模块 订单兑现低于预期时要降低仓位。",
        source_type="unit",
        source_ref="m57-governor:1",
    )

    packed = build_agent_context(
        test_db,
        task_type="research",
        query="光模块",
        symbol="300308",
        budget=ContextBudget(total=320, resident=120, retrieval=160),
    )

    assert "【检索记忆块】" in packed["text"]
    assert "光模块 订单兑现低于预期" in packed["retrieval_text"]
    assert any(ref.startswith("recall:stock_memory_items:") for ref in packed["provenance"])
    payload = test_db.execute(
        text("SELECT payload_json FROM evolution_traces WHERE id = :id"),
        {"id": packed["trace_id"]},
    ).scalar_one()
    assert "recall:stock_memory_items:" in payload
