"""
交易员 — 综合所有分析师 + 研究员输出，给出操作建议 + 仓位 + 止盈止损。

权重由 active_signal_weights() 决定：
测试1保留旧三路含 Qlib，测试2/生产使用新框架。
"""
from __future__ import annotations
from dataclasses import dataclass

from backend.agents.analyst import AnalystReport
from backend.agents.researcher import ResearcherConclusion
from backend.config import settings, active_signal_weights
from backend.analysis.factors import calc_stop_take
from backend.decision.signal_policy import score_to_recommendation


@dataclass
class TraderProposal:
    composite_score: float
    recommendation: str
    confidence: str
    stop_loss: float
    take_profit: float
    position_pct: float        # 建议仓位（占总资金）
    breakdown: dict
    reasoning: str


def _score_to_recommendation(score: float) -> str:
    """Delegate score to recommendation string via signal_policy."""
    return score_to_recommendation(score)


def _score_to_confidence(score: float) -> str:
    """Map absolute composite score to a confidence label string."""
    abs_score = abs(score)
    if abs_score >= 60:
        return "高"
    if abs_score >= 30:
        return "中"
    return "低"


def propose(
    reports: dict[str, AnalystReport],
    researcher: ResearcherConclusion,
    close: float,
    atr: float,
    portfolio_drawdown_pct: float = 0.0,
) -> TraderProposal:
    """
    reports: {"technical": .., "quant": .., "sentiment": .., "news": ..}
    """
    from backend.portfolio import suggest_position_pct  # 延迟导入避免循环

    tech = reports.get("technical")
    quant = reports.get("quant")
    sent = reports.get("sentiment")
    news = reports.get("news")

    sent_combined = (sent.score if sent else 0) * 0.5 + (news.score if news else 0) * 0.5
    weights = active_signal_weights()
    composite = (
        (quant.score if quant else 0) * weights.quant
        + (tech.score if tech else 0) * weights.technical
        + sent_combined * weights.sentiment
    )

    # 研究员偏向对综合分做小幅调整（±10%）
    if researcher.action_bias == "偏空":
        composite *= 0.9
    elif researcher.action_bias == "偏多":
        composite *= 1.05

    composite = round(max(-100, min(100, composite)), 1)

    recommendation = _score_to_recommendation(composite)
    confidence = _score_to_confidence(composite)
    stop_loss, take_profit = calc_stop_take(
        close, atr,
        atr_mult=settings.atr_multiplier,
        rr=settings.risk_reward_ratio,
    )
    position_pct = suggest_position_pct(composite, confidence, portfolio_drawdown_pct)

    reasoning = (
        f"四路得分 [tech={tech.score if tech else 0:.0f} "
        f"quant={quant.score if quant else 0:.0f} "
        f"sent={sent.score if sent else 0:.0f} "
        f"news={news.score if news else 0:.0f}] "
        f"→ 综合 {composite:+.0f}（{researcher.action_bias}调节后，{weights.profile}）。"
    )

    breakdown = {
        "quant": quant.score if quant else 0,
        "technical": tech.score if tech else 0,
        "sentiment": sent.score if sent else 0,
        "news": news.score if news else 0,
        "signal_profile": weights.profile,
    }

    return TraderProposal(
        composite_score=composite,
        recommendation=recommendation,
        confidence=confidence,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_pct=round(position_pct, 4),
        breakdown=breakdown,
        reasoning=reasoning,
    )
