"""LLM research copilot shadow decision card."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from backend.config import settings
from backend.data.database import DecisionRun, LongTermLabel, NewsItem, ResearchState, Signal
from backend.decision.signal_policy import EXIT_RECS
from backend.llm import get_provider, has_runtime_llm_provider
from backend.skills.vetter import vet_skill_output


class CopilotUnavailable(RuntimeError):
    """Raised when a manual copilot refresh cannot call the runtime LLM."""


class CopilotInputError(RuntimeError):
    """Raised when the copilot lacks the minimum local inputs."""


_SYSTEM_PROMPT = (
    "你是 StockSage 的 A 股研究副驾驶。你只输出影子研究意见，"
    "不得声称会修改官方信号，不得给投资保证。"
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
        .filter(DecisionRun.symbol == symbol, DecisionRun.as_of == as_of)
        .order_by(DecisionRun.created_at.desc())
        .first()
    )
    if exact is not None:
        return exact
    return (
        db.query(DecisionRun)
        .filter(DecisionRun.symbol == symbol)
        .order_by(DecisionRun.as_of.desc(), DecisionRun.created_at.desc())
        .first()
    )


def _latest_news(symbol: str, db, *, limit: int = 8) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=14)
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
    }


def _official_context(sig: Signal, decision: DecisionRun | None) -> dict:
    final_action = _parse(decision.final_action_json, {}) if decision else {}
    risk = _parse(decision.risk_decision_json, {}) if decision else {}
    agent_outputs = _parse(decision.agent_outputs_json, {}) if decision else {}
    breakdown = agent_outputs.get("breakdown") or {
        "quant": sig.quant_score,
        "technical": sig.technical_score,
        "sentiment": sig.sentiment_score,
    }
    return {
        "symbol": sig.symbol,
        "date": sig.date,
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


def _build_prompt(official: dict, news: list[dict], long_term: dict | None) -> str:
    payload = {
        "official_signal": official,
        "recent_news": news,
        "long_term_label": long_term,
        "shadow_rules": {
            "official_signal_is_unchanged": True,
            "max_trial_position_pct": settings.new_signal_trial_pct,
            "max_position_per_stock": settings.max_position_per_stock,
            "allowed_existing_position_multipliers": [0.7, 1.0, 1.1],
        },
    }
    return (
        "请基于以下本地证据生成精简副驾驶卡。"
        "官方信号和止盈止损不会被你修改；shadow_position_pct 只是影子建议。\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _research_state(symbol: str, db) -> ResearchState:
    state = db.query(ResearchState).filter(ResearchState.symbol == symbol).first()
    now = datetime.utcnow()
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

    data = get_provider().complete_structured(
        prompt=_build_prompt(official, news, long_term),
        tool=_COPILOT_TOOL,
        system=_SYSTEM_PROMPT,
        max_tokens=700,
        model_tier="fast",
    )
    if not data:
        raise CopilotUnavailable("LLM copilot returned empty result")

    shadow_position, risk_conflict, position_note = _bounded_shadow_position(official, data)
    card = {
        "symbol": symbol,
        "as_of": sig.date,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "stance": data.get("stance", "中性"),
        "event_read": str(data.get("event_read", ""))[:160],
        "technical_read": str(data.get("technical_read", ""))[:160],
        "risks": [str(x) for x in (data.get("risks") or [])][:3],
        "validation_questions": [str(x) for x in (data.get("validation_questions") or [])][:3],
        "summary_opinion": str(data.get("summary_opinion", ""))[:180],
        "shadow_position_pct": shadow_position,
        "position_note": position_note[:180],
        "risk_conflict": risk_conflict,
        "official": official,
        "long_term": long_term,
    }

    review = vet_skill_output({
        "skill_name": "research-copilot",
        "result": {
            "stance": card["stance"],
            "event_read": card["event_read"],
            "technical_read": card["technical_read"],
            "summary_opinion": card["summary_opinion"],
            "position_note": card["position_note"],
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
