"""Shared evidence definitions for M50 research layer.

Pure constants and pure functions — no side effects, no imports from
signal/decision/scheduler paths.

Two separate constant sets (per spec §1 C1):
- FORBIDDEN_REPORT_WORDING : output text wording checks
- ai_supply_chain_template.FORBIDDEN_TEMPLATE_KEYS : input field-name checks

These are two different checks; do NOT merge or cross-import.
"""
from __future__ import annotations

import re
from enum import StrEnum


class SourceTier(StrEnum):
    """Evidence source quality tiers, ordered strongest → weakest."""

    primary = "primary"       # 一手：原始公告/招股书/问询函/电话会记录
    official = "official"     # 官方：交易所/监管/政府产业数据
    filing = "filing"         # 定期报告：年报/半年报/季报
    ir = "ir"                 # 投资者关系：调研纪要/互动易（公司回复≠审计事实）
    industry = "industry"     # 可信行业媒体/产业数据库/海外龙头披露
    social_lead = "social_lead"  # 社媒/KOL/传闻 —— 仅 lead，不能作唯一证据


class ResearchPriorityBand(StrEnum):
    """Research priority band values used by SerenityChokepointReport.

    Collects all valid ``research_priority_band`` string values in one place so
    gate comparisons and serenity builders can reference the enum instead of
    hard-coding bare strings.
    """

    sufficient = "够查"          # Evidence sufficient to proceed with research
    watchlist = "暂缓"           # Borderline — add to watchlist, revisit later
    insufficient = "证据不足"    # Evidence too thin to support a research memo


# Strength order: primary > official > filing > ir > industry > social_lead
SOURCE_TIER = SourceTier

_TIER_RANK: dict[str, int] = {
    SourceTier.primary: 6,
    SourceTier.official: 5,
    SourceTier.filing: 4,
    SourceTier.ir: 3,
    SourceTier.industry: 2,
    SourceTier.social_lead: 1,
}


def tier_rank(tier: SourceTier | str) -> int:
    """Return numeric rank (higher = stronger evidence)."""
    return _TIER_RANK.get(str(tier) if not isinstance(tier, SourceTier) else tier, 0)


def stronger_than(a: SourceTier | str, b: SourceTier | str) -> bool:
    """Return True if tier *a* is strictly stronger than tier *b*."""
    return tier_rank(a) > tier_rank(b)


# ---------------------------------------------------------------------------
# FORBIDDEN_REPORT_WORDING
# ---------------------------------------------------------------------------
# These are wording patterns checked in the *rendered output text*.
# Distinct from ai_supply_chain_template.FORBIDDEN_TEMPLATE_KEYS which
# checks *input field names*.
#
# Design:
#   - "strong hit" (荐股式断言) → blocked
#   - "soft hit" (语气过强但非断言) → warning only
#
# Each entry is (pattern, is_strong_hit: bool).
# Strong hit: clear buy/sell recommendation language.
# Soft hit: aggressive tone without explicit recommendation.

FORBIDDEN_REPORT_WORDING: list[tuple[str, bool]] = [
    # Strong (blocked) patterns — explicit recommendation / action words
    (r"强烈买入", True),
    (r"强烈推荐", True),
    (r"确定上涨", True),
    (r"必涨", True),
    (r"火速上车", True),
    (r"满仓", True),
    (r"加仓", True),
    (r"减仓", True),
    (r"目标价\s*[\d：:＄$]", True),    # "目标价 120" / "目标价：120" — strong
    (r"买入价", True),
    (r"建仓价", True),
    (r"抄底", True),
    (r"梭哈", True),
    (r"strong buy", True),
    (r"must rise", True),
    (r"guaranteed\s+(gain|profit|return)", True),
    (r"load up", True),
    (r"price target\s*[\d：:$]", True),  # "price target 120"
    # Soft (warning) patterns — strong tone, not necessarily a recommendation
    (r"目标价", False),          # bare "目标价" without number = warning only
    (r"price target", False),   # bare "price target" without number
    (r"强烈看好", False),
    (r"绝对低估", False),
    (r"一定涨", False),
    (r"稳赚", False),
]


def scan_forbidden_wording(text: str) -> list[str]:
    """Scan rendered report text for forbidden wording.

    Returns a list of (pattern, severity) strings for each hit.
    Format: "<pattern>:strong" or "<pattern>:warning".

    Only the *caller* (research_report_gate) decides whether to block or warn;
    this function is purely a scanner.
    """
    hits: list[str] = []
    lower = text.lower()
    for pattern, is_strong in FORBIDDEN_REPORT_WORDING:
        # Use case-insensitive search; Chinese patterns are already lower.
        if re.search(pattern, lower if pattern.isascii() else text, re.IGNORECASE):
            severity = "strong" if is_strong else "warning"
            hits.append(f"{pattern}:{severity}")
    return hits
