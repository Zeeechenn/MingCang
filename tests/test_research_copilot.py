import json
from unittest.mock import MagicMock, patch

from backend.data.database import Price, ResearchState, Signal


def _signal(
    test_db,
    *,
    symbol="600519",
    recommendation="可关注",
    composite_score=20.0,
    technical_score=15.0,
    sentiment_score=30.0,
):
    sig = Signal(
        symbol=symbol,
        date="2026-05-22",
        quant_score=0,
        technical_score=technical_score,
        sentiment_score=sentiment_score,
        composite_score=composite_score,
        recommendation=recommendation,
        confidence="中",
        stop_loss=10.0,
        take_profit=14.0,
        limit_status="normal",
        rule_version="aggregate_v1:new_framework",
    )
    test_db.add(sig)
    test_db.add(Price(symbol=symbol, date="2026-05-22", open=11, high=12, low=10, close=11, volume=1))
    test_db.commit()
    return sig


def _provider(payload: dict):
    provider = MagicMock()
    provider.complete_structured.return_value = payload
    return provider


def _llm_payload(**overrides):
    payload = {
        "stance": "支持",
        "event_read": "订单改善带来短期催化，但需要确认持续性。",
        "technical_read": "技术分偏中性，尚未形成强趋势。",
        "risks": ["追高风险", "消息兑现风险"],
        "validation_questions": ["后续成交量能否维持？"],
        "summary_opinion": "可作为影子试错观察，不改变官方信号。",
        "shadow_position_pct": 0.99,
        "position_note": "LLM 原始仓位会被系统边界裁剪。",
    }
    payload.update(overrides)
    return payload


def test_generate_copilot_requires_runtime_llm_without_polluting_state(test_db):
    from backend.decision.harness import get_research_state
    from backend.research.copilot import CopilotUnavailable, generate_symbol_copilot

    _signal(test_db)

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=False):
        try:
            generate_symbol_copilot("600519", test_db)
        except CopilotUnavailable as exc:
            assert "LLM" in str(exc)
        else:
            raise AssertionError("expected CopilotUnavailable")

    assert get_research_state(test_db, "600519")["copilot"] is None


def test_generate_copilot_persists_structured_card_in_research_state(test_db):
    from backend.decision.harness import get_research_state, record_decision_run
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db)
    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="600519",
        as_of="2026-05-22",
        result={
            "rule_version": "aggregate_v1:new_framework",
            "recommendation": "可关注",
            "confidence": "中",
            "composite_score": 20.0,
            "breakdown": {"quant": 0, "technical": 15, "sentiment": 30},
            "position_pct": 0.0,
            "stop_loss": 10.0,
            "take_profit": 14.0,
        },
    )

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload())):
        card = generate_symbol_copilot("600519", test_db)

    state = get_research_state(test_db, "600519")
    assert state["copilot"]["stance"] == "支持"
    assert state["copilot"]["summary_opinion"] == card["summary_opinion"]
    assert state["copilot"]["official"]["recommendation"] == "可关注"


def test_shadow_trial_position_is_capped_when_official_position_is_zero(test_db, monkeypatch):
    from backend.research.copilot import generate_symbol_copilot

    monkeypatch.setattr("backend.research.copilot.settings.new_signal_trial_pct", 0.05)
    _signal(test_db, recommendation="可关注", composite_score=20.0)

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload())):
        card = generate_symbol_copilot("600519", test_db)

    assert card["official"]["position_pct"] == 0.0
    assert card["shadow_position_pct"] == 0.05


def test_existing_official_position_uses_only_allowed_light_multipliers(test_db):
    from backend.decision.harness import record_decision_run
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db, recommendation="可小仓试错", composite_score=42.0)
    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="600519",
        as_of="2026-05-22",
        result={
            "rule_version": "aggregate_v1:new_framework",
            "recommendation": "可小仓试错",
            "confidence": "中",
            "composite_score": 42.0,
            "position_pct": 0.10,
            "stop_loss": 10.0,
            "take_profit": 14.0,
        },
    )

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload(stance="支持"))):
        card = generate_symbol_copilot("600519", test_db)

    assert card["official"]["position_pct"] == 0.10
    assert card["shadow_position_pct"] == 0.11


def test_copilot_ignores_deep_research_decision_for_official_context(test_db):
    from backend.decision.harness import record_decision_run
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db, recommendation="可小仓试错", composite_score=42.0)
    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="600519",
        as_of="2026-05-22",
        result={
            "rule_version": "aggregate_v1:new_framework",
            "recommendation": "可小仓试错",
            "confidence": "中",
            "composite_score": 42.0,
            "position_pct": 0.10,
            "stop_loss": 10.0,
            "take_profit": 14.0,
        },
    )
    record_decision_run(
        test_db,
        run_type="deep_research",
        symbol="600519",
        as_of="2026-05-22",
        result={
            "rule_version": "deep_research_v1",
            "recommendation": "深研偏多",
            "confidence": "高",
            "composite_score": 92.0,
            "position_pct": 0.30,
            "stop_loss": 8.0,
            "take_profit": 18.0,
        },
    )

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload(stance="支持"))):
        card = generate_symbol_copilot("600519", test_db)

    assert card["official"]["rule_version"] == "aggregate_v1:new_framework"
    assert card["official"]["position_pct"] == 0.10
    assert card["shadow_position_pct"] == 0.11


def test_risk_veto_can_have_nonzero_shadow_position_but_marks_conflict(test_db):
    from backend.decision.harness import record_decision_run
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db, recommendation="观望", composite_score=32.0)
    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="600519",
        as_of="2026-05-22",
        result={
            "rule_version": "aggregate_v1:new_framework",
            "recommendation": "观望",
            "confidence": "中",
            "composite_score": 32.0,
            "position_pct": 0.0,
            "veto_reason": "大盘 RSRS 极度看空，拒绝建仓",
            "stop_loss": 10.0,
            "take_profit": 14.0,
        },
    )

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload(stance="支持"))):
        card = generate_symbol_copilot("600519", test_db)

    assert card["shadow_position_pct"] > 0
    assert card["risk_conflict"] is True


def test_exit_or_avoid_recommendations_force_zero_shadow_position(test_db):
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db, recommendation="规避", composite_score=-40.0)

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload(stance="支持"))):
        card = generate_symbol_copilot("600519", test_db)

    assert card["shadow_position_pct"] == 0.0
    assert "规避" in card["position_note"]


def test_stock_context_exposes_persisted_copilot_for_pi_shell(test_db, sample_stocks):
    from backend.agent.context import mingcang_stock_context

    _signal(test_db, symbol="300308", recommendation="观望", composite_score=31)
    test_db.add(ResearchState(
        symbol="300308",
        risks_json="[]",
        open_questions_json="[]",
        copilot_json=json.dumps({
            "stance": "谨慎",
            "summary_opinion": "影子试错但不覆盖官方观望",
            "shadow_position_pct": 0.03,
            "risk_conflict": True,
            "official": {"recommendation": "观望", "composite_score": 31},
        }, ensure_ascii=False),
    ))
    test_db.commit()

    context = mingcang_stock_context(test_db, "300308")

    assert context["copilot"]["stance"] == "谨慎"
    assert context["copilot"]["shadow_position_pct"] == 0.03
    assert context["copilot"]["risk_conflict"] is True


def test_chat_context_answer_presents_official_and_copilot_tracks(test_db, sample_stocks):
    from backend.api.routes.ai import _context_answer

    _signal(test_db, symbol="300308", recommendation="观望", composite_score=31)
    test_db.add(ResearchState(
        symbol="300308",
        risks_json="[]",
        open_questions_json="[]",
        copilot_json=json.dumps({
            "stance": "谨慎",
            "summary_opinion": "影子试错但不覆盖官方观望",
            "shadow_position_pct": 0.03,
            "risk_conflict": True,
            "official": {
                "recommendation": "观望",
                "composite_score": 31,
                "technical_score": 28,
                "sentiment_score": 35,
                "position_pct": 0.0,
            },
            "risks": ["大盘风控否决"],
            "validation_questions": ["量能能否维持？"],
        }, ensure_ascii=False),
    ))
    test_db.commit()

    response = _context_answer("帮我看一下 300308", test_db, session_id=None)

    assert "官方规则：" in response.answer
    assert "LLM 副驾驶：" in response.answer
    assert "影子仓位：3.0%" in response.answer
    assert "逆风控影子建议" in response.answer
    assert "research_copilot" in response.used_resources


def test_chat_context_answer_sanitizes_copilot_fields_for_ui(test_db, sample_stocks):
    from backend.api.routes.ai import _context_answer

    _signal(test_db, symbol="300308", recommendation="观望", composite_score=31)
    test_db.add(ResearchState(
        symbol="300308",
        risks_json="[]",
        open_questions_json="[]",
        copilot_json=json.dumps({
            "stance": "谨慎",
            "summary_opinion": "影子摘要 {\"report_path\":\"/private/tmp/copilot.json\"}",
            "shadow_position_pct": 0.03,
            "risk_conflict": False,
            "official": {"recommendation": "观望", "composite_score": 31},
            "risks": ["复核 /path/to/mingcang/risk.md"],
            "validation_questions": ["读取 report_path=/private/tmp/question.json"],
        }, ensure_ascii=False),
    ))
    test_db.commit()

    response = _context_answer("帮我看一下 300308", test_db, session_id=None)

    assert "LLM 副驾驶：" in response.answer
    assert "/private/tmp" not in response.answer
    assert "/Users/" not in response.answer
    assert "report_path" not in response.answer
    assert "{\"" not in response.answer


def test_copilot_card_carries_passing_vetter_review(test_db):
    """M15.1: a clean copilot card is run through the safety vetter."""
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db)

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(_llm_payload())):
        card = generate_symbol_copilot("600519", test_db)

    assert card["vetter"]["status"] == "pass"
    assert card["vetter"]["blocked_actions"] == []


def test_copilot_vetter_blocks_auto_trade_language_and_zeroes_shadow(test_db):
    """M15.1: auto-trade phrasing in the LLM output is blocked and shadow is zeroed."""
    from backend.research.copilot import generate_symbol_copilot

    _signal(test_db, recommendation="可关注", composite_score=20.0)
    payload = _llm_payload(summary_opinion="建议直接下单自动买入该股票。")

    with patch("backend.research.copilot.has_runtime_llm_provider", return_value=True), \
            patch("backend.research.copilot.get_provider", return_value=_provider(payload)):
        card = generate_symbol_copilot("600519", test_db)

    assert card["vetter"]["status"] == "block"
    assert "auto_trade" in card["vetter"]["blocked_actions"]
    assert card["shadow_position_pct"] == 0.0
    assert "安全审计阻断" in card["position_note"]
