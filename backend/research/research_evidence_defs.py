"""[M39-M55 论点与门] [gate-guarded] 消费者: backend/research/ai_supply_chain_template.py, backend/research/research_report_gate.py, backend/tools/m45_*.py, backend/tools/m63_render.py.
Shared evidence definitions for M50 research layer.

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


# ---------------------------------------------------------------------------
# QUANT_CLAIM_PATTERNS — M55 Phase 1 (定性/数字分轨纪律，映射表 #4)
# ---------------------------------------------------------------------------
# Serenity SKILL.md discipline: OSINT / social_lead inferences may only feed
# *qualitative* judgement; any *quantifiable* conclusion (market share, TAM,
# supply gap ratio, capacity-expansion timeline in numbers) must be backed by
# a filing/official/primary tier source.  This is a text-scan proxy only —
# it flags the presence of a quantitative-sounding claim; the caller (gate)
# decides whether the backing evidence tier is strong enough.
QUANT_CLAIM_PATTERNS: list[str] = [
    r"份额\s*\d",
    r"市占率\s*\d",
    r"占有率\s*\d",
    r"TAM\s*[\d￥$]",
    r"缺口率\s*\d",
    r"扩产周期\s*\d",
    r"产能\s*\d+\s*(万|亿|GW|片|吨)",
    r"market share\s*\d",
]


def scan_quant_claims(text: str) -> list[str]:
    """Scan text for quantitative-conclusion patterns (定性/数字分轨 proxy).

    Returns the list of matched patterns. Pure scanner — callers decide
    whether the backing evidence tier satisfies the primary-source
    requirement; this function does not know about SourceTier itself.
    """
    hits: list[str] = []
    for pattern in QUANT_CLAIM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(pattern)
    return hits


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


# ---------------------------------------------------------------------------
# FORBIDDEN_JARGON_TERMS — M55 中文表达规范归口（zad SKILL.md「中文表达规范」节）
# ---------------------------------------------------------------------------
# Readability-only convention, observe-only: never touches score / label /
# trading fields. Two things a finished MingCang research report must never
# leak to a reader:
#   1. internal method labels / template scaffolding names (only the system's
#      own prompt authors understand these — a reader sees jargon, not signal)
#   2. bracket/metadata evidence-tier markers that belong in the analyst's
#      working notes, not the prose (spelled-out Chinese, e.g. "这条供货关系
#      来自官网供应商名单、未经公司确认", is what should ship instead).
# NOTE: `[未核实]` / `[推断]` / `[推测]` as *inline missing-data flags* are an
# intentional, separate convention (see research_report_gate docstrings) and
# are NOT included here — this list only targets internal jargon leakage.
FORBIDDEN_JARGON_TERMS: tuple[str, ...] = (
    # zad SKILL.md internal shorthand / metadata labels — never print verbatim.
    "信念档",
    "五连判",
    "用户头",
    "Serenity 头",
    "硬否",
    "不具身",
    "量价双控",
    "单股报告结构",
    "赛道报告结构",
    "逆向链显形",
    "发现硬门",
    "无现成赛道地图",
    "精度降级",
    "同源同日",
    "份额跨层法",
    # bracket-form evidence-tier / methodology tags — spell them out in prose
    # instead of printing the tag itself.
    "OSINT 推断",
    "已证实供货关系",
    "纯推测",
)


MAX_BOLD_MARKERS = 25


def scan_forbidden_jargon(text: str) -> list[str]:
    """Scan rendered report text for internal jargon / template-label leakage.

    Pure scanner (M55 中文表达规范归口, mapping table item "术语三分 + 禁生造词").
    Returns the list of matched terms; the caller decides severity (this
    convention is readability-only and should never escalate past warning).
    """
    return [term for term in FORBIDDEN_JARGON_TERMS if term in text]


def count_bold_markers(text: str) -> int:
    """Count Markdown bold spans (``**...**``) in rendered report text.

    M55 中文表达规范归口 排版克制条:全篇加粗建议控制在 ``MAX_BOLD_MARKERS`` 处
    以内,超过则每行都加粗=等于没重点。Pure counter; caller decides whether to
    warn.
    """
    return len(re.findall(r"\*\*[^*\n]+\*\*", text))
