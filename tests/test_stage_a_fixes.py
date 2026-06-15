import math

import pandas as pd
import pytest


def test_calc_rsi_single_direction_and_flat_are_finite():
    from backend.analysis.factors import calc_rsi

    up = calc_rsi(pd.Series([1, 2, 3, 4, 5]))
    down = calc_rsi(pd.Series([5, 4, 3, 2, 1]))
    flat = calc_rsi(pd.Series([3, 3, 3, 3, 3]))

    assert up.iloc[-1] == 100.0
    assert down.iloc[-1] == 0.0
    assert flat.iloc[-1] == 50.0
    assert up.map(math.isfinite).all()
    assert down.map(math.isfinite).all()
    assert flat.map(math.isfinite).all()


def test_aggregate_non_finite_composite_falls_back_to_neutral(monkeypatch):
    from backend.decision import aggregator

    monkeypatch.setattr(aggregator.settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(aggregator.settings, "weight_quant", float("nan"))
    result = aggregator.aggregate(
        quant_score=10,
        technical_result={"score": 20, "limit": {}},
        sentiment_score=0.1,
        close=10,
        atr=1,
    )

    assert result["composite_score"] == 0.0
    assert result["recommendation"] == "观望"


def test_default_aggregate_shows_long_term_avoid_label_without_enforcement(monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.decision import aggregator

    monkeypatch.setattr(aggregator.settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(aggregator.settings, "weight_quant", 0.0)
    monkeypatch.setattr(aggregator.settings, "weight_technical", 0.6)
    monkeypatch.setattr(aggregator.settings, "weight_sentiment", 0.4)
    monkeypatch.setattr(aggregator.settings, "long_term_team_enabled", True)
    monkeypatch.setattr(aggregator.settings, "long_term_constraints_enabled", False)

    label = LongTermLabel(
        symbol="300308",
        date="2026-05-25",
        label="规避",
        score=-60,
        votes={"track": "规避"},
        key_findings=["基本面风险未解除"],
        expires_at="2026-06-04",
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    )
    result = aggregator.aggregate(
        quant_score=0,
        technical_result={"score": 80, "limit": {}},
        sentiment_score=0.8,
        close=10,
        atr=1,
        long_term_label=label,
    )

    assert result["recommendation"] == "可小仓试错"
    assert result["position_pct"] > 0.0
    assert any("验证模式" in note for note in result["risk_notes"])
    assert any(c["type"] == "long_term_label" for c in result["research_constraints"])
    assert result["research_conflicts"] == []


def test_default_aggregate_respects_long_term_avoid_label_when_enforced(monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.decision import aggregator

    monkeypatch.setattr(aggregator.settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(aggregator.settings, "weight_quant", 0.0)
    monkeypatch.setattr(aggregator.settings, "weight_technical", 0.6)
    monkeypatch.setattr(aggregator.settings, "weight_sentiment", 0.4)
    monkeypatch.setattr(aggregator.settings, "long_term_team_enabled", True)
    monkeypatch.setattr(aggregator.settings, "long_term_constraints_enabled", True)

    label = LongTermLabel(
        symbol="300308",
        date="2026-05-25",
        label="规避",
        score=-60,
        votes={"track": "规避"},
        key_findings=["基本面风险未解除"],
        expires_at="2026-06-04",
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    )
    result = aggregator.aggregate(
        quant_score=0,
        technical_result={"score": 80, "limit": {}},
        sentiment_score=0.8,
        close=10,
        atr=1,
        long_term_label=label,
    )

    assert result["recommendation"] == "观望"
    assert result["position_pct"] == 0.0
    assert any("规避" in note for note in result["risk_notes"])
    assert result["research_conflicts"]


def test_default_aggregate_ignores_untrusted_long_term_avoid_label(monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.decision import aggregator

    monkeypatch.setattr(aggregator.settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(aggregator.settings, "weight_quant", 0.0)
    monkeypatch.setattr(aggregator.settings, "weight_technical", 0.6)
    monkeypatch.setattr(aggregator.settings, "weight_sentiment", 0.4)
    monkeypatch.setattr(aggregator.settings, "long_term_team_enabled", True)

    label = LongTermLabel(
        symbol="300308",
        date="2026-05-25",
        label="规避",
        score=-60,
        votes={"track": "规避"},
        key_findings=["LLM 调用失败，默认观望"],
        expires_at="2026-06-04",
        quality="failed",
        constraint_eligible=False,
        quality_notes=["赛道研究员 LLM 调用失败"],
    )
    result = aggregator.aggregate(
        quant_score=0,
        technical_result={"score": 80, "limit": {}},
        sentiment_score=0.8,
        close=10,
        atr=1,
        long_term_label=label,
    )

    assert result["recommendation"] == "可小仓试错"
    assert result["position_pct"] > 0.0
    assert any("未通过质量门" in note for note in result["risk_notes"])


@pytest.mark.parametrize("enforcement_enabled", [False, True])
def test_research_constraints_do_not_block_entry_for_failed_long_term_label(monkeypatch, enforcement_enabled):
    from backend.decision import research_constraints

    monkeypatch.setattr(research_constraints.settings, "long_term_team_enabled", True)
    monkeypatch.setattr(research_constraints.settings, "long_term_constraints_enabled", enforcement_enabled)
    failed_label = {
        "label": "规避",
        "key_findings": ["LLM 调用失败，默认观望"],
        "quality": "failed",
        "constraint_eligible": False,
        "quality_notes": ["赛道研究员 LLM 调用失败"],
    }

    result = research_constraints.apply_research_constraints(
        recommendation="可小仓试错",
        composite_score=66.0,
        position_pct=0.12,
        long_term_label=failed_label,
    )

    assert result.recommendation == "可小仓试错"
    assert result.position_pct == 0.12
    assert result.conflicts == []
    assert any("仅展示不约束" in note for note in result.risk_notes)


def test_default_aggregate_does_not_downgrade_entry_when_long_term_missing(monkeypatch):
    from backend.decision import aggregator

    monkeypatch.setattr(aggregator.settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(aggregator.settings, "weight_quant", 0.0)
    monkeypatch.setattr(aggregator.settings, "weight_technical", 0.6)
    monkeypatch.setattr(aggregator.settings, "weight_sentiment", 0.4)
    monkeypatch.setattr(aggregator.settings, "long_term_team_enabled", True)

    result = aggregator.aggregate(
        quant_score=0,
        technical_result={"score": 80, "limit": {}},
        sentiment_score=0.8,
        close=10,
        atr=1,
        long_term_label=None,
    )

    assert result["recommendation"] == "可小仓试错"
    assert result["position_pct"] > 0.0
    assert not any("长期标签缺失" in note for note in result["risk_notes"])


def test_default_aggregate_surfaces_memory_constraints(monkeypatch):
    from backend.decision import aggregator

    monkeypatch.setattr(aggregator.settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(aggregator.settings, "weight_quant", 0.0)
    monkeypatch.setattr(aggregator.settings, "weight_technical", 0.6)
    monkeypatch.setattr(aggregator.settings, "weight_sentiment", 0.4)
    monkeypatch.setattr(aggregator.settings, "long_term_team_enabled", False)

    result = aggregator.aggregate(
        quant_score=0,
        technical_result={"score": 80, "limit": {}},
        sentiment_score=0.8,
        close=10,
        atr=1,
        memory_context={"text": "【300308 股票长期记忆】\n- [risk|重要5|watching] 海外订单兑现风险"},
    )

    assert result["recommendation"] == "可小仓试错"
    assert any(c["type"] == "risk" for c in result["research_constraints"])
    assert any(c["type"] == "memory_risk" for c in result["research_conflicts"])


def test_position_sizer_preserves_caps_for_small_candidate_sets():
    from backend.portfolio.combo_weights import equal_weight, size_positions

    assert equal_weight(1, max_per=0.2) == [0.2]
    assert equal_weight(2, max_per=0.2) == [0.2, 0.2]
    sized = size_positions([{"sym": "a"}, {"sym": "b"}, {"sym": "c"}], max_per=0.15)
    assert [x["weight"] for x in sized] == [0.15, 0.15, 0.15]


def test_risk_manager_does_not_downgrade_strong_buy_without_long_term_label():
    from backend.agents.risk_manager import review
    from backend.agents.trader import TraderProposal

    proposal = TraderProposal(
        composite_score=70,
        recommendation="强买",
        confidence="高",
        stop_loss=9,
        take_profit=12,
        position_pct=0.2,
        breakdown={},
        reasoning="test",
    )

    decision = review(proposal, regime=None, long_term_label=None)
    assert decision.final_recommendation == "强买"
    assert not any("长期标签缺失" in note for note in decision.risk_notes)


def test_risk_manager_shows_long_term_label_without_enforcement(monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.agents.risk_manager import review
    from backend.agents.trader import TraderProposal

    monkeypatch.setattr("backend.agents.risk_manager.settings.long_term_team_enabled", True)
    monkeypatch.setattr("backend.agents.risk_manager.settings.long_term_constraints_enabled", False)

    proposal = TraderProposal(
        composite_score=70,
        recommendation="强买",
        confidence="高",
        stop_loss=9,
        take_profit=12,
        position_pct=0.2,
        breakdown={},
        reasoning="test",
    )
    label = LongTermLabel(
        symbol="300308",
        date="2026-05-25",
        label="规避",
        score=-60,
        votes={"track": "规避"},
        key_findings=["基本面风险未解除"],
        expires_at="2026-06-04",
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    )

    decision = review(proposal, regime=None, long_term_label=label)

    assert decision.final_recommendation == "强买"
    assert decision.veto_reason is None
    assert decision.adjusted_position_pct == 0.2
    assert any("验证模式" in note for note in decision.risk_notes)


def test_risk_manager_enforces_long_term_label_when_enabled(monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.agents.risk_manager import review
    from backend.agents.trader import TraderProposal

    monkeypatch.setattr("backend.agents.risk_manager.settings.long_term_team_enabled", True)
    monkeypatch.setattr("backend.agents.risk_manager.settings.long_term_constraints_enabled", True)

    proposal = TraderProposal(
        composite_score=70,
        recommendation="强买",
        confidence="高",
        stop_loss=9,
        take_profit=12,
        position_pct=0.2,
        breakdown={},
        reasoning="test",
    )
    label = LongTermLabel(
        symbol="300308",
        date="2026-05-25",
        label="规避",
        score=-60,
        votes={"track": "规避"},
        key_findings=["基本面风险未解除"],
        expires_at="2026-06-04",
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    )

    decision = review(proposal, regime=None, long_term_label=label)

    assert decision.final_recommendation == "观望"
    assert decision.veto_reason and "规避" in decision.veto_reason
    assert decision.adjusted_position_pct == 0.0


def test_aggregate_v2_regime_dampening_preserves_risk_manager_decision(monkeypatch):
    from backend.analysis.timing.regime import RegimeReport
    from backend.decision.aggregator import aggregate_v2

    monkeypatch.setattr("backend.config.settings.regime_filter_enabled", True)
    monkeypatch.setattr("backend.config.settings.risk_manager_enabled", True)
    monkeypatch.setattr("backend.config.settings.multi_round_debate_enabled", False)
    monkeypatch.setattr("backend.config.settings.long_term_team_enabled", False)
    monkeypatch.setattr("backend.config.settings.position_sizing_enabled", True)

    technical_result = {
        "score": 75,
        "raw_score": 75,
        "latest": {"rsi14": 58, "close": 10.0, "atr14": 0.3},
        "limit": {},
    }
    quant_result = {"score": 75, "model": "lgbm"}
    sentiment_result = {
        "sentiment": 0.75,
        "key_events": ["公司中标大额订单"],
        "summary": "利好",
        "impact": "short",
    }

    veto_regime = RegimeReport(
        rsrs_z=-1.5,
        diffusion=0.5,
        market_bullish=False,
        market_bearish=True,
        sector_strong=False,
        sector_weak=False,
        dampen_score=True,
        reason="RSRS看空",
    )
    veto_result = aggregate_v2(
        quant_result=quant_result,
        technical_result=technical_result,
        sentiment_result=sentiment_result,
        close=10.0,
        atr=0.3,
        regime=veto_regime,
        long_term_label=None,
    )
    assert veto_result.get("veto_reason")
    assert veto_result["recommendation"] == "观望"
    assert veto_result["position_pct"] == 0.0

    weak_sector_regime = RegimeReport(
        rsrs_z=-0.5,
        diffusion=0.15,
        market_bullish=False,
        market_bearish=False,
        sector_strong=False,
        sector_weak=True,
        dampen_score=True,
        reason="板块扩散弱",
    )
    weak_sector_result = aggregate_v2(
        quant_result=quant_result,
        technical_result=technical_result,
        sentiment_result=sentiment_result,
        close=10.0,
        atr=0.3,
        regime=weak_sector_regime,
        long_term_label=None,
    )
    assert weak_sector_result["recommendation"] == "可关注"
    assert weak_sector_result.get("position_pct", 0) < 0.15
