"""
Piotroski F-Score 财务质量分析师（算法主导）

9 因子打分（盈利能力 4 + 杠杆流动性 3 + 经营效率 2）：
  • ROA > 0
  • CFO > 0
  • ROA ↑
  • CFO > NI（盈利质量过滤）
  • 长期负债率 ↓
  • 流动比率 ↑
  • 总股本无增（防摊薄）
  • 毛利率 ↑
  • 资产周转率 ↑

Score → Vote 映射（settings 可调）：
  • ≥ piotroski_strong_threshold (7)  → 值得持有
  • ≤ piotroski_weak_threshold (4)    → 规避
  • 中间                              → 观望（可触发 LLM 解释 key_findings）
"""
from __future__ import annotations
import logging

from backend.agents.long_term.base import LongTermReport
from backend.config import settings
from backend.data.fundamentals import compute_piotroski_factors

logger = logging.getLogger(__name__)


_FACTOR_LABELS = {
    "roa_positive": "ROA为正",
    "cfo_positive": "经营现金流为正",
    "roa_improving": "ROA提升",
    "cfo_gt_ni": "现金流>净利润（盈利质量好）",
    "leverage_decreasing": "长期负债率下降",
    "current_ratio_improving": "流动比率提升",
    "no_new_shares": "总股本未稀释",
    "gross_margin_improving": "毛利率提升",
    "asset_turnover_improving": "资产周转率提升",
}


def _score_to_label_vote(score: int) -> str:
    """Map F-score integer to a label vote string."""
    if score >= settings.piotroski_strong_threshold:
        return "值得持有"
    if score <= settings.piotroski_weak_threshold:
        return "规避"
    return "观望"


def _score_to_signal_score(score: int) -> float:
    """0-9 映射到 -100 ~ +100（中位 4.5 = 0）"""
    return round((score - 4.5) / 4.5 * 100, 1)


def _template_findings(factors: dict[str, bool], raw: dict) -> list[str]:
    """无 LLM 时的模板化 key_findings（≤3 条）"""
    positive = [_FACTOR_LABELS[k] for k, v in factors.items() if v and k in _FACTOR_LABELS]
    negative = [_FACTOR_LABELS[k] for k, v in factors.items() if not v and k in _FACTOR_LABELS]
    findings = []
    if positive:
        findings.append("✅ " + "; ".join(positive[:3]))
    if negative:
        findings.append("⚠️ 未达: " + "; ".join(negative[:3]))
    roa = raw.get("roa_cur")
    if roa is not None:
        findings.append(f"当期 ROA={roa*100:.2f}%")
    return findings[:3]


def analyze(symbol: str, db) -> LongTermReport:
    """主入口"""
    if not settings.long_term_piotroski_enabled:
        return LongTermReport(
            role="quality", score=0, confidence=0,
            label_vote="观望", key_findings=["Piotroski 分析师已禁用"],
        )

    result = compute_piotroski_factors(symbol, db)
    if not result.get("available"):
        return LongTermReport(
            role="quality", score=0, confidence=0,
            label_vote="观望",
            key_findings=[f"财务数据不足: {result.get('reason', 'unknown')}"],
            raw=result,
        )

    score = result["score"]               # 0-9
    factors = result["factors"]
    raw = result.get("raw", {})

    label_vote = _score_to_label_vote(score)
    signal_score = _score_to_signal_score(score)
    confidence = abs(signal_score) / 100
    findings = _template_findings(factors, raw)

    # 边缘 5-6 分时可触发 LLM 生成更精炼解释（v1 先用模板）
    # TODO: 上线后若发现模板 findings 质量不够，再接入 LLM

    logger.info("piotroski %s: F=%d/9 → %s", symbol, score, label_vote)
    return LongTermReport(
        role="quality",
        score=signal_score,
        confidence=round(confidence, 2),
        label_vote=label_vote,
        key_findings=findings,
        raw={
            "f_score": score,
            "factors": factors,
            "report_period": result.get("report_period"),
            "comparison_period": result.get("comparison_period"),
        },
    )
