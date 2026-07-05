"""[M63 现役] [active] 消费者: backend/api/routes/research.py, backend/tools/m63_research.py.
LLM research copilot shadow decision card."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from backend.config import settings
from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.data.database import DecisionRun, LongTermLabel, NewsItem, ResearchState, Signal
from backend.data.degradation import emit_degradation
from backend.decision.harness import OFFICIAL_SIGNAL_RUN_TYPES
from backend.decision.signal_policy import EXIT_RECS
from backend.llm import get_provider, has_runtime_llm_provider
from backend.skills.vetter import vet_skill_output


class CopilotUnavailable(RuntimeError):
    """Raised when a manual copilot refresh cannot call the runtime LLM."""


class CopilotInputError(RuntimeError):
    """Raised when the copilot lacks the minimum local inputs."""


_SYSTEM_PROMPT = (
    "你是 MingCang 的 A 股研究副驾驶。你只输出影子研究意见，"
    "不得声称会修改官方信号，不得给投资保证。"
    "任何『等待/观察』类结论必须附带可独立观测的触发条件"
    "(具体价格位/均线/已公告的公开事件),禁止把内部标签更新、下季财报披露作为唯一触发。"
    "给出的初始止损不得小于 1.5×ATR14;20日涨幅>15% 的动量股止盈必须用"
    "ATR 追踪表述,禁止静态目标价一刀切。"
    "存在 CFO<净利、流动比率<1、毛利率异常任一项时,建议仓位必须显式下调并说明。"
)

_COPILOT_TOOL = {
    "name": "research_copilot_card",
    "description": "单股影子研究副驾驶卡片",
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {
                "type": "string",
                "enum": ["支持", "谨慎", "反对", "中性"],
            },
            "event_read": {"type": "string", "description": "50字内事件理解"},
            "technical_read": {"type": "string", "description": "50字内技术/分数解读"},
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3条风险",
            },
            "validation_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3条待验证问题",
            },
            "summary_opinion": {"type": "string", "description": "一句综合意见"},
            "shadow_position_pct": {
                "type": "number",
                "description": "影子仓位比例，系统会按规则裁剪",
            },
            "position_note": {"type": "string", "description": "仓位理由"},
            "reentry_trigger": {
                "type": "string",
                "description": "等待/观察类结论的可独立观测再评估触发条件",
            },
        },
        "required": [
            "stance",
            "event_read",
            "technical_read",
            "risks",
            "validation_questions",
            "summary_opinion",
            "shadow_position_pct",
            "position_note",
        ],
    },
}

_OBSERVE_WORDS = ("观望", "等待", "观察", "中性", "谨慎")
_BAD_TRIGGER_WORDS = ("标签", "财报")
_GOOD_TRIGGER_WORDS = (
    "价格",
    "收盘",
    "均线",
    "MA",
    "ma",
    "突破",
    "跌破",
    "公告",
    "事件",
    "解禁",
    "减持",
    "放量",
    "缩量",
)


def _parse(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trigger_quality(card: dict) -> str:
    text = " ".join(
        str(card.get(key) or "")
        for key in ("stance", "summary_opinion", "position_note", "technical_read")
    )
    is_observe = any(word in text for word in _OBSERVE_WORDS)
    if not is_observe:
        return "ok"
    trigger = str(card.get("reentry_trigger") or "").strip()
    if not trigger:
        return "degraded"
    has_bad_only = any(word in trigger for word in _BAD_TRIGGER_WORDS)
    has_good = any(word in trigger for word in _GOOD_TRIGGER_WORDS) or any(ch.isdigit() for ch in trigger)
    if has_bad_only and not has_good:
        return "degraded"
    return "ok"


def _latest_signal(symbol: str, db) -> Signal:
    sig = (
        db.query(Signal)
        .filter(Signal.symbol == symbol)
        .order_by(Signal.date.desc(), Signal.created_at.desc())
        .first()
    )
    if sig is None:
        raise CopilotInputError("No signal found for copilot")
    return sig


def _latest_decision(symbol: str, as_of: str, db) -> DecisionRun | None:
    exact = (
        db.query(DecisionRun)
        .filter(
            DecisionRun.symbol == symbol,
            DecisionRun.as_of == as_of,
            DecisionRun.run_type.in_(OFFICIAL_SIGNAL_RUN_TYPES),
        )
        .order_by(DecisionRun.created_at.desc())
        .first()
    )
    if exact is not None:
        return exact
    return (
        db.query(DecisionRun)
        .filter(
            DecisionRun.symbol == symbol,
            DecisionRun.run_type.in_(OFFICIAL_SIGNAL_RUN_TYPES),
        )
        .order_by(DecisionRun.as_of.desc(), DecisionRun.created_at.desc())
        .first()
    )


def _latest_news(symbol: str, db, *, limit: int = 8) -> list[dict]:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=14)
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "title": row.title,
            "source": row.source,
            "published_at": row.published_at.isoformat(timespec="seconds"),
        }
        for row in rows
    ]


def _latest_long_term(symbol: str, db) -> dict | None:
    row = (
        db.query(LongTermLabel)
        .filter(LongTermLabel.symbol == symbol)
        .order_by(LongTermLabel.date.desc(), LongTermLabel.created_at.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "label": row.label,
        "score": row.score,
        "key_findings": _parse(row.key_findings_json, []),
        "expires_at": row.expires_at,
        "quality": getattr(row, "quality", "degraded") or "degraded",
        "constraint_eligible": bool(getattr(row, "constraint_eligible", False)),
        "quality_notes": _parse(getattr(row, "quality_notes_json", None), []),
    }


_COPILOT_CONTEXT_SECTIONS = [
    "announcements",
    "research_reports",
    "corporate_events",
    "fund_flow",
    "data_health",
]


def _compact_m61_context_pack(pack: dict, *, item_limit: int = 2, field_chars: int = 140) -> dict:
    compact = dict(pack)
    for section, value in list(compact.items()):
        if not isinstance(value, dict):
            continue
        section_value = dict(value)
        items = section_value.get("items")
        if isinstance(items, list):
            clipped: list[dict] = []
            for item in items[:item_limit]:
                if not isinstance(item, dict):
                    clipped.append(item)
                    continue
                clipped.append({
                    key: (val[:field_chars] if isinstance(val, str) and len(val) > field_chars else val)
                    for key, val in item.items()
                })
            section_value["items"] = clipped
        compact[section] = section_value
    return compact


def _build_m61_copilot_context_text(symbol: str, db, *, max_chars: int = 1600) -> str:
    """Render extra M61 prompt context without changing copilot output schema."""
    try:
        pack = build_stock_context_pack(symbol, sections=_COPILOT_CONTEXT_SECTIONS, db=db)
        pack = _compact_m61_context_pack(pack)
        return render_context_text(pack, max_chars)
    except Exception as exc:
        emit_degradation(
            component="research_layer",
            category="copilot_context_pack",
            provider="context_builder",
            error=f"failure:{exc}",
            context={"symbol": symbol},
            db=db,
        )
        return ""


def _official_context(sig: Signal, decision: DecisionRun | None) -> dict:
    """Build official context dict.

    When ``decision`` comes from a different date than ``sig`` (fallback lookup),
    ``decision_date`` will differ from ``signal_date`` and
    ``decision_date_mismatch`` will be True.  Callers should surface this so
    users know that position_pct / risk_notes / veto_reason are from a stale
    decision run.
    """
    final_action = _parse(decision.final_action_json, {}) if decision else {}
    risk = _parse(decision.risk_decision_json, {}) if decision else {}
    agent_outputs = _parse(decision.agent_outputs_json, {}) if decision else {}
    breakdown = agent_outputs.get("breakdown") or {
        "quant": sig.quant_score,
        "technical": sig.technical_score,
        "sentiment": sig.sentiment_score,
    }
    decision_date: str | None = decision.as_of if decision else None
    mismatch = bool(decision_date and decision_date != sig.date)
    return {
        "symbol": sig.symbol,
        "signal_date": sig.date,
        # Keep "date" as the signal date for backward compatibility.
        "date": sig.date,
        "decision_date": decision_date,
        "decision_date_mismatch": mismatch,
        "recommendation": sig.recommendation,
        "confidence": sig.confidence,
        "composite_score": sig.composite_score,
        "quant_score": sig.quant_score,
        "technical_score": sig.technical_score,
        "sentiment_score": sig.sentiment_score,
        "stop_loss": sig.stop_loss,
        "take_profit": sig.take_profit,
        "limit_status": sig.limit_status,
        "rule_version": sig.rule_version,
        "position_pct": _float(final_action.get("position_pct"), 0.0),
        "breakdown": breakdown,
        "risk_notes": risk.get("risk_notes", []),
        "veto_reason": risk.get("veto_reason"),
    }


def _bounded_shadow_position(official: dict, llm_card: dict) -> tuple[float, bool, str]:
    rec = official.get("recommendation")
    official_position = max(0.0, _float(official.get("position_pct"), 0.0))
    requested = max(0.0, _float(llm_card.get("shadow_position_pct"), official_position))
    note = str(llm_card.get("position_note") or "")

    if rec in EXIT_RECS:
        return 0.0, False, f"官方信号为{rec}，影子仓位强制为0。"

    if official_position <= 0:
        shadow = min(requested, settings.new_signal_trial_pct)
    else:
        if requested > official_position * 1.05:
            multiplier = 1.1
        elif requested < official_position * 0.95:
            multiplier = 0.7
        else:
            multiplier = 1.0
        shadow = official_position * multiplier
        shadow = min(shadow, settings.max_position_per_stock)

    shadow = round(max(0.0, shadow), 4)
    conflict = bool(official.get("veto_reason") and shadow > 0)
    return shadow, conflict, note


def _build_prompt(
    official: dict,
    news: list[dict],
    long_term: dict | None,
    context_text: str = "",
) -> str:
    payload = {
        "official_signal": official,
        "recent_news": news,
        "long_term_label": long_term,
        "m61_context_text": context_text,
        "shadow_rules": {
            "official_signal_is_unchanged": True,
            "max_trial_position_pct": settings.new_signal_trial_pct,
            "max_position_per_stock": settings.max_position_per_stock,
            "allowed_existing_position_multipliers": [0.7, 1.0, 1.1],
        },
    }
    note = ""
    if official.get("decision_date_mismatch"):
        note = (
            f"注意：本次 official_signal 中的 position_pct / risk_notes / veto_reason "
            f"来自 decision_date={official['decision_date']}，"
            f"而信号日期为 signal_date={official['signal_date']}，存在日期错配。"
            "在生成 shadow_position_pct 时请保守处理。\n"
        )
    return (
        note
        + "ctx=m61_p3\n"
        + "请基于以下本地证据生成精简副驾驶卡。"
        "官方信号和止盈止损不会被你修改；shadow_position_pct 只是影子建议。\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _research_state(symbol: str, db) -> ResearchState:
    state = db.query(ResearchState).filter(ResearchState.symbol == symbol).first()
    now = datetime.now(UTC).replace(tzinfo=None)
    if state is None:
        state = ResearchState(
            symbol=symbol,
            thesis="",
            risks_json="[]",
            open_questions_json="[]",
            created_at=now,
        )
        db.add(state)
    state.updated_at = now
    return state


def generate_symbol_copilot(symbol: str, db) -> dict:
    """Generate and persist a manual LLM shadow research card for one symbol."""
    if not has_runtime_llm_provider(settings):
        raise CopilotUnavailable("LLM provider unavailable for research copilot")

    sig = _latest_signal(symbol, db)
    decision = _latest_decision(symbol, sig.date, db)
    official = _official_context(sig, decision)
    news = _latest_news(symbol, db)
    long_term = _latest_long_term(symbol, db)
    context_text = _build_m61_copilot_context_text(symbol, db)

    _copilot_prompt = _build_prompt(official, news, long_term, context_text)
    data = get_provider().complete_structured(
        prompt=_copilot_prompt,
        tool=_COPILOT_TOOL,
        system=_SYSTEM_PROMPT,
        max_tokens=700,
        model_tier="fast",
    )
    try:
        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("copilot", _SYSTEM_PROMPT + _copilot_prompt, json.dumps(data))
    except Exception:
        pass
    if not data:
        raise CopilotUnavailable("LLM copilot returned empty result")

    shadow_position, risk_conflict, position_note = _bounded_shadow_position(official, data)
    decision_date_mismatch = official.get("decision_date_mismatch", False)
    card = {
        "symbol": symbol,
        "as_of": sig.date,
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        # Surface decision date so UI / callers can warn when it differs from signal date.
        "decision_date": official.get("decision_date"),
        "decision_date_mismatch": decision_date_mismatch,
        "stance": data.get("stance", "中性"),
        "event_read": str(data.get("event_read", ""))[:160],
        "technical_read": str(data.get("technical_read", ""))[:160],
        "risks": [str(x) for x in (data.get("risks") or [])][:3],
        "validation_questions": [str(x) for x in (data.get("validation_questions") or [])][:3],
        "summary_opinion": str(data.get("summary_opinion", ""))[:180],
        "shadow_position_pct": shadow_position,
        "position_note": position_note[:180],
        "reentry_trigger": str(data.get("reentry_trigger", ""))[:180],
        "risk_conflict": risk_conflict,
        "official": official,
        "long_term": long_term,
    }
    card["trigger_quality"] = _trigger_quality(card)

    review = vet_skill_output({
        "skill_name": "research-copilot",
        "result": {
            "stance": card["stance"],
            "event_read": card["event_read"],
            "technical_read": card["technical_read"],
            "summary_opinion": card["summary_opinion"],
            "position_note": card["position_note"],
            "reentry_trigger": card["reentry_trigger"],
            "risks": card["risks"],
            "validation_questions": card["validation_questions"],
        },
        "evidence": [f"signal:{symbol}:{sig.date}"],
        "allowed_actions": ["research_only"],
    })
    card["vetter"] = review.to_dict()
    if review.blocked_actions:
        card["shadow_position_pct"] = 0.0
        card["position_note"] = ("安全审计阻断自动交易类表述，影子仓位强制为 0。"
                                 + card["position_note"])[:180]

    state = _research_state(symbol, db)
    state.copilot_json = json.dumps(card, ensure_ascii=False, sort_keys=True)
    db.commit()
    return card
