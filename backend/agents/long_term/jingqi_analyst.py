"""
景气投资 jingqi 分析师（算法主导，A股专属）

参考：开源证券《景气投资方法论》(2026.1) 7×34 框架
核心结论：Δ 类指标（边际变化）对股价正向指引最强：
  Δ 利润增速 > Δ 收入增速 > Δ ROE > 收入增速 > 盈利增速

Score 公式：
  base = 0.4 × pctile_dnp + 0.3 × pctile_drev + 0.3 × pctile_droe   # 0~1（行业内分位）
  score = (base - 0.5) × 200    # -100 ~ +100
  if Δ利润增速从负转正: score += 20
  if base > 0.7: score = max(score, 50)

Vote 映射：
  ≥ 40 且 base > 0.7  → 值得持有
  0 ~ 40              → 观望
  -40 ~ 0             → 估值偏高
  < -40 或 base < 0.2 → 规避

无同行业 peers 数据时（首批只有 10 只股，多数行业可能没有 peers），
按 Δ 绝对值阈值兜底打分。
"""
from __future__ import annotations
import logging

from backend.agents.long_term.base import LongTermReport
from backend.config import settings
from backend.data.fundamentals import compute_jingqi_deltas, list_peers

logger = logging.getLogger(__name__)


def _score_no_peers(deltas: dict) -> float:
    """无行业 peers 时按 Δ 绝对值阈值兜底"""
    dnp = deltas.get("delta_net_profit_yoy")
    drev = deltas.get("delta_revenue_yoy")
    droe = deltas.get("delta_roe")
    score = 0
    n = 0
    # 利润 Δ
    if dnp is not None:
        score += max(-50, min(50, dnp))   # ±50% 截断
        n += 1
    # 收入 Δ
    if drev is not None:
        score += max(-30, min(30, drev * 0.6))
        n += 1
    # ROE Δ
    if droe is not None:
        score += max(-20, min(20, droe * 5))
        n += 1
    return score / max(n, 1)


def _score_with_peers(deltas: dict, pctile: dict) -> float:
    """有 peers 时按行业分位评分"""
    weights = {"delta_net_profit_yoy": 0.4, "delta_revenue_yoy": 0.3, "delta_roe": 0.3}
    base = 0.0
    total_w = 0.0
    for k, w in weights.items():
        p = pctile.get(k)
        if p is not None:
            base += p * w
            total_w += w
    if total_w == 0:
        return _score_no_peers(deltas)
    base = base / total_w
    score = (base - 0.5) * 200
    return score


def _apply_bonuses(score: float, deltas: dict) -> float:
    """转折奖励 + 强景气区下限"""
    transitions = deltas.get("transitions", {})
    if transitions.get("profit_negative_to_positive"):
        score += 20
    if transitions.get("revenue_negative_to_positive"):
        score += 10
    return round(max(-100, min(100, score)), 1)


def _score_to_label_vote(score: float, deltas: dict, pctile: dict) -> str:
    """Map composite score and percentile to a label vote string."""
    base_signals = [p for p in pctile.values() if p is not None]
    avg_pctile = sum(base_signals) / len(base_signals) if base_signals else None

    if score >= 40 and avg_pctile is not None and avg_pctile > settings.jingqi_strong_pctile:
        return "值得持有"
    if score >= 40:
        return "值得持有"
    if score < -40 or (avg_pctile is not None and avg_pctile < settings.jingqi_weak_pctile):
        return "规避"
    if score < 0:
        return "估值偏高"
    return "观望"


def _build_findings(deltas: dict, pctile: dict, score: float) -> list[str]:
    """Build key findings list from delta and percentile data."""
    findings = []
    dnp = deltas.get("delta_net_profit_yoy")
    drev = deltas.get("delta_revenue_yoy")
    droe = deltas.get("delta_roe")

    if dnp is not None:
        p = pctile.get("delta_net_profit_yoy")
        ptxt = f"，行业分位 {p*100:.0f}%" if p is not None else ""
        findings.append(f"Δ 净利润增速 {dnp:+.1f}pp{ptxt}")
    if drev is not None:
        findings.append(f"Δ 营收增速 {drev:+.1f}pp")
    if droe is not None:
        findings.append(f"Δ ROE {droe:+.2f}pp")

    transitions = deltas.get("transitions", {})
    if transitions.get("profit_negative_to_positive"):
        findings.insert(0, "🔥 利润增速从负转正（景气拐点）")
    elif transitions.get("revenue_negative_to_positive"):
        findings.insert(0, "📈 收入增速从负转正")

    return findings[:3]


def analyze(symbol: str, db) -> LongTermReport:
    """Run jingqi (boom) long-term analysis for a symbol."""
    if not settings.long_term_jingqi_enabled:
        return LongTermReport(
            role="boom", score=0, confidence=0,
            label_vote="观望", key_findings=["景气分析师已禁用"],
        )

    peers = list_peers(symbol, db)
    deltas = compute_jingqi_deltas(symbol, db, peers=peers)

    if not deltas.get("available"):
        return LongTermReport(
            role="boom", score=0, confidence=0,
            label_vote="观望",
            key_findings=[f"财报数据不足: {deltas.get('reason', 'unknown')}"],
            raw=deltas,
        )

    pctile = deltas.get("industry_pctile", {})
    raw_score = _score_with_peers(deltas, pctile) if peers else _score_no_peers(deltas)
    score = _apply_bonuses(raw_score, deltas)

    label_vote = _score_to_label_vote(score, deltas, pctile)
    findings = _build_findings(deltas, pctile, score)
    confidence = min(1.0, abs(score) / 60)

    logger.info("jingqi %s: score=%.1f → %s (peers=%d)", symbol, score, label_vote, len(peers))
    return LongTermReport(
        role="boom",
        score=score,
        confidence=round(confidence, 2),
        label_vote=label_vote,
        key_findings=findings,
        raw={
            "deltas": {k: deltas[k] for k in ("delta_net_profit_yoy", "delta_revenue_yoy", "delta_roe")
                       if k in deltas},
            "pctile": pctile,
            "transitions": deltas.get("transitions"),
            "report_period": deltas.get("report_period"),
            "peers_count": len(peers),
        },
    )
