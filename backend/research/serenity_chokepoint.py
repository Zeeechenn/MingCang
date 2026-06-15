"""Serenity Chokepoint Research Analyst — M50 Phase 1.

observe-only / non-promoting.  This module NEVER returns LongTermReport,
never calls LongTermTeam / _aggregate_score / aggregate / aggregate_v2 /
run_pipeline / apply_research_constraints, and never writes to DB.

Entry point: analyze(topic, symbols, db) -> SerenityChokepointReport | None
  - Returns None when long_term_serenity_enabled is False (default).
  - Returns None when LLM is not usable.
  - The returned dataclass contains NO score / label_vote / trading fields.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from backend.research.research_evidence_defs import SourceTier

try:
    from backend.research.research_evidence_defs import ResearchPriorityBand
    _PRIORITY_BAND_VALUES = [b.value for b in ResearchPriorityBand]
except ImportError:
    ResearchPriorityBand = None  # type: ignore[assignment,misc]
    _PRIORITY_BAND_VALUES = ["够查", "暂缓", "证据不足"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SKILL.md loader (mirrors track_analyst._load_skill_system_prompt)
# ---------------------------------------------------------------------------

# backend/research/serenity_chokepoint.py: parents[0]=research, parents[1]=backend, parents[2]=repo root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD_CANDIDATES = (
    _PROJECT_ROOT / ".pi" / "skills" / "serenity-chokepoint" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "serenity-chokepoint" / "SKILL.md",
)

_FALLBACK_SYSTEM = """你是供应链瓶颈研究员（Serenity Chokepoint 方法论）。
请按六步框架对给定产业链赛道做 observe-only 研究：

1. 强制需求 —— 识别下游催化剂，判断需求是否存在"非买不可"刚性。
2. 分层快速筛选 —— 逐层检查：强制需求 / 规模错配 / 无替代 / 外部声音。
   不通过任一项 → 暂缓，无需继续。
3. 稀缺层定位 —— 找"扩产慢 + 供应商少 + 认证严 + 替代难"的层。
4. 证据分层 —— 区分公告/财报（一手）vs 媒体叙事（社媒）。
5. 反方先行 —— 列出主要做空/证伪角度；再给出贝叶斯更新路径。
6. 研究优先级档位 —— 输出"够查"/"暂缓"/"证据不足"之一。

约束：
- 不输出价格预测、买卖建议、仓位、止盈止损。
- 不使用"强烈推荐"/"确定上涨"/"目标价"等字眼。
- 证据必须有可追溯来源；无来源的叙事须注明"待核验"。
"""


def _load_skill_system_prompt() -> str:
    for path in SKILL_MD_CANDIDATES:
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                if raw.startswith("---"):
                    end = raw.find("\n---", 3)
                    if end != -1:
                        raw = raw[end + 4:].lstrip()
                logger.debug("serenity SKILL.md loaded from %s", path)
                return raw
        except Exception as exc:
            logger.warning("读取 serenity SKILL.md 失败 %s: %s", path, exc)
    return _FALLBACK_SYSTEM


# ---------------------------------------------------------------------------
# Tool schema (no score / label_vote / trading fields — enforced by schema)
# ---------------------------------------------------------------------------

_SERENITY_TOOL: dict[str, Any] = {
    "name": "serenity_chokepoint_analysis",
    "description": "供应链瓶颈六步框架结构化输出（observe-only）",
    "input_schema": {
        "type": "object",
        "properties": {
            "chokepoint_layer": {
                "type": "string",
                "description": "论题核心瓶颈层名称（如：光模块封装、CoWoS先进封装、HBM显存）",
            },
            "chain_layers": {
                "type": "array",
                "description": "产业链各层简述（从下游到上游）",
                "items": {
                    "type": "object",
                    "properties": {
                        "layer": {"type": "string"},
                        "description": {"type": "string"},
                        "key_players": {"type": "string"},
                    },
                    "required": ["layer", "description"],
                },
            },
            "scarce_layer": {
                "type": "string",
                "description": "最稀缺层（扩产慢+供应商少+认证严+替代难）",
            },
            "quick_filter_by_layer": {
                "type": "array",
                "description": "逐层快速筛选结果",
                "items": {
                    "type": "object",
                    "properties": {
                        "layer": {"type": "string"},
                        "forced_demand": {"type": "boolean",
                                         "description": "该层是否有强制性需求"},
                        "size_mismatch": {"type": "boolean",
                                          "description": "是否存在规模错配（需求远超供给）"},
                        "no_substitute": {"type": "boolean",
                                          "description": "是否无可替代方案"},
                        "outside_voice": {"type": "string",
                                          "description": "外部佐证（海外龙头/监管/行业数据），无则写'待核验'"},
                    },
                    "required": ["layer", "forced_demand", "size_mismatch",
                                 "no_substitute", "outside_voice"],
                },
            },
            "quick_filter_pass": {
                "type": "boolean",
                "description": "主题级快速筛选是否通过（取 scarce_layer 对应层判定）",
            },
            "evidence_tier": {
                "type": "string",
                "enum": [t.value for t in SourceTier],
                "description": "当前最强证据等级",
            },
            "source_refs": {
                "type": "array",
                "description": "关键证据引用列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "tier": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["title", "tier"],
                },
            },
            "substitute_risk": {
                "type": "string",
                "description": "替代风险描述；无替代风险则写'暂未发现明显替代路径'",
            },
            "bayesian": {
                "type": "object",
                "description": "贝叶斯更新路径",
                "properties": {
                    "prior": {"type": "string", "description": "先验判断"},
                    "key_update_triggers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "哪些新证据会显著更新判断",
                    },
                    "current_posterior": {"type": "string",
                                         "description": "综合当前证据后的后验描述"},
                },
                "required": ["prior", "key_update_triggers", "current_posterior"],
            },
            "bear_case": {
                "type": "string",
                "description": "主要做空/证伪角度（反方先行）",
            },
            "falsification_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "若下列问题有否定答案则论题失效（证伪问题清单）",
            },
            "research_priority_band": {
                "type": "string",
                "enum": _PRIORITY_BAND_VALUES,
                "description": "研究优先级档位",
            },
        },
        "required": [
            "chokepoint_layer",
            "chain_layers",
            "scarce_layer",
            "quick_filter_by_layer",
            "quick_filter_pass",
            "evidence_tier",
            "source_refs",
            "substitute_risk",
            "bayesian",
            "bear_case",
            "falsification_questions",
            "research_priority_band",
        ],
    },
}

# Verify no trading / scoring fields leak into schema
_FORBIDDEN_SCHEMA_KEYS = {
    "score", "label_vote", "buy_score", "position_pct",
    "price_target", "stop_loss", "take_profit", "composite_score",
}
assert not (_FORBIDDEN_SCHEMA_KEYS & set(_SERENITY_TOOL["input_schema"]["properties"])), (
    "Serenity tool schema must not contain scoring/trading fields"
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SerenityChokepointReport:
    """Structured output from Serenity Chokepoint analyst.

    INTENTIONALLY has no score / label_vote / trading fields.
    Not a LongTermReport.  Must not be passed to aggregate / run_pipeline.
    """

    topic: str
    as_of: str                          # YYYY-MM-DD
    chokepoint_layer: str
    chain_layers: list[dict]
    scarce_layer: str
    quick_filter_by_layer: list[dict]   # [{layer, forced_demand, size_mismatch,
                                        #   no_substitute, outside_voice}]
    quick_filter_pass: bool
    evidence_tier: str                  # SourceTier value
    source_refs: list                   # [{title, url?, tier, note?}]
    substitute_risk: str
    bayesian: dict                      # {prior, key_update_triggers, current_posterior}
    bear_case: str
    falsification_questions: list[str]
    research_priority_band: Literal["够查", "暂缓", "证据不足"]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(
    topic: str,
    symbols: list[str],
    db,
    *,
    as_of: str | None = None,
) -> SerenityChokepointReport | None:
    """Run Serenity Chokepoint analysis for *topic*.

    Returns None (observe-only disabled) when:
    - settings.long_term_serenity_enabled is False (default)
    - LLM is not usable

    Never writes to DB.  Never calls LongTermTeam aggregation paths.
    """
    from backend.config import settings

    if not settings.long_term_serenity_enabled:
        logger.debug("serenity_chokepoint disabled (long_term_serenity_enabled=False)")
        return None

    from backend.llm import get_provider, runtime_readiness

    readiness = runtime_readiness(settings)
    if not readiness.get("usable"):
        logger.warning("serenity_chokepoint: LLM not usable — %s", readiness.get("reason"))
        return None

    llm = get_provider()

    day = as_of or date.today().isoformat()
    system_prompt = _load_skill_system_prompt()

    # Build a concise prompt with available context
    symbol_str = ", ".join(symbols) if symbols else "（无指定标的）"
    prompt = (
        f"主题：{topic}\n"
        f"相关标的：{symbol_str}\n"
        f"研究日期：{day}\n\n"
        "请按 Serenity Chokepoint 六步框架，对上述主题做供应链瓶颈结构化分析。\n"
        "要求：只做 observe-only 研究，不输出买卖建议/价格预测/仓位。"
    )

    result = llm.complete_structured(
        prompt=prompt,
        tool=_SERENITY_TOOL,
        system=system_prompt,
        max_tokens=1200,
        model_tier="capable",
    )

    if not result:
        logger.warning("serenity_chokepoint: LLM returned empty result for topic=%s", topic)
        return None

    try:
        return SerenityChokepointReport(
            topic=topic,
            as_of=day,
            chokepoint_layer=result.get("chokepoint_layer", ""),
            chain_layers=result.get("chain_layers", []),
            scarce_layer=result.get("scarce_layer", ""),
            quick_filter_by_layer=result.get("quick_filter_by_layer", []),
            quick_filter_pass=bool(result.get("quick_filter_pass", False)),
            evidence_tier=result.get("evidence_tier", "social_lead"),
            source_refs=result.get("source_refs", []),
            substitute_risk=result.get("substitute_risk", ""),
            bayesian=result.get("bayesian", {
                "prior": "",
                "key_update_triggers": [],
                "current_posterior": "",
            }),
            bear_case=result.get("bear_case", ""),
            falsification_questions=result.get("falsification_questions", []),
            research_priority_band=result.get("research_priority_band", "证据不足"),
        )
    except (TypeError, ValueError) as exc:
        logger.error("serenity_chokepoint: failed to build report: %s", exc)
        return None
