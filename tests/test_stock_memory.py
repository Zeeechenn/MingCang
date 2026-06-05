"""M12 structured stock memory: cross-entry recall and governance."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
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
    assert "used_memory_atom_ids" in ctx
    assert "l0_context" in ctx


def test_build_memory_context_includes_l0_trusted_and_pending_sections(test_db):
    from backend.memory.l0_memory import create_memory_atom, promote_atom
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    trusted = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="thesis",
        summary="L0 trusted thesis：订单兑现改善",
        source_type="test",
        source_ref="stock-context-trusted",
        trust_state="pending",
    )
    promote_atom(test_db, trusted["id"], confirmed_by="tester")
    pending = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="risk",
        summary="L0 pending risk：客户砍单",
        source_type="test",
        source_ref="stock-context-pending",
        trust_state="pending",
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="旧股票记忆仍然保留",
        source_type="test",
    )

    ctx = build_memory_context(test_db, symbol="300308", limit=8, include_l0=True)

    assert "L0 trusted thesis：订单兑现改善" in ctx["text"]
    assert "L0 pending risk：客户砍单" in ctx["text"]
    assert "旧股票记忆仍然保留" in ctx["text"]
    assert set(ctx["used_memory_atom_ids"]) == {trusted["id"], pending["id"]}
    assert ctx["l0_context"]["legacy_memory"] == []


def test_build_memory_context_keeps_l0_dormant_by_default(test_db, monkeypatch):
    from backend.config import settings
    from backend.memory.l0_memory import create_memory_atom, promote_atom
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    monkeypatch.setattr(settings, "atlas_enabled", False)
    atom = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="thesis",
        summary="L0 dormant thesis should not enter production memory context",
        source_type="test",
        source_ref="stock-context-dormant",
        trust_state="pending",
    )
    promote_atom(test_db, atom["id"], confirmed_by="tester")
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="旧股票记忆仍然保留",
        source_type="test",
    )

    ctx = build_memory_context(test_db, symbol="300308", limit=8)

    assert "L0 dormant thesis should not enter production memory context" not in ctx["text"]
    assert "旧股票记忆仍然保留" in ctx["text"]
    assert ctx["used_memory_atom_ids"] == []
    assert ctx["l0_context"]["trusted_memory"] == []


def test_build_memory_context_keeps_unrelated_global_preference_out_of_symbol_context(test_db):
    from backend.memory.ai_memory import remember
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    remember(test_db, "pref:unrelated", "用户偏好：只关注白酒龙头", category="preference")
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="300308 需要跟踪海外客户资本开支变化",
        source_type="test",
        importance=5,
    )

    ctx = build_memory_context(test_db, symbol="300308", query="光模块 订单", limit=8)

    assert "300308 需要跟踪海外客户资本开支变化" in ctx["text"]
    assert "只关注白酒龙头" not in ctx["text"]


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


def test_stock_memory_context_route_does_not_update_usage_or_audit(test_db):
    from backend.api.routes.memory import stock_memory_context
    from backend.memory.l0_memory import create_memory_atom, promote_atom
    from backend.memory.stock_memory import create_stock_memory

    row = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="供应链风险需要复核",
        source_type="test",
        importance=5,
    )
    atom = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="thesis",
        summary="L0 只读 context",
        source_type="test",
        source_ref="route-readonly",
        trust_state="pending",
    )
    promote_atom(test_db, atom["id"], confirmed_by="tester")

    ctx = stock_memory_context("300308", db=test_db)

    used = test_db.execute(
        text("SELECT last_used_at FROM stock_memory_items WHERE id = :id"),
        {"id": row["id"]},
    ).scalar()
    audits = test_db.execute(text(
        "SELECT count(*) FROM audit_log_fts WHERE event_type='stock_memory.recall'"
    )).scalar()
    l0_used = test_db.execute(
        text("SELECT last_used_at FROM memory_atoms WHERE id = :id"),
        {"id": atom["id"]},
    ).scalar()
    l0_audits = test_db.execute(text(
        "SELECT count(*) FROM audit_log_fts WHERE event_type='l0_memory.recall'"
    )).scalar()
    assert "供应链风险需要复核" in ctx["text"]
    assert "L0 只读 context" in ctx["text"]
    assert used is None
    assert audits == 0
    assert l0_used is None
    assert l0_audits == 0


def test_l0_memory_routes_promote_refute_and_validate_payload(test_db):
    from fastapi import HTTPException

    from backend.api.routes.memory import (
        L0TrustPayload,
        l0_memory_atom_promote,
        l0_memory_atom_refute,
    )
    from backend.memory.l0_memory import create_memory_atom

    promote_target = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="lesson",
        summary="可晋升 L0 记忆",
        source_type="test",
        source_ref="route-promote",
        trust_state="pending",
    )
    promoted = l0_memory_atom_promote(
        promote_target["id"],
        L0TrustPayload(confirmed_by="human"),
        db=test_db,
    )
    assert promoted["trust_state"] == "trusted"

    refute_target = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="risk",
        summary="可否定 L0 记忆",
        source_type="test",
        source_ref="route-refute",
        trust_state="pending",
    )
    refuted = l0_memory_atom_refute(
        refute_target["id"],
        L0TrustPayload(confirmed_by="human", reason="证据不支持"),
        db=test_db,
    )
    assert refuted["trust_state"] == "refuted"
    assert refuted["refutation_reason"] == "证据不支持"

    with pytest.raises(HTTPException) as empty_confirm:
        l0_memory_atom_promote(
            refute_target["id"],
            L0TrustPayload(confirmed_by=" "),
            db=test_db,
        )
    assert empty_confirm.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        l0_memory_atom_promote(
            99999,
            L0TrustPayload(confirmed_by="human"),
            db=test_db,
        )
    assert missing.value.status_code == 404


def test_l0_memory_route_guards_reject_remote_even_with_write_allowlist(monkeypatch):
    from fastapi import HTTPException

    from backend.agent.http_guard import agent_write_guard
    from backend.api.routes.memory import local_human_l0_gate

    class FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS", "l0_memory.promote")
    request = FakeRequest({"x-stocksage-agent-api-key": "secret"})

    agent_write_guard("l0_memory.promote")(request)
    with pytest.raises(HTTPException) as exc:
        local_human_l0_gate(request)
    assert exc.value.status_code == 403


def test_l0_memory_context_route_invalid_filters_return_400(test_db):
    from fastapi import HTTPException

    from backend.api.routes.memory import l0_memory_atoms, l0_memory_context

    with pytest.raises(HTTPException) as bad_scope:
        l0_memory_context(scope_type="unsupported", db=test_db)
    assert bad_scope.value.status_code == 400

    with pytest.raises(HTTPException) as bad_trust:
        l0_memory_atoms(trust_state="invented", db=test_db)
    assert bad_trust.value.status_code == 400


def test_build_memory_context_marks_multiple_used_ids_with_bound_params(test_db):
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    first = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="供应链风险需要复核",
        source_type="test",
    )
    second = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="订单兑现是主线",
        source_type="test",
    )

    ctx = build_memory_context(test_db, symbol="300308", limit=5)

    assert set(ctx["used_stock_memory_ids"]) == {first["id"], second["id"]}
    rows = test_db.execute(
        text("SELECT id, last_used_at FROM stock_memory_items ORDER BY id")
    ).all()
    assert {row.id for row in rows if row.last_used_at is not None} == {first["id"], second["id"]}


def test_stock_memory_patch_importance_does_not_refresh_updated_at(test_db):
    from backend.memory.stock_memory import create_stock_memory, patch_stock_memory

    row = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="供应链风险需要复核",
        source_type="test",
        ttl_days=7,
    )
    old = "2026-05-01T00:00:00"
    test_db.execute(
        text("UPDATE stock_memory_items SET updated_at = :old WHERE id = :id"),
        {"old": old, "id": row["id"]},
    )
    test_db.commit()

    patched = patch_stock_memory(test_db, row["id"], importance=5)

    assert patched["importance"] == 5
    assert patched["updated_at"] == old


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
    assert rows[0]["summary"] == "300308 研究索引：报告摘要，不包含原始长文正文"
    assert rows[0]["source_ref"] == "/tmp/report.md#research:300308"
    # M15.3: 不再批量生成 thesis/risk/event candidate 噪声；真正的结构化字段需 LLM 输出
    assert list_stock_memories(test_db, symbol="300308", memory_type="thesis") == []
    assert list_stock_memories(test_db, symbol="300308", memory_type="risk") == []
    assert list_stock_memories(test_db, symbol="300308", memory_type="event") == []


def test_persisted_research_pointer_sections_build_research_context(test_db):
    from backend.agents.pipeline import build_research_context
    from backend.memory.research_memory import remember_deep_research
    from backend.memory.stock_memory import list_stock_memories

    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="订单兑现是核心验证点，估值拥挤是主要风险",
        symbols=["300308"],
        report_path="/tmp/report.md",
        sections=[{
            "role": "research_writer",
            "title": "IC memo",
            "catalysts": ["海外订单兑现"],
            "risks": ["估值拥挤风险"],
            "evidence_snippets": ["订单排产证据", "估值分位证据"],
            "stance": "中性偏多",
            "confidence": 0.72,
        }],
    )

    rows = list_stock_memories(test_db, symbol="300308", memory_type="research_pointer")
    context = build_research_context(sentiment_result={"research_context": rows})

    assert context["catalysts"] == ["海外订单兑现"]
    assert context["risks"] == ["估值拥挤风险"]
    assert context["evidence_snippets"] == ["订单排产证据", "估值分位证据"]
    assert context["stance"] == "中性偏多"
    assert context["confidence"] == 0.72


def test_research_dossier_recalls_deep_research_pointer(test_db, sample_stocks):
    from backend.memory.research_memory import remember_deep_research
    from backend.research.dossier import build_research_dossier

    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="订单兑现是核心验证点，估值拥挤是主要风险",
        symbols=["300308"],
        report_path="/tmp/report.md",
    )

    dossier = build_research_dossier(test_db, "300308")

    assert dossier["symbol"] == "300308"
    assert dossier["stock"]["name"] == "中际旭创"
    assert len(dossier["deep_research"]) == 1
    assert "AI算力产业链" in dossier["deep_research"][0]["evidence"]["topic"]
    assert "latest_signal" in dossier["missing"]
    assert "copilot" in dossier["missing"]


def test_research_dossier_exposes_copilot_pending_questions(test_db, sample_stocks):
    import json

    from backend.data.database import ResearchState
    from backend.research.dossier import build_research_dossier

    test_db.add(ResearchState(
        symbol="300308",
        thesis="",
        risks_json="[]",
        open_questions_json="[]",
        copilot_json=json.dumps({
            "validation_questions": ["订单是否继续兑现？", "估值风险是否缓解？"],
        }, ensure_ascii=False),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ))
    test_db.commit()

    dossier = build_research_dossier(test_db, "300308")

    assert dossier["pending_questions"] == ["订单是否继续兑现？", "估值风险是否缓解？"]
    assert "pending_questions" in dossier["missing"]
    assert "copilot" not in dossier["missing"]


def test_research_dossier_combines_signal_label_memory_and_action(test_db, sample_stocks):
    from backend.agents.long_term.base import LongTermLabel
    from backend.agents.long_term.storage import save_label
    from backend.data.database import Signal
    from backend.decision.harness import record_decision_run
    from backend.memory.stock_memory import create_stock_memory
    from backend.research.dossier import build_research_dossier

    test_db.add(Signal(
        symbol="300308",
        date="2026-05-25",
        quant_score=0,
        technical_score=80,
        sentiment_score=80,
        composite_score=60,
        recommendation="可小仓试错",
        confidence="高",
        stop_loss=9,
        take_profit=12,
        limit_status="normal",
        rule_version="aggregate_v1:new_framework",
    ))
    save_label(LongTermLabel(
        symbol="300308",
        date="2026-05-25",
        label="规避",
        score=-50,
        votes={"track": "规避"},
        key_findings=["深研风险未解除"],
        expires_at="2999-01-01",
    ), test_db)
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="海外订单兑现不足时避免追高",
        source_type="test",
        importance=5,
    )
    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="300308",
        as_of="2026-05-25",
        result={
            "rule_version": "aggregate_v1:new_framework",
            "recommendation": "观望",
            "confidence": "高",
            "composite_score": 60,
            "breakdown": {"technical": 80, "sentiment": 80, "quant": 0},
            "risk_notes": ["长期团'规避'阻断入场"],
            "research_conflicts": [{
                "type": "short_long_conflict",
                "severity": "high",
                "summary": "短线入场信号与长期规避标签冲突",
            }],
            "official_action": {
                "recommendation": "观望",
                "position_pct": 0.0,
                "is_constrained": True,
                "constraint_count": 1,
                "conflict_count": 1,
            },
            "stop_loss": 9,
            "take_profit": 12,
            "position_pct": 0.0,
        },
    )

    dossier = build_research_dossier(test_db, "300308")

    assert dossier["latest_signal"]["recommendation"] == "可小仓试错"
    assert dossier["long_term_label"]["label"] == "规避"
    assert dossier["official_action"]["recommendation"] == "观望"
    assert dossier["official_action"]["is_constrained"] is True
    assert any(c["type"] == "short_long_conflict" for c in dossier["conflicts"])
    assert any(row["memory_type"] == "risk" for row in dossier["stock_memory"])


def test_research_dossier_keeps_deep_research_out_of_official_action(test_db, sample_stocks):
    from backend.data.database import Signal
    from backend.decision.harness import record_decision_run
    from backend.memory.research_memory import remember_deep_research
    from backend.research.dossier import build_research_dossier

    test_db.add(Signal(
        symbol="300308",
        date="2026-05-25",
        quant_score=0,
        technical_score=80,
        sentiment_score=80,
        composite_score=60,
        recommendation="可小仓试错",
        confidence="高",
        stop_loss=9,
        take_profit=12,
        limit_status="normal",
        rule_version="aggregate_v1:new_framework",
    ))
    test_db.commit()
    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="300308",
        as_of="2026-05-25",
        result={
            "rule_version": "aggregate_v1:new_framework",
            "recommendation": "观望",
            "confidence": "高",
            "composite_score": 60,
            "official_action": {
                "recommendation": "观望",
                "position_pct": 0.0,
                "is_constrained": True,
            },
            "position_pct": 0.0,
        },
    )
    record_decision_run(
        test_db,
        run_type="deep_research",
        symbol="300308",
        as_of="2026-05-25",
        result={
            "rule_version": "deep_research_v1",
            "recommendation": "深研偏多",
            "confidence": "高",
            "composite_score": 95,
            "official_action": {
                "recommendation": "深研偏多",
                "position_pct": 0.30,
            },
            "position_pct": 0.30,
        },
    )
    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="深研证据仍应作为指针展示",
        symbols=["300308"],
        report_path="/tmp/report.md",
    )

    dossier = build_research_dossier(test_db, "300308")

    assert dossier["evidence"][0]["run_type"] == "deep_research"
    assert dossier["official_action"]["recommendation"] == "观望"
    assert dossier["official_action"]["position_pct"] == 0.0
    assert len(dossier["deep_research"]) == 1


def test_deep_research_memory_keeps_per_symbol_pointers(test_db):
    from backend.memory.research_memory import remember_deep_research
    from backend.memory.stock_memory import list_stock_memories

    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="报告摘要，不包含原始长文正文",
        symbols=["300308", "603986"],
        report_path="/tmp/report.md",
    )

    first = list_stock_memories(test_db, symbol="300308", memory_type="research_pointer")
    second = list_stock_memories(test_db, symbol="603986", memory_type="research_pointer")
    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["source_ref"] != second[0]["source_ref"]


def test_update_judgment_outcomes_writes_outcome_and_lesson(test_db):
    from backend.data.database import Price
    from backend.memory.stock_memory import (
        create_stock_memory,
        list_stock_memories,
        update_judgment_outcomes,
    )

    for i, close in enumerate([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90]):
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
    assert "10d-10.00%" in outcomes[0]["summary"]
    assert "技术确认与新闻兑现" in lessons[0]["summary"]


def test_create_stock_memory_upserts_on_source_ref(test_db):
    """M15.0: a re-run with the same source_ref updates in place, not duplicates."""
    from backend.memory.stock_memory import create_stock_memory, list_stock_memories

    first = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="2026-05-20 建议可关注，综合分+12",
        evidence={"date": "2026-05-20", "recommendation": "可关注"},
        source_type="postmarket_signal",
        source_ref="300308:2026-05-20",
    )
    second = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="2026-05-20 建议可小仓试错，综合分+31",
        evidence={"date": "2026-05-20", "recommendation": "可小仓试错"},
        source_type="postmarket_signal",
        source_ref="300308:2026-05-20",
    )

    rows = list_stock_memories(test_db, symbol="300308", memory_type="judgment", limit=20)
    assert second["id"] == first["id"]
    assert len(rows) == 1
    assert rows[0]["summary"] == "2026-05-20 建议可小仓试错，综合分+31"


def test_create_stock_memory_without_source_ref_always_inserts(test_db):
    """Rows without a source_ref carry no idempotency key and are not deduped."""
    from backend.memory.stock_memory import create_stock_memory, list_stock_memories

    for _ in range(2):
        create_stock_memory(
            test_db,
            symbol="300308",
            memory_type="risk",
            summary="无 source_ref 的临时风险记忆",
            source_type="test",
        )
    rows = list_stock_memories(test_db, symbol="300308", memory_type="risk", limit=20)
    assert len(rows) == 2


def test_update_judgment_outcomes_waits_for_full_horizon(test_db):
    """M15.0: no outcome is frozen until a full 10-trading-day horizon exists."""
    from backend.data.database import Price
    from backend.memory.stock_memory import (
        create_stock_memory,
        list_stock_memories,
        update_judgment_outcomes,
    )

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="2026-05-20 建议可小仓试错",
        evidence={"date": "2026-05-20", "recommendation": "可小仓试错"},
        source_type="postmarket_signal",
        source_ref="300308:2026-05-20",
    )

    # Only 6 trading days of prices: the 10-day horizon is not complete yet.
    for i, close in enumerate([100, 99, 98, 97, 96, 95]):
        test_db.add(Price(symbol="300308", date=f"2026-05-{20 + i:02d}",
                          open=close, high=close, low=close, close=close, volume=1000))
    test_db.commit()
    assert update_judgment_outcomes(test_db, symbol="300308") == 0
    assert list_stock_memories(test_db, symbol="300308", memory_type="outcome") == []

    # Extend to a full 11-row horizon: the outcome is written once, fully formed.
    for i, close in zip(range(6, 11), [94, 93, 92, 91, 90], strict=True):
        test_db.add(Price(symbol="300308", date=f"2026-05-{20 + i:02d}",
                          open=close, high=close, low=close, close=close, volume=1000))
    test_db.commit()
    written = update_judgment_outcomes(test_db, symbol="300308")
    outcomes = list_stock_memories(test_db, symbol="300308", memory_type="outcome")
    assert written == 2
    assert len(outcomes) == 1
    assert "10d-10.00%" in outcomes[0]["summary"]
