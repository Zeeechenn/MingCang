"""
多信号聚合 → 最终建议

阶段C 后此模块有两条路径：
  • multi_agent_enabled=False（旧版）：原 aggregate() 三路加权
  • multi_agent_enabled=True（显式研究/实验模式）：aggregate_v2() 调用 agents.pipeline
"""
import logging
import math
import statistics

from backend.analysis.factors import calc_stop_take
from backend.config import active_signal_weights, settings
from backend.decision.signal_policy import score_to_recommendation
from backend.llm import get_provider, has_runtime_llm_provider

logger = logging.getLogger(__name__)


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

    try:
        kronos_score = float(kronos_result["score"])
    except (KeyError, TypeError, ValueError):
        return qlib_score, {"kronos_ignored": "missing_or_invalid_score"}

    if not math.isfinite(kronos_score):
        return qlib_score, {"kronos_ignored": "non_finite_score"}

    kronos_score = max(-100.0, min(100.0, kronos_score))
    w_k = max(0.0, min(1.0, float(settings.kronos_weight_in_quant)))
    blended = qlib_score * (1 - w_k) + kronos_score * w_k
    return round(blended, 1), {
        "kronos_score": round(kronos_score, 1),
        "kronos_volatility_adj": kronos_result.get("volatility_adj", 1.0),
        "kronos_predicted_high": kronos_result.get("predicted_high"),
        "kronos_predicted_low": kronos_result.get("predicted_low"),
    }


def _effective_sentiment_score(sentiment_score: float, sentiment_result: dict | None) -> float:
    """Use event_score when event taxonomy found a real event; otherwise keep polarity."""
    if not sentiment_result or sentiment_result.get("event_score_mode") != "event_override":
        return sentiment_score
    raw_score = sentiment_result.get("event_score")
    if raw_score is None:
        return sentiment_score
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return sentiment_score
    return max(-1.0, min(1.0, score)) if math.isfinite(score) else sentiment_score


def _sentiment_for_signal(sentiment_result: dict) -> dict:
    """Copy sentiment payload with event-aware sentiment substituted for scoring paths."""
    effective = _effective_sentiment_score(
        float(sentiment_result.get("sentiment") or 0.0),
        sentiment_result,
    )
    if effective == sentiment_result.get("sentiment"):
        return sentiment_result
    return {**sentiment_result, "raw_sentiment": sentiment_result.get("sentiment", 0.0), "sentiment": effective}


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
    multi_agent_enabled=False 时跳过，避免批量产信号时消耗 token。
    """
    if not has_runtime_llm_provider(settings):
        return {}
    if not settings.multi_agent_enabled:
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
    try:
        import json as _json

        from backend.ops.llm_usage import log_llm_usage

        log_llm_usage("debate", prompt, _json.dumps(data))
    except Exception:
        pass
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
    long_term_label=None,
    memory_context: dict | None = None,
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
    effective_sentiment = _effective_sentiment_score(sentiment_score, sentiment_result)

    weights = active_signal_weights()
    composite = (
        blended_quant * weights.quant
        + tech_score * weights.technical
        + effective_sentiment * 100 * weights.sentiment
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
        "sentiment": round(effective_sentiment * 100, 1),
    }

    from backend.decision.research_constraints import apply_research_constraints
    from backend.portfolio import suggest_position_pct

    recommendation = _score_to_recommendation(composite)
    confidence = _score_to_confidence(composite)
    position_pct = suggest_position_pct(composite, confidence)
    constrained = apply_research_constraints(
        recommendation=recommendation,
        composite_score=composite,
        position_pct=position_pct,
        long_term_label=long_term_label,
        memory_context=memory_context,
    )

    result = {
        "composite_score": constrained.composite_score,
        "recommendation": constrained.recommendation,
        "confidence": confidence,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_loss_executable": stop_loss_executable,
        "limit_status": limit.get("status", "normal"),
        "breakdown": breakdown,
        "position_pct": constrained.position_pct,
        "risk_notes": constrained.risk_notes,
        "research_constraints": constrained.constraints,
        "research_conflicts": constrained.conflicts,
        "official_action": constrained.final_action,
        "rule_version": f"aggregate_v1:{weights.profile}",
    }
    if llm_arb:
        result["llm_arbitration"] = llm_arb
    if kronos_info:
        result["kronos"] = kronos_info
    if sentiment_result and sentiment_result.get("event_score_mode") == "event_override":
        result["event_signal"] = {
            "event_score": sentiment_result.get("event_score"),
            "raw_sentiment": round(sentiment_score * 100, 1),
            "event_types": sentiment_result.get("event_types", []),
        }
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
    kronos_result: dict | None = None,
) -> dict:
    """
    阶段C 新版聚合：调用 agents.pipeline 完整多 Agent 决策。
    regime: RegimeReport | None — 由调用方提前算好（scheduler 注入）
    reflection_context: 分层记忆文本（阶段C memory_layered.get_layered_context）

    生命周期内可能调用 _bull_bear_debate 或 multi_round_debate 触发 LLM；
    只在分歧时触发以控成本。
    M4.1 启用 multi_round_debate_enabled 时升级为 3 轮辩论。
    """
    from backend.agents import PipelineInputs, run_pipeline
    from backend.agents.analyst import (
        news_analyst,
        quant_analyst,
        sentiment_analyst,
        technical_analyst,
    )
    from backend.agents.director import assess as director_assess
    from backend.agents.researcher import (
        conclusion_to_arbitration_dict,
        has_divergence,
        multi_round_debate,
    )

    sentiment_result = _sentiment_for_signal(sentiment_result)

    # 与旧版一致的 quant 层混合（Kronos 等可选模块仍可参与）
    blended_quant_score, kronos_info = _blend_quant(quant_result.get("score", 0), kronos_result)
    quant_result_merged = {**quant_result, "score": blended_quant_score}

    # 分歧检测：如有则触发 LLM 辩论
    reports = [
        technical_analyst(technical_result),
        quant_analyst(quant_result_merged),
        sentiment_analyst(sentiment_result),
        news_analyst(sentiment_result),
    ]
    # M4.2 Director 评估（零 LLM）→ 取 debate_topic
    director = director_assess(reports) if settings.research_director_enabled else None
    debate_topic = director.debate_topic if director else ""
    from backend.agents.pipeline import build_research_context
    research_context = build_research_context(
        sentiment_result=sentiment_result,
        reflection_context=reflection_context,
    )

    llm_arb = None
    multi_round_tried = False
    if has_divergence(reports):
        if settings.multi_round_debate_enabled:
            # M4.1 三轮辩论（接受 M4.2 Director 议题）
            avg_score = sum(r.score for r in reports) / len(reports)
            conclusion = multi_round_debate(
                reports,
                composite_hint=avg_score,
                reflection_context=reflection_context,
                debate_topic=debate_topic,
                research_context=research_context,
            )
            multi_round_tried = True
            # M17.2：无论多轮是否成功都采用其结论，不再回退到单轮 LLM
            llm_arb = conclusion_to_arbitration_dict(conclusion)
        if not multi_round_tried:
            # 多轮未启用 → 单轮辩论（M17.2：compute real stop/take to avoid dummy 0s）
            from backend.analysis.factors import calc_stop_take
            _stop, _take = calc_stop_take(close, atr,
                                          atr_mult=settings.atr_multiplier,
                                          rr=settings.risk_reward_ratio)
            llm_arb = _bull_bear_debate(
                composite_score=sum(r.score for r in reports) / len(reports),
                quant_score=blended_quant_score,
                tech_result=technical_result,
                sentiment_result=sentiment_result,
                close=close, stop_loss=_stop, take_profit=_take,
                reflection_context=reflection_context,
            ) or None

    decision = run_pipeline(PipelineInputs(
        technical_result=technical_result,
        qlib_result=quant_result_merged,
        sentiment_result=sentiment_result,
        close=close, atr=atr,
        regime=regime,
        llm_arbitration=llm_arb,
        portfolio_drawdown_pct=portfolio_drawdown_pct,
        limit_status=technical_result.get("limit", {}),
        long_term_label=long_term_label,
        _precomputed_reports=reports,  # M17.2 避免四路分析师重复计算
        research_context=research_context,
    ))

    result = decision.to_signal_dict()
    result["rule_version"] = f"multi_agent_v2:{active_signal_weights().profile}"
    if kronos_info:
        result["kronos"] = kronos_info

    # 阶段A regime 过滤层：综合分二次衰减（在 risk_manager 之后，最后兜底）
    if regime is not None:
        from backend.analysis.timing.regime import apply_regime_filter
        old_score = result["composite_score"]
        new_score, dampened = apply_regime_filter(old_score, regime)
        if dampened:
            result["composite_score"] = new_score
            if old_score > 0 and result.get("position_pct", 0) > 0:
                result["position_pct"] = round(result["position_pct"] * (new_score / old_score), 4)
            result["regime_dampened"] = True

    return result


def save_signal(symbol: str, date: str, result: dict, db) -> None:
    """
    将 aggregate() 结果写入 Signal 表（upsert：同一 symbol+date 存在则覆盖更新）。
    """
    import json

    from backend.config import settings
    from backend.data.database import Signal, Stock
    from backend.decision.market_policy import is_production_signal_market

    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock is not None and not is_production_signal_market(stock.market):
        raise ValueError(f"official signals are CN-only; {symbol} market={stock.market} is observe-only")

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

    try:
        from backend.decision.harness import record_decision_run

        record_decision_run(
            db,
            run_type="postmarket",
            symbol=symbol,
            as_of=date,
            result=result,
            input_snapshot={
                "data_timestamp": data_timestamp,
                "breakdown": result.get("breakdown", {}),
                "limit_status": result.get("limit_status", "normal"),
                "news_audit": result.get("news_audit", []),
            },
        )
    except Exception as e:
        # Harness persistence is observability; a write failure must not block signals.
        logger.warning("decision harness write failed for %s %s: %s", symbol, date, e)
