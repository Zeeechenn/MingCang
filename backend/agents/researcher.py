"""
研究员团 — 看多/看空辩论。

三层路径：
  • 快路径（quick_consensus）：分析师分歧标准差 < 阈值时直接复用平均方向，零 LLM
  • 单轮路径（debate）：分歧时由 aggregator._bull_bear_debate 注入 llm_arbitration，1 次 LLM
  • 多轮路径（multi_round_debate, M4.1）：3 轮辩论 bull→bear→bull-final，3 次 LLM
    - 触发条件：multi_round_debate_enabled=True 且 stdev >= multi_round_debate_min_divergence
    - 失败回退：任一轮失败则降级为单轮 llm_arbitration 或 quick_consensus
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from jsonschema import ValidationError, validate

from backend.agents.analyst import AnalystReport
from backend.config import settings
from backend.llm import get_provider, has_runtime_llm_provider


@dataclass
class DebateRound:
    """一轮辩论记录。speaker: 'bull' | 'bear' | 'adjudicator'"""
    round_num: int
    speaker: str
    points: list[str]              # 主张/反驳/回应/裁定理由
    references: list[str]          # 引用的分析师角色或前一轮 point


@dataclass
class ResearcherConclusion:
    bull_points: list[str]
    bear_points: list[str]
    action_bias: str               # 偏多 / 中性 / 偏空
    rationale: str
    used_llm: bool
    rounds: list[DebateRound] = field(default_factory=list)   # M4.1 多轮记录
    fallback_reason: str | None = None        # 走 quick_consensus / 中途降级的原因
    structured_output_valid: bool | None = None  # LLM 路径下 JSON Schema 校验结果


def quick_consensus(
    reports: list[AnalystReport],
    *,
    fallback_reason: str | None = None,
) -> ResearcherConclusion:
    """无分歧时的快速结论生成"""
    scores = [r.score for r in reports]
    avg = sum(scores) / len(scores) if scores else 0
    if avg > 15:
        bias = "偏多"
    elif avg < -15:
        bias = "偏空"
    else:
        bias = "中性"
    bull = [f.key_findings[0] for f in reports if f.score > 10 and f.key_findings]
    bear = [f.key_findings[0] for f in reports if f.score < -10 and f.key_findings]
    return ResearcherConclusion(
        bull_points=bull[:3],
        bear_points=bear[:3],
        action_bias=bias,
        rationale=f"四路均值 {avg:+.1f}，方向一致，跳过辩论。",
        used_llm=False,
        fallback_reason=fallback_reason,
    )


def has_divergence(reports: list[AnalystReport], threshold: float | None = None) -> bool:
    """分析师分数标准差超过阈值视为分歧"""
    if len(reports) < 2:
        return False
    scores = [r.score for r in reports]
    threshold = settings.multi_round_debate_min_divergence if threshold is None else threshold
    # M17.2 口径统一：aggregator 用 stdev < threshold 跳过（即 >= 触发），此处对齐 >=
    return statistics.stdev(scores) >= threshold


def debate(reports: list[AnalystReport], llm_arbitration: dict | None = None) -> ResearcherConclusion:
    """
    单轮辩论（保留为旧路径）：aggregator._bull_bear_debate 注入 llm_arbitration 后调用。
    llm_arbitration 为 None 时退回 quick_consensus。
    """
    if not llm_arbitration:
        return quick_consensus(reports, fallback_reason="no_arbitration_input")

    # M4.1 兼容：若 llm_arbitration 自带 rounds，直接透传
    rounds_raw = llm_arbitration.get("rounds") or []
    rounds = [
        DebateRound(
            round_num=r.get("round_num", i + 1),
            speaker=r.get("speaker", ""),
            points=r.get("points", [])[:3],
            references=r.get("references", []),
        )
        for i, r in enumerate(rounds_raw)
    ]

    return ResearcherConclusion(
        bull_points=llm_arbitration.get("bull_points", [])[:3],
        bear_points=llm_arbitration.get("bear_points", [])[:3],
        action_bias=llm_arbitration.get("action_bias", "中性"),
        rationale=llm_arbitration.get("rationale", ""),
        used_llm=True,
        rounds=rounds,
        fallback_reason=llm_arbitration.get("fallback_reason"),
        structured_output_valid=llm_arbitration.get("structured_output_valid"),
    )


# ── M4.1 多轮辩论 ────────────────────────────────────────────────────

_BULL_OPENING_TOOL = {
    "name": "bull_opening",
    "description": "看多研究员开场陈述",
    "input_schema": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "最强 3 条看多论点（每条 ≤20 字，引用具体信号）",
            },
            "key_signal": {
                "type": "string",
                "description": "最有说服力的信号源（technical/quant/sentiment/news）",
            },
        },
        "required": ["points", "key_signal"],
    },
}

_BEAR_REBUTTAL_TOOL = {
    "name": "bear_rebuttal",
    "description": "看空研究员反驳",
    "input_schema": {
        "type": "object",
        "properties": {
            "rebuttals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "针对哪条 bull point（≤15字摘要）"},
                        "counter": {"type": "string", "description": "反驳论据（≤25字）"},
                    },
                    "required": ["target", "counter"],
                },
                "description": "对 bull 论点逐条反驳，最多 3 条",
            },
            "additional_bears": {
                "type": "array",
                "items": {"type": "string"},
                "description": "bull 未提到的独立看空理由，最多 2 条",
            },
        },
        "required": ["rebuttals", "additional_bears"],
    },
}

_FINAL_ADJUDICATION_TOOL = {
    "name": "final_adjudication",
    "description": "看多对反驳的回应 + 综合裁定",
    "input_schema": {
        "type": "object",
        "properties": {
            "bull_response": {
                "type": "array",
                "items": {"type": "string"},
                "description": "看多对 bear 反驳的最终回应（最多 3 条）",
            },
            "winning_side": {
                "type": "string",
                "enum": ["bull", "bear", "tie"],
                "description": "本轮辩论的胜方（基于论据质量而非数量）",
            },
            "action_bias": {
                "type": "string",
                "enum": ["偏多", "中性", "偏空"],
            },
            "rationale": {
                "type": "string",
                "description": "1 句话综合判断，指出最关键的胜负手",
            },
        },
        "required": ["bull_response", "winning_side", "action_bias", "rationale"],
    },
}


def _build_analyst_brief(reports: list[AnalystReport]) -> str:
    """把 4 路报告压成 LLM 可读的紧凑摘要"""
    lines = []
    for r in reports:
        findings = "; ".join(r.key_findings[:2]) if r.key_findings else "无"
        lines.append(f"- {r.role}: {r.score:+.0f}（置信 {r.confidence:.2f}）{findings}")
    return "\n".join(lines)


def _validate_tool_output(data: dict | None, tool: dict) -> tuple[bool, str | None]:
    """对 complete_structured 返回值跑一次 jsonschema 校验。
    返回 (是否合法, 错误描述)。"""
    if not isinstance(data, dict):
        return False, "missing_or_non_dict_output"
    try:
        validate(instance=data, schema=tool["input_schema"])
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.path) or "<root>"
        return False, f"schema:{tool.get('name', '?')}:{path}:{exc.message}"
    return True, None


_NEGATIVE_HINTS = ("风险", "下滑", "减持", "处罚", "监管", "亏损", "回撤", "拥挤", "走弱")


def _research_context_items(research_context: dict | None, key: str, limit: int = 4) -> list[str]:
    """Read bounded string items from optional research context."""
    if not isinstance(research_context, dict):
        return []
    value = research_context.get(key) or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _split_evidence_for_side(research_context: dict | None, *, side: str) -> list[str]:
    """Partition snippets into bull/bear prompt evidence with simple keyword rules."""
    snippets = _research_context_items(research_context, "evidence_snippets", limit=8)
    if side == "bear":
        return [s for s in snippets if any(hint in s for hint in _NEGATIVE_HINTS)][:4]
    positives = [s for s in snippets if not any(hint in s for hint in _NEGATIVE_HINTS)]
    return positives[:4]


def _format_research_context(research_context: dict | None, *, side: str) -> str:
    """Render optional IC memo context for a specific debate role."""
    if not isinstance(research_context, dict):
        return ""
    if side == "bull":
        primary_label = "可用催化剂"
        primary = _research_context_items(research_context, "catalysts")
    elif side == "bear":
        primary_label = "可用风险"
        primary = _research_context_items(research_context, "risks")
    else:
        primary_label = "催化剂与风险"
        primary = (
            _research_context_items(research_context, "catalysts", limit=3)
            + _research_context_items(research_context, "risks", limit=3)
        )
    evidence = _split_evidence_for_side(research_context, side=side if side in {"bull", "bear"} else "bull")
    if side == "adjudicator":
        evidence += _split_evidence_for_side(research_context, side="bear")
    lines = []
    if primary:
        lines.append(f"{primary_label}：" + "；".join(primary[:5]))
    if evidence:
        lines.append("证据片段：" + "；".join(evidence[:5]))
    stance = research_context.get("stance")
    confidence = research_context.get("confidence")
    if stance:
        lines.append(f"研究员综合立场：{stance}；confidence={confidence}")
    if not lines:
        return ""
    return "结构化专题研究上下文（只能作为论据，不得直接改交易动作）：\n" + "\n".join(lines) + "\n"


def multi_round_debate(
    reports: list[AnalystReport],
    *,
    composite_hint: float = 0.0,
    reflection_context: str = "",
    debate_topic: str = "",
    research_context: dict | None = None,
) -> ResearcherConclusion:
    """
    M4.1 三轮辩论编排器：
      Round 1 — Bull 开场（最强 3 论点）
      Round 2 — Bear 反驳（逐条 + 补充）
      Round 3 — Bull 最终回应 + 裁定 action_bias

    任一轮 LLM 失败则降级：
      • Round 1 失败 → quick_consensus
      • Round 2 失败 → 仅返回 Bull 开场，bias 由分数均值决定
      • Round 3 失败 → 用 Round 1 + Round 2 凑出结论，bias 由分数均值决定

    debate_topic: 由 Research Director（M4.2）下达的议题，为空时让 bull 自由开场
    """
    if not settings.multi_round_debate_enabled:
        return quick_consensus(reports, fallback_reason="multi_round_debate_disabled")

    if not has_runtime_llm_provider(settings):
        return quick_consensus(reports, fallback_reason="no_llm_provider")

    if len(reports) < 2:
        return quick_consensus(reports, fallback_reason="too_few_reports")

    stdev = statistics.stdev([r.score for r in reports])
    if stdev < settings.multi_round_debate_min_divergence:
        return quick_consensus(reports, fallback_reason="no_divergence")

    provider = get_provider()
    brief = _build_analyst_brief(reports)
    topic_line = f"辩论议题（Director 指定）：{debate_topic}\n" if debate_topic else ""
    bull_context = _format_research_context(research_context, side="bull")
    bear_context = _format_research_context(research_context, side="bear")
    adjudicator_context = _format_research_context(research_context, side="adjudicator")

    rounds: list[DebateRound] = []

    # Round 1 — Bull 开场
    bull_prompt = (
        f"{reflection_context}{topic_line}"
        f"{bull_context}"
        f"四路分析师报告：\n{brief}\n"
        f"综合分提示：{composite_hint:+.0f}/100。\n"
        f"你是看多研究员，请用最强的 3 条理由陈述看多观点。"
    )
    bull_data = provider.complete_structured(
        prompt=bull_prompt, tool=_BULL_OPENING_TOOL,
        max_tokens=300, model_tier="fast",
    )
    try:
        import json as _json

        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("deep_research", bull_prompt, _json.dumps(bull_data))
    except Exception:
        pass
    bull_valid, bull_err = _validate_tool_output(bull_data, _BULL_OPENING_TOOL)
    if not bull_valid:
        return quick_consensus(reports, fallback_reason=f"round1_invalid:{bull_err}")
    if not bull_data.get("points"):
        return quick_consensus(reports, fallback_reason="round1_empty_points")

    bull_points = bull_data.get("points", [])[:3]
    rounds.append(DebateRound(
        round_num=1, speaker="bull",
        points=bull_points,
        references=[bull_data.get("key_signal", "")],
    ))

    # Round 2 — Bear 反驳
    bear_prompt = (
        f"四路分析师报告：\n{brief}\n"
        f"{bear_context}"
        f"看多方刚陈述：\n" + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(bull_points)) + "\n"
        "你是看空研究员，请逐条反驳并补充独立看空理由。"
    )
    bear_data = provider.complete_structured(
        prompt=bear_prompt, tool=_BEAR_REBUTTAL_TOOL,
        max_tokens=400, model_tier="fast",
    )
    try:
        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("deep_research", bear_prompt, _json.dumps(bear_data))
    except Exception:
        pass
    bear_valid, bear_err = _validate_tool_output(bear_data, _BEAR_REBUTTAL_TOOL)
    bear_empty = bear_valid and not bear_data.get("rebuttals")
    if not bear_valid or bear_empty:
        # 降级：只有 bull 开场，bias 由均值决定
        avg = sum(r.score for r in reports) / len(reports)
        bias = "偏多" if avg > 10 else ("偏空" if avg < -10 else "中性")
        reason = (
            f"round2_invalid:{bear_err}" if not bear_valid else "round2_empty_rebuttals"
        )
        return ResearcherConclusion(
            bull_points=bull_points,
            bear_points=[],
            action_bias=bias,
            rationale="多轮辩论第2轮失败，回退到 Bull 开场 + 均值裁定。",
            used_llm=True,
            rounds=rounds,
            fallback_reason=reason,
            structured_output_valid=False,
        )

    rebuttals = bear_data.get("rebuttals", [])[:3]
    additional_bears = bear_data.get("additional_bears", [])[:2]
    bear_points = [r.get("counter", "") for r in rebuttals] + additional_bears
    bear_points = [p for p in bear_points if p][:3]
    rounds.append(DebateRound(
        round_num=2, speaker="bear",
        points=bear_points,
        references=[r.get("target", "") for r in rebuttals],
    ))

    # Round 3 — Bull 最终回应 + 裁定
    bear_bullets = "\n".join(
        f"  反驳[{r.get('target', '?')}]: {r.get('counter', '')}"
        for r in rebuttals
    )
    if additional_bears:
        bear_bullets += "\n  独立看空: " + "; ".join(additional_bears)

    final_prompt = (
        f"四路分析师报告：\n{brief}\n"
        f"{adjudicator_context}"
        f"Bull 开场：\n" + "\n".join(f"  {i+1}. {p}" for i, p in enumerate(bull_points)) + "\n"
        f"Bear 反驳：\n{bear_bullets}\n"
        f"请：(1) 让 Bull 最终回应 Bear 的反驳；(2) 客观裁定本轮谁更有说服力，"
        f"给出最终 action_bias。"
    )
    final_data = provider.complete_structured(
        prompt=final_prompt, tool=_FINAL_ADJUDICATION_TOOL,
        max_tokens=400, model_tier="capable",
    )
    try:
        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("deep_research", final_prompt, _json.dumps(final_data))
    except Exception:
        pass
    final_valid, final_err = _validate_tool_output(final_data, _FINAL_ADJUDICATION_TOOL)
    final_empty = final_valid and not final_data.get("action_bias")
    if not final_valid or final_empty:
        # 降级：用前两轮 + 均值
        avg = sum(r.score for r in reports) / len(reports)
        bias = "偏多" if avg > 10 else ("偏空" if avg < -10 else "中性")
        reason = (
            f"round3_invalid:{final_err}" if not final_valid else "round3_empty_bias"
        )
        return ResearcherConclusion(
            bull_points=bull_points,
            bear_points=bear_points,
            action_bias=bias,
            rationale="多轮辩论第3轮失败，按前两轮 + 均值裁定。",
            used_llm=True,
            rounds=rounds,
            fallback_reason=reason,
            structured_output_valid=False,
        )

    bull_response = final_data.get("bull_response", [])[:3]
    rounds.append(DebateRound(
        round_num=3, speaker="adjudicator",
        points=[final_data.get("rationale", "")] + bull_response,
        references=[final_data.get("winning_side", "tie")],
    ))

    return ResearcherConclusion(
        bull_points=bull_points,
        bear_points=bear_points,
        action_bias=final_data["action_bias"],
        rationale=final_data.get("rationale", ""),
        used_llm=True,
        rounds=rounds,
        structured_output_valid=True,
    )


def conclusion_to_arbitration_dict(conclusion: ResearcherConclusion) -> dict:
    """把 ResearcherConclusion 序列化为 llm_arbitration dict（供 pipeline 透传）"""
    return {
        "bull_points": conclusion.bull_points,
        "bear_points": conclusion.bear_points,
        "action_bias": conclusion.action_bias,
        "rationale": conclusion.rationale,
        "used_llm": conclusion.used_llm,
        "round_count": len(conclusion.rounds),
        "fallback_reason": conclusion.fallback_reason,
        "structured_output_valid": conclusion.structured_output_valid,
        "rounds": [
            {
                "round_num": r.round_num,
                "speaker": r.speaker,
                "points": r.points,
                "references": r.references,
            }
            for r in conclusion.rounds
        ],
    }
