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

from backend.agents.long_term.base import LongTermReport, VoteLabel
from backend.config import settings
from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.data.fundamentals import compute_piotroski_factors
from backend.memory.bias_override import lookup_caveat

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


def _score_to_label_vote(normalized_score: float) -> VoteLabel:
    """Map normalized F-score ratio to a label vote string."""
    if normalized_score >= settings.piotroski_strong_threshold / 9:
        return "值得持有"
    if normalized_score <= settings.piotroski_weak_threshold / 9:
        return "规避"
    return "观望"


def _score_to_signal_score(normalized_score: float) -> float:
    """0-1 映射到 -100 ~ +100（中位 0.5 = 0）"""
    return round((normalized_score - 0.5) / 0.5 * 100, 1)


def _score_summary(score: int, denominator: int) -> str:
    summary = f"Piotroski F-Score {score}/{denominator}"
    if denominator < 9:
        summary += " (股本历史缺失,N/A 因子已从分母剔除)"
    return summary


def _template_findings(factors: dict[str, bool | None], raw: dict) -> list[str]:
    """无 LLM 时的模板化 key_findings（≤3 条）"""
    positive = [_FACTOR_LABELS[k] for k, v in factors.items() if v and k in _FACTOR_LABELS]
    negative = [_FACTOR_LABELS[k] for k, v in factors.items() if v is False and k in _FACTOR_LABELS]
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
    context_text = render_context_text(
        build_stock_context_pack(symbol, sections=["financials", "holders"], db=db),
        1800,
    )
    if not settings.long_term_piotroski_enabled:
        return LongTermReport(
            role="quality", score=0, confidence=0,
            label_vote="观望", key_findings=["Piotroski 分析师已禁用"],
            raw={"context_text": context_text},
        )

    result = compute_piotroski_factors(symbol, db)
    if not result.get("available"):
        result["context_text"] = context_text
        return LongTermReport(
            role="quality", score=0, confidence=0,
            label_vote="观望",
            key_findings=[f"财务数据不足: {result.get('reason', 'unknown')}"],
            raw=result,
        )

    score = result["score"]
    denominator_value = result.get("score_denominator", 9)
    denominator = int(denominator_value) if denominator_value is not None else 0
    if denominator <= 0:
        result["context_text"] = context_text
        return LongTermReport(
            role="quality", score=0, confidence=0,
            label_vote="观望",
            key_findings=["财务数据不足: Piotroski 可用因子分母为 0"],
            raw=result,
        )
    normalized_score = score / denominator
    factors = result["factors"]
    raw = result.get("raw", {})

    label_vote = _score_to_label_vote(normalized_score)
    signal_score = _score_to_signal_score(normalized_score)
    confidence = abs(signal_score) / 100
    findings = ([_score_summary(score, denominator)] + _template_findings(factors, raw))[:3]

    # 边缘 5-6 分时可触发 LLM 生成更精炼解释（v1 先用模板）
    # TODO: 上线后若发现模板 findings 质量不够，再接入 LLM

    logger.info("piotroski %s: F=%d/%d → %s", symbol, score, denominator, label_vote)

    raw_payload = {
        "f_score": score,
        "score_denominator": denominator,
        "factors": factors,
        "report_period": result.get("report_period"),
        "comparison_period": result.get("comparison_period"),
        "context_text": context_text,
    }

    # M9.横向 反偏差缓冲：查 ai_memory(scope=bias_override) 是否有针对本路投票
    # 的 caveat；有则注入到 key_findings 第 0 位（保证 team._merge_findings
    # 的 [:2] 截断不会丢），并写入 raw["bias_caveat"] 供决策链消费。
    # 不覆盖 label_vote — 让 LLM 自己看到原始投票 + 提示后判断。
    caveat = lookup_caveat(db, "piotroski", label_vote)
    if caveat:
        findings = ([f"⚠️ 偏差提示: {caveat}"] + findings)[:3]
        raw_payload["bias_caveat"] = caveat

    return LongTermReport(
        role="quality",
        score=signal_score,
        confidence=round(confidence, 2),
        label_vote=label_vote,
        key_findings=findings,
        raw=raw_payload,
    )
