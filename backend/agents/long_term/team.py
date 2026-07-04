"""
长期分析师团聚合器

三路分析师 → 加权综合分 → 标签映射 → LongTermLabel

标签映射规则（一票否决 + 加权融合）：
  • 任一分析师投"规避" → label="规避"（一票否决）
  • score ≥ 50  → 值得持有
  • 30 ≤ score < 50（或 track_analyst 第五层⚠️）→ 估值偏高
  • -20 ≤ score < 30 → 观望
  • score < -20 → 规避
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from backend.agents.long_term import (
    jingqi_analyst,
    piotroski_analyst,
    qfii_flow_analyst,
    track_analyst,
)
from backend.agents.long_term.base import LabelQuality, LongTermLabel, LongTermReport, VoteLabel
from backend.config import settings

logger = logging.getLogger(__name__)
PROMPT_VERSION = "m61_p3"


def _aggregate_score(reports: dict[str, LongTermReport]) -> float:
    """加权综合分（settings 中权重可配）

    flow（QFII Outflow 反向规避）权重小，主要靠一票否决发挥作用；
    其 confidence=0 时（未触发规避）会被本函数自动跳过，不稀释正向分。
    """
    weights = {
        "track": settings.long_term_track_weight,
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


def _resolve_label(score: float, votes: dict[str, VoteLabel],
                   track_layer5: str | None = None) -> VoteLabel:
    """根据综合分 + 一票否决 + track_analyst 高位 决定最终 label"""
    # 一票否决：任一分析师投"规避"
    if "规避" in votes.values():
        return "规避"

    # track_analyst 第五层"规避"或"等回调"硬约束
    if track_layer5 == "规避":
        return "规避"

    if score >= 50:
        # 但如果 track_analyst 第五层"等回调"，降级
        if track_layer5 == "等回调":
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


def _assess_label_quality(reports: dict[str, LongTermReport]) -> tuple[LabelQuality, bool, list[str]]:
    """Return quality metadata that controls whether a label may constrain trades."""
    notes: list[str] = []
    valid_reports = [r for r in reports.values() if r.confidence >= 0.01]

    if not valid_reports:
        return "failed", False, ["没有有效长期分析师报告"]

    track = reports.get("track")
    if settings.long_term_track_enabled:
        if track is None:
            return "failed", False, ["赛道研究员分析缺失"]
        if track.confidence < 0.01:
            finding_text = "；".join(track.key_findings)
            if "LLM 调用失败" in finding_text:
                return "failed", False, ["赛道研究员 LLM 调用失败"]
            return "degraded", False, ["赛道研究员置信度为 0，标签仅展示"]

    if len(valid_reports) < 2:
        notes.append("有效长期分析师少于 2 路")
    avg_conf = sum(r.confidence for r in valid_reports) / len(valid_reports)
    if avg_conf < 0.25:
        notes.append(f"长期分析师平均置信度过低 ({avg_conf:.2f})")

    if notes:
        return "degraded", False, notes
    return "trusted", True, ["长期标签通过质量门"]


class LongTermTeam:
    """长期分析师团（封装三路分析师 + 聚合逻辑）"""

    def run(self, symbol: str, name: str, db) -> LongTermLabel:
        """Run all long-term analysts and aggregate into a LongTermLabel."""
        reports: dict[str, LongTermReport] = {}

        if settings.long_term_track_enabled:
            try:
                reports["track"] = track_analyst.analyze(symbol, name, db)
            except Exception as e:
                logger.error("track_analyst 失败 %s: %s", symbol, e)
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
        quality, constraint_eligible, quality_notes = _assess_label_quality(reports)
        quality_notes = [*quality_notes, f"prompt_version={PROMPT_VERSION}"]

        today = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
        expires = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=settings.long_term_label_ttl_days)) \
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
            quality=quality,
            constraint_eligible=constraint_eligible,
            quality_notes=quality_notes,
            prompt_version=PROMPT_VERSION,
        )
