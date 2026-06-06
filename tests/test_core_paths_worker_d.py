"""Worker D focused coverage for core route, memory, and researcher paths."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.data.database import get_db
from backend.main import app


def _client_for_db(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _clear_client_override() -> None:
    app.dependency_overrides.pop(get_db, None)


def test_ai_chat_falls_back_to_project_context_for_incomplete_position(test_db, sample_stocks):
    from backend.api.routes.ai import chat
    from backend.api.schemas import AIChatRequest

    response = chat(
        AIChatRequest(message="帮我添加持仓 600519", mode="general"),
        db=test_db,
    )

    assert response.pending_action is None
    assert response.used_resources[:3] == ["stocks", "positions", "project_research"]
    assert "当前自选股包括" in response.answer
    assert "需要联网调研时" in response.answer


def test_ai_chat_auth_fails_in_remote_mode_without_key(test_db, monkeypatch):
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")

    client = _client_for_db(test_db)
    try:
        response = client.post(
            "/api/ai/chat",
            json={"message": "看看 600519", "mode": "general"},
        )
    finally:
        _clear_client_override()

    assert response.status_code == 401
    assert "api key" in response.json()["detail"].lower()


def test_ai_confirm_action_auth_fails_for_pending_dynamic_action(test_db, monkeypatch):
    from backend.api.routes.ai import chat, confirm_action
    from backend.api.schemas import AIChatRequest

    pending_response = chat(
        AIChatRequest(message="帮我添加自选股 600519 贵州茅台", mode="general"),
        db=test_db,
    )
    assert pending_response.pending_action is not None

    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")

    with pytest.raises(HTTPException) as exc:
        confirm_action(pending_response.pending_action["id"], db=test_db)

    assert exc.value.status_code == 401


def test_system_status_happy_path_counts_core_tables(test_db, monkeypatch):
    from backend.api.deps import get_settings
    from backend.api.routes.system import system_status
    from backend.data.database import FinancialMetric, LongTermLabel, Price

    monkeypatch.setattr("backend.llm.runtime_readiness", lambda settings: {"ready": True})
    monkeypatch.setattr("backend.scheduler.get_scheduler_state", lambda: {"jobs": {}})

    test_db.add(Price(symbol="600519", date="2026-05-29", open=1, high=2, low=1, close=2, volume=100))
    test_db.add(FinancialMetric(symbol="600519", report_date="2026-03-31", revenue=100))
    test_db.add(LongTermLabel(
        symbol="600519",
        date="2026-05-28",
        label="值得持有",
        score=71,
        expires_at="2026-06-07",
    ))
    test_db.commit()

    payload = system_status(db=test_db, settings=get_settings())

    assert payload["latest_price_date"] == "2026-05-29"
    assert payload["financial_metrics_count"] == 1
    assert payload["long_term_labels_count"] == 1
    assert payload["latest_long_term_label_date"] == "2026-05-28"
    assert payload["runtime_readiness"] == {"ready": True}


def test_system_runtime_config_auth_fails_in_remote_mode_without_key(test_db, monkeypatch):
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")

    client = _client_for_db(test_db)
    try:
        response = client.patch(
            "/api/system/runtime-config",
            json={"adx_filter_enabled": True},
        )
    finally:
        _clear_client_override()

    assert response.status_code == 401
    assert "api key" in response.json()["detail"].lower()


def test_system_health_degrades_when_db_queries_fail(monkeypatch):
    from backend.api.routes.system import system_health

    class FailingDb:
        def query(self, *args, **kwargs):
            raise RuntimeError("db offline")

    monkeypatch.setattr("backend.llm.runtime_readiness", lambda settings: {"ready": False})
    monkeypatch.setattr("backend.scheduler.get_scheduler_state", lambda: {"jobs": {}})

    payload = system_health(db=FailingDb())

    assert payload["healthy"] is False
    assert payload["db_ok"] is False
    assert payload["latest_price_date"] is None
    assert payload["runtime_readiness"] == {"ready": False}


def test_layered_context_combines_long_medium_short_and_audits(test_db, monkeypatch):
    from backend.config import settings
    from backend.decision import memory_layered

    monkeypatch.setattr(settings, "layered_memory_enabled", True)
    memory_layered._SHORT_TERM.clear()
    memory_layered._upsert_layered_row(
        test_db,
        symbol=None,
        layer="long",
        content="# long\n\n## 2026-W22\n\n长期反思内容\n",
    )
    memory_layered.save_short_term(
        "600519",
        {
            "composite_score": 21,
            "recommendation": "可小仓试错",
            "stop_loss": 10,
            "take_profit": 12,
        },
    )
    monkeypatch.setattr(
        "backend.decision.decision_memory.get_reflection_context",
        lambda symbol, db, lookback_days: "【中期记忆】历史表现良好",
    )

    context = memory_layered.get_layered_context("600519", test_db)

    assert "长期反思内容" in context
    assert "【中期记忆】历史表现良好" in context
    assert "【短期记忆" in context
    audit_count = test_db.execute(text(
        "SELECT count(*) FROM audit_log_fts WHERE event_type='decision_memory.recall'"
    )).scalar()
    assert audit_count == 1


def test_layered_context_uses_legacy_reflection_when_disabled(test_db, monkeypatch):
    from backend.config import settings
    from backend.decision import memory_layered

    monkeypatch.setattr(settings, "layered_memory_enabled", False)
    monkeypatch.setattr(
        "backend.decision.decision_memory.get_reflection_context",
        lambda symbol, db, lookback_days: f"legacy:{symbol}:{lookback_days}",
    )

    assert memory_layered.get_layered_context("600519", test_db, lookback_days=12) == "legacy:600519:12"


def test_researcher_multi_round_round1_schema_failure_records_reason(monkeypatch):
    from backend.agents import researcher
    from backend.agents.analyst import AnalystReport

    class Provider:
        def complete_structured(self, **kwargs):
            return {"key_signal": "technical"}

    reports = [
        AnalystReport(role="technical", score=60, confidence=0.7, key_findings=["突破"], raw={}),
        AnalystReport(role="quant", score=-30, confidence=0.6, key_findings=["估值偏高"], raw={}),
        AnalystReport(role="sentiment", score=20, confidence=0.5, key_findings=["情绪改善"], raw={}),
        AnalystReport(role="news", score=-10, confidence=0.5, key_findings=["事件消化"], raw={}),
    ]
    monkeypatch.setattr(researcher.settings, "multi_round_debate_enabled", True)
    monkeypatch.setattr(researcher.settings, "ai_provider", "anthropic")
    monkeypatch.setattr(researcher.settings, "anthropic_api_key", "fake")
    monkeypatch.setattr(researcher.settings, "openai_api_key", "")
    monkeypatch.setattr(researcher.settings, "multi_round_debate_min_divergence", 20.0)
    monkeypatch.setattr(researcher, "get_provider", lambda: Provider())

    conclusion = researcher.multi_round_debate(reports)

    assert conclusion.used_llm is False
    assert conclusion.fallback_reason.startswith("round1_invalid:")
    assert conclusion.rounds == []


def test_researcher_multi_round_too_few_reports_falls_back_without_provider(monkeypatch):
    from backend.agents import researcher
    from backend.agents.analyst import AnalystReport

    monkeypatch.setattr(researcher.settings, "multi_round_debate_enabled", True)
    monkeypatch.setattr(researcher.settings, "ai_provider", "anthropic")
    monkeypatch.setattr(researcher.settings, "anthropic_api_key", "fake")
    monkeypatch.setattr(researcher.settings, "openai_api_key", "")
    monkeypatch.setattr(researcher.settings, "multi_round_debate_min_divergence", 20.0)
    monkeypatch.setattr(
        researcher,
        "get_provider",
        lambda: pytest.fail("provider should not be loaded for too-few reports"),
    )
    reports = [
        AnalystReport(role="technical", score=30, confidence=0.6, key_findings=["突破"], raw={})
    ]

    conclusion = researcher.multi_round_debate(reports)

    assert conclusion.used_llm is False
    assert conclusion.action_bias == "偏多"
    assert conclusion.fallback_reason == "too_few_reports"
