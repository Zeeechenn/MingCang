"""
长期分析师团聚合器

三路分析师 → 加权综合分 → 标签映射 → LongTermLabel

标签映射规则（一票否决 + 加权融合）：
  • 任一分析师投"规避" → label="规避"（一票否决）
  • score ≥ 50  → 值得持有
  • 30 ≤ score < 50（或 a_teacher 第五层⚠️）→ 估值偏高
  • -20 ≤ score < 30 → 观望
  • score < -20 → 规避
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta

from backend.agents.long_term.base import LongTermReport, LongTermLabel
from backend.agents.long_term import (
    piotroski_analyst,
    jingqi_analyst,
    a_teacher_analyst,
    qfii_flow_analyst,
)
from backend.config import settings

logger = logging.getLogger(__name__)


def _aggregate_score(reports: dict[str, LongTermReport]) -> float:
    """加权综合分（settings 中权重可配）

    flow（QFII Outflow 反向规避）权重小，主要靠一票否决发挥作用；
    其 confidence=0 时（未触发规避）会被本函数自动跳过，不稀释正向分。
    """
    weights = {
        "track": settings.long_term_a_teacher_weight,
        "quality": settings.long_term_piotroski_weight,
        "boom": settings.long_term_jingqi_weight,
        "flow": settings.long_term_qfii_flow_weight,
    }
    total = 0.0
    total_w = 0.0
    for role, w in weights.items():
        rep = reports.get(role)
        if rep is None or rep.confidence < 0.01:
            continue
        total += rep.score * w
        total_w += w
    if total_w == 0:
        return 0.0
    return round(total / total_w, 1)


def _resolve_label(score: float, votes: dict[str, str],
                   a_teacher_layer5: str | None = None) -> str:
    """根据综合分 + 一票否决 + a_teacher 高位 决定最终 label"""
    # 一票否决：任一分析师投"规避"
    if "规避" in votes.values():
        return "规避"

    # a_teacher 第五层"规避"或"等回调"硬约束
    if a_teacher_layer5 == "规避":
        return "规避"

    if score >= 50:
        # 但如果 a_teacher 第五层"等回调"，降级
        if a_teacher_layer5 == "等回调":
            return "估值偏高"
        return "值得持有"
    if score >= 30:
        return "估值偏高"
    if score >= -20:
        return "观望"
    return "规避"


def _merge_findings(reports: dict[str, LongTermReport]) -> list[str]:
    """合并各路 key_findings，每路最多 2 条，总共 ≤8 条"""
    merged: list[str] = []
    role_prefix = {
        "track": "[赛道]",
        "quality": "[质量]",
        "boom": "[景气]",
        "flow": "[外资流向]",
    }
    for role in ("track", "boom", "quality", "flow"):
        rep = reports.get(role)
        if rep is None:
            continue
        for f in rep.key_findings[:2]:
            merged.append(f"{role_prefix[role]} {f}")
    return merged[:8]


class LongTermTeam:
    """长期分析师团（封装三路分析师 + 聚合逻辑）"""

    def run(self, symbol: str, name: str, db) -> LongTermLabel:
        """Run all long-term analysts and aggregate into a LongTermLabel."""
        reports: dict[str, LongTermReport] = {}

        if settings.long_term_a_teacher_enabled:
            try:
                reports["track"] = a_teacher_analyst.analyze(symbol, name, db)
            except Exception as e:
                logger.error("a_teacher 失败 %s: %s", symbol, e)
        if settings.long_term_piotroski_enabled:
            try:
                reports["quality"] = piotroski_analyst.analyze(symbol, db)
            except Exception as e:
                logger.error("piotroski 失败 %s: %s", symbol, e)
        if settings.long_term_jingqi_enabled:
            try:
                reports["boom"] = jingqi_analyst.analyze(symbol, db)
            except Exception as e:
                logger.error("jingqi 失败 %s: %s", symbol, e)

        if settings.long_term_qfii_flow_enabled:
            try:
                reports["flow"] = qfii_flow_analyst.analyze(symbol, db)
            except Exception as e:
                logger.error("qfii_flow 失败 %s: %s", symbol, e)

        score = _aggregate_score(reports)
        votes = {r.role: r.label_vote for r in reports.values()}
        layer5 = None
        if "track" in reports:
            layer5 = reports["track"].raw.get("layers", {}).get("layer5_entry_timing")

        final_label = _resolve_label(score, votes, layer5)
        findings = _merge_findings(reports)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        expires = (datetime.utcnow() + timedelta(days=settings.long_term_label_ttl_days)) \
            .strftime("%Y-%m-%d")

        logger.info(
            "team %s: track=%s quality=%s boom=%s flow=%s → score=%.1f label=%s",
            symbol,
            votes.get("track", "N/A"), votes.get("quality", "N/A"),
            votes.get("boom", "N/A"), votes.get("flow", "N/A"),
            score, final_label,
        )

        return LongTermLabel(
            symbol=symbol,
            date=today,
            label=final_label,
            score=score,
            votes=votes,
            key_findings=findings,
            expires_at=expires,
        )
