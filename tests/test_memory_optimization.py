"""Outcome-backed memory optimization regression tests."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import text


def test_query_filter_runs_before_limit(test_db):
    from backend.memory.stock_memory import create_stock_memory, list_stock_memories

    target = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="旧记录里的海外客户砍单风险",
        source_type="test",
    )
    for index in range(20):
        create_stock_memory(
            test_db,
            symbol="300308",
            memory_type="risk",
            summary=f"较新的无关记录 {index}",
            source_type="test",
        )

    rows = list_stock_memories(test_db, symbol="300308", q="砍单", limit=3)

    assert [row["id"] for row in rows] == [target["id"]]


def test_context_compacts_outcomes_and_suppresses_raw_judgment_noise(test_db):
    from backend.memory.stock_memory import build_memory_context, create_stock_memory

    for index, value in enumerate([3.0, 2.0, -1.0, 5.0, -2.0, 4.0]):
        create_stock_memory(
            test_db,
            symbol="300308",
            memory_type="outcome",
            summary=f"结果 {index}",
            evidence={
                "recommendation": "可小仓试错",
                "returns": {"10d": value + 1},
                "excess_returns": {"10d": value},
            },
            source_type="outcome_update",
            source_ref=f"outcome:test:{index}",
            status="validated",
        )
    for index in range(12):
        create_stock_memory(
            test_db,
            symbol="300308",
            memory_type="judgment",
            summary=f"原始判断流水 {index}",
            evidence={"date": "2026-05-20", "recommendation": "可关注"},
            source_type="postmarket_signal",
            source_ref=f"judgment:test:{index}",
        )

    context = build_memory_context(test_db, symbol="300308", limit=8)

    assert "历史结果校准" in context["text"]
    assert "入场类判断：n=6" in context["text"]
    assert "相对沪深300" in context["text"]
    assert "原始判断流水" not in context["text"]
    assert context["outcome_sample_count"] == 6


def test_decision_context_is_shadow_only_while_explicit_retrieval_remains(test_db, monkeypatch):
    from backend.config import settings
    from backend.memory.stock_memory import (
        build_decision_memory_context,
        build_memory_context,
        create_stock_memory,
    )

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="历史风险仅允许显式查看",
        source_type="test",
    )
    monkeypatch.setattr(settings, "memory_decision_context_enabled", False)

    decision = build_decision_memory_context(test_db, symbol="300308")
    explicit = build_memory_context(test_db, symbol="300308", record_usage=False)

    assert decision["text"] == ""
    assert decision["used_stock_memory_ids"] == []
    assert decision["memory_mode"] == "shadow_only"
    assert decision["decision_context_enabled"] is False
    assert "历史风险仅允许显式查看" in explicit["text"]


def test_decision_context_requires_explicit_promotion_switch(test_db, monkeypatch):
    from backend.config import settings
    from backend.memory.stock_memory import build_decision_memory_context, create_stock_memory

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="显式晋升后才允许进入决策上下文",
        source_type="test",
    )
    monkeypatch.setattr(settings, "memory_decision_context_enabled", True)

    context = build_decision_memory_context(test_db, symbol="300308", record_usage=False)

    assert "显式晋升后才允许进入决策上下文" in context["text"]
    assert context["memory_mode"] == "decision_context_enabled"
    assert context["decision_context_enabled"] is True


def test_outcome_calibration_deduplicates_same_day_reruns(test_db):
    from backend.memory.experience import build_outcome_calibration
    from backend.memory.stock_memory import create_stock_memory

    for index, value in enumerate((-8.0, 6.0), start=1):
        create_stock_memory(
            test_db,
            symbol="300308",
            memory_type="outcome",
            summary=f"rerun {index}",
            evidence={
                "recommendation": "可小仓试错",
                "excess_returns": {"10d": value},
                "judgment_evidence": {"date": "2026-07-01"},
            },
            source_type="test",
            source_ref=f"outcome:rerun:{index}",
            status="validated",
        )

    result = build_outcome_calibration(test_db, symbol="300308")

    assert result["sample_count"] == 1
    assert "n=1" in result["text"]


def test_outcome_calibration_applies_limit_after_observation_dedup(test_db):
    from backend.memory.experience import build_outcome_calibration
    from backend.memory.stock_memory import create_stock_memory

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="outcome",
        summary="older unique day",
        evidence={
            "recommendation": "可小仓试错",
            "excess_returns": {"10d": 2.0},
            "judgment_evidence": {"date": "2026-06-30"},
        },
        source_type="test",
        source_ref="outcome:older-unique",
        status="validated",
    )
    for index in range(3):
        create_stock_memory(
            test_db,
            symbol="300308",
            memory_type="outcome",
            summary=f"newer rerun {index}",
            evidence={
                "recommendation": "可小仓试错",
                "excess_returns": {"10d": -2.0},
                "judgment_evidence": {"date": "2026-07-01"},
            },
            source_type="test",
            source_ref=f"outcome:newer-rerun:{index}",
            status="validated",
        )

    result = build_outcome_calibration(test_db, symbol="300308", limit=2)

    assert result["sample_count"] == 2
    assert "n=2" in result["text"]


def test_archive_resolved_judgments_is_reversible_compaction(test_db):
    from backend.memory.maintenance import archive_resolved_judgments
    from backend.memory.stock_memory import create_stock_memory

    judgment = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="等待结果的原始判断",
        evidence={"date": "2026-05-20", "recommendation": "可小仓试错"},
        source_type="postmarket_signal",
        source_ref="300308:2026-05-20",
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="outcome",
        summary="完整窗口结果",
        evidence={"recommendation": "可小仓试错", "returns": {"10d": 2.0}},
        source_type="outcome_update",
        source_ref=f"outcome:{judgment['id']}",
        status="validated",
    )
    old = (datetime.utcnow() - timedelta(days=60)).isoformat(timespec="seconds")
    test_db.execute(
        text("UPDATE stock_memory_items SET created_at=:old WHERE id=:id"),
        {"old": old, "id": judgment["id"]},
    )
    test_db.commit()

    archived = archive_resolved_judgments(test_db, retention_days=30)
    status = test_db.execute(
        text("SELECT status FROM stock_memory_items WHERE id=:id"),
        {"id": judgment["id"]},
    ).scalar()

    assert archived == 1
    assert status == "archived"


def test_archive_unresolvable_judgment_requires_mature_later_prices(test_db):
    import json

    from backend.memory.maintenance import archive_unresolvable_judgments
    from backend.memory.stock_memory import create_stock_memory

    judgment = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="judgment",
        summary="周末运行日不应伪造结果",
        evidence={"date": "2026-05-30", "recommendation": "可小仓试错"},
        source_type="postmarket_signal",
        source_ref="300308:2026-05-30",
    )
    for day in range(1, 12):
        test_db.execute(text("""
            INSERT INTO prices(symbol, asset_key, market, date, open, high, low, close, volume)
            VALUES('300308', 'CN:300308', 'CN', :date, 10, 11, 9, 10, 100)
        """), {"date": f"2026-06-{day:02d}"})
    test_db.commit()

    archived = archive_unresolvable_judgments(test_db)
    row = test_db.execute(text(
        "SELECT status, evidence_json FROM stock_memory_items WHERE id=:id"
    ), {"id": judgment["id"]}).first()

    assert archived == 1
    assert row.status == "archived"
    assert json.loads(row.evidence_json)["date"] == "2026-05-30"


def test_memory_health_detects_equal_count_but_different_recall_sets(test_db):
    from backend.memory.maintenance import memory_health_snapshot
    from backend.memory.recall import sync_recall_index
    from backend.memory.stock_memory import create_stock_memory

    first = create_stock_memory(
        test_db, symbol="300308", memory_type="risk", summary="first",
        source_type="test", source_ref="risk:first",
    )
    create_stock_memory(
        test_db, symbol="300308", memory_type="risk", summary="second",
        source_type="test", source_ref="risk:second",
    )
    sync_recall_index(test_db)
    test_db.execute(
        text("UPDATE stock_memory_items SET status='archived' WHERE id=:id"),
        {"id": first["id"]},
    )
    create_stock_memory(
        test_db, symbol="300308", memory_type="risk", summary="third",
        source_type="test", source_ref="risk:third",
    )

    health = memory_health_snapshot(test_db)

    assert health["active_stock_memory_rows"] == health["indexed_stock_memory_rows"]
    assert health["recall_index_gap"] == 1
    assert health["recall_index_stale_rows"] == 1
    assert health["recall_index_exact"] is False


def test_track_analyst_prompt_excludes_project_memory_in_shadow_mode(test_db, sample_stocks, monkeypatch):
    from backend.agents.long_term import track_analyst
    from backend.memory.stock_memory import create_stock_memory

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="历史经验：海外客户资本开支下修时容易误判",
        source_type="test",
        importance=5,
    )
    captured: dict[str, str] = {}

    class Provider:
        def complete_structured(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return {
                "layer3_cycle_or_structural": "混合",
                "layer5_entry_timing": "观望",
                "score": 10,
                "label_vote": "观望",
                "key_findings": ["当前证据优先"],
            }

    monkeypatch.setattr(track_analyst, "runtime_readiness", lambda settings: {"usable": True, "reason": "ok"})
    monkeypatch.setattr(track_analyst, "get_provider", lambda: Provider())
    monkeypatch.setattr(track_analyst, "_fetch_supply_chain_evidence", lambda industry, name: [])
    monkeypatch.setattr(track_analyst.settings, "memory_decision_context_enabled", False)

    report = track_analyst.analyze("300308", "中际旭创", test_db)

    assert report.label_vote == "观望"
    assert "历史经验（只作为待验证先验" not in captured["prompt"]
    assert "海外客户资本开支下修时容易误判" not in captured["prompt"]
    assert report.raw["memory_refs"] == []
    assert report.raw["memory_mode"] == "shadow_only"
    assert report.raw["memory_decision_context_applied"] is False


def test_postmarket_persist_accrues_memory_outcomes(test_db, monkeypatch):
    from backend.jobs import postmarket

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("backend.decision.aggregator.save_signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "backend.decision.memory_layered.save_decision_layered",
        lambda symbol, date, result, db: calls.append(("layered", symbol)),
    )
    monkeypatch.setattr(
        "backend.memory.stock_memory.update_judgment_outcomes",
        lambda db, symbol: calls.append(("outcome", symbol)) or 2,
    )
    monkeypatch.setattr("backend.decision.harness.review_latest_signal", lambda db, symbol: None)

    postmarket._persist_postmarket_stock(
        SimpleNamespace(symbol="300308", market="CN"),
        {"date": "2026-05-20", "result": {}},
        test_db,
    )

    assert ("layered", "300308") in calls
    assert ("outcome", "300308") in calls


def test_postmarket_memory_recall_sync_runs_once_through_shared_helper(test_db, monkeypatch):
    import importlib

    from backend.jobs import postmarket

    calls: list[object] = []
    recall_module = importlib.import_module("backend.memory.recall")
    monkeypatch.setattr(
        recall_module,
        "sync_recall_index",
        lambda db: calls.append(db),
    )

    assert postmarket._sync_postmarket_memory_recall(test_db) is True
    assert calls == [test_db]


def test_read_only_context_does_not_write_layered_recall_audit(test_db):
    from backend.memory.stock_memory import build_memory_context

    test_db.execute(text("""
        INSERT INTO decision_memory_layered(symbol, layer, content, updated_at)
        VALUES('__GLOBAL__', 'long', '# 长期反思\n\n## 2026-W20\n\n历史偏差', '2026-05-20')
    """))
    test_db.commit()

    context = build_memory_context(
        test_db,
        symbol="300308",
        record_usage=False,
    )
    audit_table = test_db.execute(text(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='audit_log_fts'"
    )).scalar()
    audits = 0 if not audit_table else test_db.execute(text(
        "SELECT count(*) FROM audit_log_fts WHERE event_type='decision_memory.recall'"
    )).scalar()

    assert "历史偏差" in context["text"]
    assert audits == 0
