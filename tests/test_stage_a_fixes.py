import math

import pandas as pd


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


def test_position_sizer_preserves_caps_for_small_candidate_sets():
    from backend.portfolio.combo_weights import equal_weight, size_positions

    assert equal_weight(1, max_per=0.2) == [0.2]
    assert equal_weight(2, max_per=0.2) == [0.2, 0.2]
    sized = size_positions([{"sym": "a"}, {"sym": "b"}, {"sym": "c"}], max_per=0.15)
    assert [x["weight"] for x in sized] == [0.15, 0.15, 0.15]


def test_risk_manager_downgrades_strong_buy_without_long_term_label():
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
    assert decision.final_recommendation == "可关注"
    assert any("长期标签缺失" in note for note in decision.risk_notes)


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
