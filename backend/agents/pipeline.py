"""
多 Agent 决策流水线编排器

调用顺序（M4.2 起）：
  Analysts (并行 4 路) → Director (评估质量+下达议题) → Researcher (分歧时辩论)
  → Trader → RiskManager
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.agents.analyst import (
    AnalystReport,
    news_analyst,
    quant_analyst,
    sentiment_analyst,
    technical_analyst,
)
from backend.agents.director import DirectorAssessment, assess, assessment_to_dict
from backend.agents.researcher import debate, has_divergence, quick_consensus
from backend.agents.risk_manager import RiskDecision, review
from backend.agents.trader import TraderProposal, propose
from backend.analysis.timing.regime import RegimeReport
from backend.config import settings


def _step_record(
    name: str,
    elapsed_ms: float,
    *,
    used_llm: bool = False,
    structured_output_valid: bool | None = None,
    fallback_reason: str | None = None,
    extra: dict | None = None,
) -> dict:
    """构造单个 step 的 span 记录。"""
    record = {
        "step_name": name,
        "duration_ms": round(elapsed_ms, 3),
        "used_llm": used_llm,
        "structured_output_valid": structured_output_valid,
        "fallback_reason": fallback_reason,
    }
    if extra:
        record.update(extra)
    return record


@dataclass
class AgentDecision:
    composite_score: float
    recommendation: str
    confidence: str
    stop_loss: float
    take_profit: float
    position_pct: float
    breakdown: dict
    analysts: dict           # role → AnalystReport.to_dict()
    director: dict           # DirectorAssessment fields (M4.2)
    researcher: dict         # ResearcherConclusion fields
    risk: dict               # RiskDecision fields
    regime: dict | None
    reasoning: str
    trader_position_pct: float | None = None
    risk_position_pct: float | None = None
    decision_trace: list[dict] = field(default_factory=list)  # step span 记录

    def to_signal_dict(self) -> dict:
        """转回 aggregator 兼容格式（用于写 Signal 表）"""
        arbitration = {
            "bull_points": self.researcher.get("bull_points", []),
            "bear_points": self.researcher.get("bear_points", []),
            "action_bias": self.researcher.get("action_bias", "中性"),
            "rationale": self.researcher.get("rationale", ""),
            "used_llm": bool(self.researcher.get("used_llm")),
            "round_count": len(self.researcher.get("rounds") or []),
            "fallback_reason": self.researcher.get("fallback_reason"),
            "structured_output_valid": self.researcher.get("structured_output_valid"),
        }
        # M4.1 透传多轮辩论记录
        if self.researcher.get("rounds"):
            arbitration["rounds"] = self.researcher["rounds"]
        return {
            "composite_score": self.composite_score,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "breakdown": self.breakdown,
            "position_pct": self.position_pct,
            "trader_position_pct": self.trader_position_pct,
            "risk_position_pct": self.risk_position_pct,
            "limit_status": self.risk.get("limit_status", "normal"),
            "llm_arbitration": arbitration,
            "director": self.director,
            "risk_notes": self.risk.get("risk_notes", []),
            "veto_reason": self.risk.get("veto_reason"),
            "regime": self.regime,
            "stop_loss_executable": self.risk.get("stop_loss_executable", True),
            "decision_trace": self.decision_trace,
        }


def run_pipeline(
    technical_result: dict,
    qlib_result: dict,
    sentiment_result: dict,
    close: float,
    atr: float,
    regime: RegimeReport | None = None,
    llm_arbitration: dict | None = None,
    portfolio_drawdown_pct: float = 0.0,
    limit_status: dict | None = None,
    long_term_label=None,                 # LongTermLabel | None
) -> AgentDecision:
    """
    主入口。调用方（aggregator）需准备：
      • technical_result: technical_score() 返回值
      • qlib_result:      qlib_score() 返回值
      • sentiment_result: analyze_news() 返回值
      • regime:           market_regime() 返回值（可选，None 则跳过 RM 的 regime 检查）
      • llm_arbitration:  分歧时 _bull_bear_debate() 返回值（可选）
    """
    trace: list[dict] = []

    # 1. Analysts
    t0 = time.perf_counter()
    reports: dict[str, AnalystReport] = {
        "technical": technical_analyst(technical_result),
        "quant": quant_analyst(qlib_result),
        "sentiment": sentiment_analyst(sentiment_result),
        "news": news_analyst(sentiment_result),
    }
    report_list = list(reports.values())
    trace.append(_step_record(
        "analysts",
        (time.perf_counter() - t0) * 1000,
        extra={"report_count": len(report_list)},
    ))

    # 2. Research Director (M4.2): 评估质量+下达辩论议题
    t0 = time.perf_counter()
    if settings.research_director_enabled:
        director_assessment: DirectorAssessment = assess(report_list)
    else:
        director_assessment = assess([])   # 空评估，保证 dict 字段一致
    trace.append(_step_record(
        "director",
        (time.perf_counter() - t0) * 1000,
        extra={"enabled": settings.research_director_enabled},
    ))

    # 3. Researcher
    t0 = time.perf_counter()
    if has_divergence(report_list):
        researcher = debate(report_list, llm_arbitration)
    else:
        researcher = quick_consensus(report_list, fallback_reason="no_divergence")
    trace.append(_step_record(
        "researcher",
        (time.perf_counter() - t0) * 1000,
        used_llm=researcher.used_llm,
        structured_output_valid=researcher.structured_output_valid,
        fallback_reason=researcher.fallback_reason,
        extra={"round_count": len(researcher.rounds or [])},
    ))

    # 4. Trader
    t0 = time.perf_counter()
    proposal: TraderProposal = propose(
        reports, researcher,
        close=close, atr=atr,
        portfolio_drawdown_pct=portfolio_drawdown_pct,
    )

    # 4.5 长期"观望"标签 → 综合分硬截断到 watch_score_cap
    from backend.agents.trader import _score_to_recommendation
    if long_term_label is not None and long_term_label.label == "观望" \
            and settings.long_term_team_enabled:
        cap = settings.long_term_watch_score_cap
        if proposal.composite_score > cap:
            proposal.breakdown["long_term_cap"] = cap
            proposal.composite_score = cap
            proposal.recommendation = _score_to_recommendation(cap)
    trace.append(_step_record(
        "trader",
        (time.perf_counter() - t0) * 1000,
        extra={
            "composite_score": proposal.composite_score,
            "position_pct": proposal.position_pct,
        },
    ))

    # 5. Risk Manager
    t0 = time.perf_counter()
    risk: RiskDecision = review(
        proposal, regime, limit_status, portfolio_drawdown_pct,
        long_term_label=long_term_label,
    )
    trace.append(_step_record(
        "risk_manager",
        (time.perf_counter() - t0) * 1000,
        extra={
            "approved": risk.approved,
            "veto_reason": risk.veto_reason,
        },
    ))

    final_pos = risk.adjusted_position_pct
    final_rec = risk.final_recommendation

    reasoning = proposal.reasoning
    if risk.veto_reason:
        reasoning += f" 风控否决: {risk.veto_reason}。"
    if risk.risk_notes:
        reasoning += " 风控提示: " + "; ".join(risk.risk_notes)
    if director_assessment.quality_notes:
        reasoning += " Director: " + "; ".join(director_assessment.quality_notes[:2])

    return AgentDecision(
        composite_score=proposal.composite_score,
        recommendation=final_rec,
        confidence=proposal.confidence,
        stop_loss=proposal.stop_loss,
        take_profit=proposal.take_profit,
        position_pct=final_pos,
        breakdown=proposal.breakdown,
        analysts={k: v.to_dict() for k, v in reports.items()},
        director=assessment_to_dict(director_assessment),
        researcher={
            "bull_points": researcher.bull_points,
            "bear_points": researcher.bear_points,
            "action_bias": researcher.action_bias,
            "rationale": researcher.rationale,
            "used_llm": researcher.used_llm,
            "fallback_reason": researcher.fallback_reason,
            "structured_output_valid": researcher.structured_output_valid,
            "rounds": [
                {
                    "round_num": r.round_num,
                    "speaker": r.speaker,
                    "points": r.points,
                    "references": r.references,
                }
                for r in (researcher.rounds or [])
            ],
        },
        risk={
            "approved": risk.approved,
            "trader_position_pct": proposal.position_pct,
            "risk_position_pct": final_pos,
            "veto_reason": risk.veto_reason,
            "risk_notes": risk.risk_notes,
            "limit_status": (limit_status or {}).get("status", "normal"),
            "stop_loss_executable": (limit_status or {}).get("stop_loss_executable", True),
            "long_term": long_term_label.to_dict() if long_term_label else None,
        },
        regime=regime.to_dict() if regime else None,
        reasoning=reasoning,
        trader_position_pct=proposal.position_pct,
        risk_position_pct=final_pos,
        decision_trace=trace,
    )
