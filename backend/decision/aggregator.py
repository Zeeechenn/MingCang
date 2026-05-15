"""
多信号聚合 → 最终建议

阶段C 后此模块有两条路径：
  • multi_agent_enabled=False（旧版）：原 aggregate() 三路加权
  • multi_agent_enabled=True（默认）：aggregate_v2() 调用 agents.pipeline
"""
import math
import statistics
from backend.config import settings, active_signal_weights
from backend.analysis.factors import calc_stop_take
from backend.decision.signal_policy import score_to_recommendation
from backend.llm import get_provider


RECOMMENDATION_MAP = [
    (25,  "可小仓试错"),
    (0,   "可关注"),
    (-20, "观望"),
    (-101, "规避"),
]


def _score_to_recommendation(score: float) -> str:
    """Delegate score to recommendation string via signal_policy."""
    return score_to_recommendation(score)


def _score_to_confidence(score: float) -> str:
    """Map absolute composite score to a confidence label string."""
    abs_score = abs(score)
    if abs_score >= 60:
        return "高"
    if abs_score >= 30:
        return "中"
    return "低"


def _blend_quant(qlib_score: float, kronos_result: dict | None) -> tuple[float, dict]:
    """
    在量化信号层内部混合 Qlib 得分和 Kronos 得分。
    kronos_result=None 时退化为纯 Qlib 得分。
    返回 (blended_score, kronos_breakdown_info)
    """
    if kronos_result is None or not settings.kronos_enabled:
        return qlib_score, {}

    w_k = settings.kronos_weight_in_quant
    blended = qlib_score * (1 - w_k) + kronos_result["score"] * w_k
    return round(blended, 1), {
        "kronos_score": kronos_result["score"],
        "kronos_volatility_adj": kronos_result.get("volatility_adj", 1.0),
        "kronos_predicted_high": kronos_result.get("predicted_high"),
        "kronos_predicted_low": kronos_result.get("predicted_low"),
    }


_DEBATE_TOOL = {
    "name": "debate_result",
    "description": "多空辩论结论",
    "input_schema": {
        "type": "object",
        "properties": {
            "bull_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "看多理由（最多3条，每条15字内）",
            },
            "bear_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "看空理由（最多3条，每条15字内）",
            },
            "action_bias": {
                "type": "string",
                "enum": ["偏多", "中性", "偏空"],
            },
            "rationale": {
                "type": "string",
                "description": "1句话综合判断，指出哪路信号更可信",
            },
        },
        "required": ["bull_points", "bear_points", "action_bias", "rationale"],
    },
}


def _bull_bear_debate(
    composite_score: float,
    quant_score: float,
    tech_result: dict,
    sentiment_result: dict,
    close: float,
    stop_loss: float,
    take_profit: float,
    reflection_context: str = "",
) -> dict:
    """
    三路信号分歧时进行多空辩论（标准差 < 20 视为一致，跳过以节省 API）。
    同时注入历史决策反思（reflection_context）帮助 LLM 修正系统性偏差。
    """
    if not settings.anthropic_api_key and not settings.openai_api_key:
        return {}

    scores = [
        quant_score,
        tech_result.get("score", 0),
        sentiment_result.get("sentiment", 0) * 100,
    ]
    if statistics.stdev(scores) < 20:
        return {}

    key_events = sentiment_result.get("key_events", [])
    limit = tech_result.get("limit", {})
    limit_note = ""
    if limit.get("limit_down"):
        limit_note = "⚠️ 今日跌停，止损信号当日不可执行。"
    elif limit.get("limit_up"):
        limit_note = "今日涨停，买入信号当日难以成交。"

    prompt = (
        f"{reflection_context}"
        f"三路信号存在分歧，请进行多空辩论并给出综合判断：\n"
        f"- 量化信号（Qlib）：{quant_score:.0f}/100\n"
        f"- 技术信号：{tech_result.get('score', 0):.0f}/100"
        f"（RSI={tech_result.get('latest', {}).get('rsi14', 'N/A')}）\n"
        f"- 情感信号：{sentiment_result.get('sentiment', 0)*100:.0f}/100"
        f"，关键事件：{', '.join(key_events) or '无'}\n"
        f"综合分：{composite_score:.0f}，当前价：{close}"
        f"，止损：{stop_loss}，止盈：{take_profit}\n"
        f"{limit_note}"
    )

    data = get_provider().complete_structured(
        prompt=prompt,
        tool=_DEBATE_TOOL,
        max_tokens=400,
        model_tier="fast",
    )
    if data:
        data["bull_points"] = data.get("bull_points", [])[:3]
        data["bear_points"] = data.get("bear_points", [])[:3]
    return data


def aggregate(
    quant_score: float,
    technical_result: dict,
    sentiment_score: float,
    close: float,
    atr: float,
    sentiment_result: dict | None = None,
    kronos_result: dict | None = None,
    reflection_context: str = "",
) -> dict:
    """
    多路信号加权融合，计算止盈止损，输出最终建议。
    sentiment_result: analyze_news() 的完整返回值（含 key_events 等），
                      传入后信号分歧时触发多空辩论；仅传 sentiment_score 时跳过。
    kronos_result: 来自 kronos_engine.kronos_analyze()，可选，None 时跳过。
    reflection_context: decision_memory.get_reflection_context() 的输出，
                        注入辩论 prompt 帮助 LLM 从历史复盘中修正偏差。

    Returns:
        composite_score: -100 ~ +100
        recommendation: 强买/买入/观望/卖出/强卖
        confidence: 高/中/低
        stop_loss: float  (Kronos 高波动时自动扩大)
        take_profit: float
        stop_loss_executable: bool  (跌停时为 False)
        llm_arbitration: dict | None  (含 bull_points/bear_points/action_bias/rationale)
        kronos: dict | None  (前端展示用预测支撑/阻力)
    """
    tech_score = technical_result.get("score", 0)
    blended_quant, kronos_info = _blend_quant(quant_score, kronos_result)

    weights = active_signal_weights()
    composite = (
        blended_quant * weights.quant
        + tech_score * weights.technical
        + sentiment_score * 100 * weights.sentiment
    )
    if not math.isfinite(composite):
        composite = 0.0
    composite = round(max(-100, min(100, composite)), 1)

    # Kronos 高波动预测时动态扩大止损空间（最多 ×2）
    volatility_adj = kronos_info.get("kronos_volatility_adj", 1.0) if kronos_result else 1.0
    effective_atr_mult = min(settings.atr_multiplier * volatility_adj, settings.atr_multiplier * 2)

    stop_loss, take_profit = calc_stop_take(
        close, atr,
        atr_mult=effective_atr_mult,
        rr=settings.risk_reward_ratio,
    )

    # 涨跌停可执行性标注
    limit = technical_result.get("limit", {})
    stop_loss_executable = limit.get("stop_loss_executable", True)

    # 信号分歧时触发多空辩论（含历史反思注入）
    _sent_result = sentiment_result or {"sentiment": sentiment_score, "key_events": []}
    llm_arb = _bull_bear_debate(
        composite, blended_quant, technical_result, _sent_result,
        close, stop_loss, take_profit,
        reflection_context=reflection_context,
    )

    breakdown = {
        "quant": round(blended_quant, 1),
        "technical": round(tech_score, 1),
        "sentiment": round(sentiment_score * 100, 1),
    }

    result = {
        "composite_score": composite,
        "recommendation": _score_to_recommendation(composite),
        "confidence": _score_to_confidence(composite),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_loss_executable": stop_loss_executable,
        "limit_status": limit.get("status", "normal"),
        "breakdown": breakdown,
        "rule_version": f"aggregate_v1:{weights.profile}",
    }
    if llm_arb:
        result["llm_arbitration"] = llm_arb
    if kronos_info:
        result["kronos"] = kronos_info
    return result


def aggregate_v2(
    quant_result: dict,
    technical_result: dict,
    sentiment_result: dict,
    close: float,
    atr: float,
    regime=None,
    reflection_context: str = "",
    portfolio_drawdown_pct: float = 0.0,
    long_term_label=None,
) -> dict:
    """
    阶段C 新版聚合：调用 agents.pipeline 完整多 Agent 决策。
    regime: RegimeReport | None — 由调用方提前算好（scheduler 注入）
    reflection_context: 分层记忆文本（阶段C memory_layered.get_layered_context）

    生命周期内可能调用 _bull_bear_debate 触发 LLM；只在分歧时触发以控成本。
    """
    from backend.agents import run_pipeline
    from backend.agents.analyst import (
        technical_analyst, quant_analyst, sentiment_analyst, news_analyst,
    )
    from backend.agents.researcher import has_divergence

    # 与旧版一致的 quant 层混合（Kronos 等可选模块仍可参与）
    blended_quant_score, kronos_info = _blend_quant(quant_result.get("score", 0), None)
    quant_result_merged = {**quant_result, "score": blended_quant_score}

    # 分歧检测：如有则触发 LLM 辩论（保留原 _bull_bear_debate 工具调用）
    reports = [
        technical_analyst(technical_result),
        quant_analyst(quant_result_merged),
        sentiment_analyst(sentiment_result),
        news_analyst(sentiment_result),
    ]
    llm_arb = None
    if has_divergence(reports):
        llm_arb = _bull_bear_debate(
            composite_score=sum(r.score for r in reports) / len(reports),
            quant_score=blended_quant_score,
            tech_result=technical_result,
            sentiment_result=sentiment_result,
            close=close, stop_loss=0, take_profit=0,
            reflection_context=reflection_context,
        ) or None

    decision = run_pipeline(
        technical_result=technical_result,
        qlib_result=quant_result_merged,
        sentiment_result=sentiment_result,
        close=close, atr=atr,
        regime=regime,
        llm_arbitration=llm_arb,
        portfolio_drawdown_pct=portfolio_drawdown_pct,
        limit_status=technical_result.get("limit", {}),
        long_term_label=long_term_label,
    )

    result = decision.to_signal_dict()
    result["rule_version"] = f"multi_agent_v2:{active_signal_weights().profile}"

    # 阶段A regime 过滤层：综合分二次衰减（在 risk_manager 之后，最后兜底）
    if regime is not None:
        from backend.analysis.timing.regime import apply_regime_filter
        new_score, dampened = apply_regime_filter(result["composite_score"], regime)
        if dampened:
            result["composite_score"] = new_score
            result["recommendation"] = _score_to_recommendation(new_score)
            result["confidence"] = _score_to_confidence(new_score)
            result["regime_dampened"] = True

    return result


def save_signal(symbol: str, date: str, result: dict, db) -> None:
    """
    将 aggregate() 结果写入 Signal 表（upsert：同一 symbol+date 存在则覆盖更新）。
    """
    import json
    from backend.config import settings
    from backend.data.database import Signal

    arb = result.get("llm_arbitration")
    rationale_json = json.dumps(arb, ensure_ascii=False) if arb else None
    rule_version = result.get("rule_version", "multi_agent_v2" if settings.multi_agent_enabled else "aggregate_v1")
    data_timestamp = result.get("data_timestamp", date)

    existing = db.query(Signal).filter(
        Signal.symbol == symbol, Signal.date == date
    ).first()

    if existing:
        existing.quant_score = result["breakdown"]["quant"]
        existing.technical_score = result["breakdown"]["technical"]
        existing.sentiment_score = result["breakdown"]["sentiment"]
        existing.composite_score = result["composite_score"]
        existing.recommendation = result["recommendation"]
        existing.confidence = result["confidence"]
        existing.stop_loss = result["stop_loss"]
        existing.take_profit = result["take_profit"]
        existing.limit_status = result.get("limit_status", "normal")
        existing.llm_rationale = rationale_json
        existing.rule_version = rule_version
        existing.data_timestamp = data_timestamp
    else:
        db.add(Signal(
            symbol=symbol,
            date=date,
            quant_score=result["breakdown"]["quant"],
            technical_score=result["breakdown"]["technical"],
            sentiment_score=result["breakdown"]["sentiment"],
            composite_score=result["composite_score"],
            recommendation=result["recommendation"],
            confidence=result["confidence"],
            stop_loss=result["stop_loss"],
            take_profit=result["take_profit"],
            limit_status=result.get("limit_status", "normal"),
            llm_rationale=rationale_json,
            rule_version=rule_version,
            data_timestamp=data_timestamp,
        ))
    db.commit()
