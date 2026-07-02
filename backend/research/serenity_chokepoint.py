"""Serenity Chokepoint methodology lens — RETIRED as an independent analyzer (M55).

M55 Phase 0 spec (`docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md`, section 4) found
this module's own LLM-driven pipeline to be a full duplicate of structures
already living on the ATLAS research spine (`theme_hypothesis_engine.py`,
`ai_supply_chain_template.py`, `forward_thesis.py`, `thesis_ledger.py`,
`review_loop.py`) — with no DB write, no idempotent create, and no
kill_conditions state machine of its own. The module was default-off
(`long_term_serenity_enabled=False`) with zero CLI/web/pipeline callers, so
retiring the independent pipeline is a zero-diff change to production
behaviour.

What remains here, kept intentionally for callers that still want to
reference the shape or load the six-step methodology text:

- `_load_skill_system_prompt()` / `SKILL_MD_CANDIDATES` — the SKILL.md
  loader. The six-step methodology + A-share source playbook text lives on
  as a "keep-standalone" prompt reference (spec ③, step 4); it is not a
  data structure ATLAS has an equivalent field for.
- `SerenityChokepointReport` — the observe-only, score/vote-free dataclass.
  `research_report_gate.py` still type-references it for its optional
  `serenity=` parameter (`_check_serenity_layer`). Field shape is UNCHANGED
  so that gate remains byte-for-byte compatible.
- `analyze()` — kept as a deprecated no-op stub (always returns None,
  never touches the LLM) purely so any stray external import does not
  hard-fail. It is not called anywhere in this repo (verified: only tests
  and `research_report_gate.py`'s type-only import reference this module).

Removed: the independent `_SERENITY_TOOL` structured-LLM schema and the
LLM-calling body of `analyze()` — that was the duplicate "parallel
analyzer" pipeline. Any future consumer of the serenity six-step
methodology should call the ATLAS modules listed above directly
(`theme_hypothesis_engine.create_hypothesis`, `forward_thesis.*`,
`thesis_ledger.create_thesis(kill_conditions=...)`, `review_loop.*`)
rather than re-populating this dataclass through a new LLM tool call.

observe-only / non-promoting.  This module NEVER returns LongTermReport,
never calls LongTermTeam / _aggregate_score / aggregate / aggregate_v2 /
run_pipeline / apply_research_constraints, and never writes to DB.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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

M55 注：此六步方法论现作为跑在 ATLAS 研究脊柱上的方法论透镜使用，不再有独立的
LLM 结构化分析器（`analyze()` 已退役为 no-op）。字段级对应关系见
`docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md` 第 ③ 节。
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
# Result dataclass — retained for `research_report_gate.py` type reference.
#
# INTENTIONALLY has no score / label_vote / trading fields.
# Not a LongTermReport.  Must not be passed to aggregate / run_pipeline.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SerenityChokepointReport:
    """Structured shape for Serenity Chokepoint methodology output.

    Field shape is unchanged from the pre-M55 independent analyzer so that
    `research_report_gate._check_serenity_layer` and its tests remain
    byte-for-byte compatible. Instances are no longer produced by an
    in-module LLM call (see module docstring); callers that still want to
    populate this shape should do so from ATLAS-native data (e.g. a
    `ForwardThesis` / `ThesisLedger` record) rather than a new parallel
    pipeline.
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
# Retired entry point — kept as a deprecated no-op stub only so a stray
# external import of `analyze` does not hard-fail. Always returns None.
# Never touches settings, LLM readiness, providers, or the DB.
# ---------------------------------------------------------------------------

def analyze(
    topic: str,
    symbols: list[str],
    db,
    *,
    as_of: str | None = None,
) -> SerenityChokepointReport | None:
    """RETIRED (M55): always returns None, never calls the LLM or the DB.

    The independent structured-LLM pipeline this function used to run is
    retired per `docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md` section ④ (full
    duplication of the ATLAS research spine). Use the ATLAS modules
    directly (`theme_hypothesis_engine`, `forward_thesis`, `thesis_ledger`,
    `review_loop`) for new work.
    """
    warnings.warn(
        "backend.research.serenity_chokepoint.analyze() is retired (M55) and "
        "always returns None. Use theme_hypothesis_engine / forward_thesis / "
        "thesis_ledger / review_loop on the ATLAS research spine instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "serenity_chokepoint.analyze() called but is retired (M55) — returning None "
        "for topic=%s",
        topic,
    )
    return None
