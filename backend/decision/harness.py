"""Decision harness persistence and lightweight review helpers."""
from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from backend.data.database import DecisionRun, Price, ResearchState, Signal
from backend.decision.signal_policy import is_entry_signal


def _json(data) -> str:
    """Serialize JSON payloads with stable UTF-8 output."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _parse(raw: str | None, default):
    """Parse a JSON string, returning default on absence or decode failure."""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _signal_summary(result: dict) -> str:
    """Build a short human-readable summary for research state."""
    score = result.get("composite_score")
    rec = result.get("recommendation", "-")
    risk_notes = result.get("risk_notes") or []
    veto = result.get("veto_reason")
    suffix = f"；风控否决：{veto}" if veto else ""
    if risk_notes:
        suffix += "；风控提示：" + " / ".join(risk_notes[:2])
    return f"{rec}，综合分 {score:+.1f}{suffix}" if isinstance(score, (int, float)) else rec


def _trace_step(
    step_name: str,
    *,
    used_llm: bool = False,
    fallback_reason: str | None = None,
    input_summary: str = "",
    output_summary: str = "",
    provider: str | None = None,
    model_tier: str | None = None,
    structured_output_valid: bool | None = None,
) -> dict:
    step = {
        "step_name": step_name,
        "used_llm": used_llm,
        "fallback_reason": fallback_reason,
        "duration_ms": 0,
        "input_summary": input_summary,
        "output_summary": output_summary,
    }
    if used_llm:
        step.update({
            "provider": provider,
            "model_tier": model_tier,
            "structured_output_valid": structured_output_valid,
        })
    return step


def _build_decision_trace(result: dict) -> list[dict]:
    """Build a compact step trace when the caller did not provide one."""
    explicit = result.get("decision_trace")
    if isinstance(explicit, list):
        return explicit

    breakdown = result.get("breakdown", {}) or {}
    llm = result.get("llm_arbitration", {}) or {}
    risk_notes = result.get("risk_notes", []) or []
    portfolio = result.get("portfolio_decision") or {}

    try:
        from backend.config import settings
        provider = settings.ai_provider
    except Exception:
        provider = None

    trace = [
        _trace_step(
            "analysts",
            input_summary="technical/quant/sentiment/news inputs",
            output_summary=", ".join(f"{k}={v}" for k, v in breakdown.items()) or "no breakdown",
        ),
        _trace_step(
            "director",
            input_summary="analyst reports",
            output_summary="; ".join((result.get("director") or {}).get("quality_notes", [])[:2]) or "no director notes",
        ),
        _trace_step(
            "researcher",
            used_llm=bool(llm.get("used_llm")),
            fallback_reason=None if llm.get("used_llm") else "no_llm_or_no_divergence",
            input_summary="analyst disagreement and debate topic",
            output_summary=llm.get("rationale") or "no arbitration",
            provider=provider,
            model_tier="fast",
            structured_output_valid=bool(llm) if llm.get("used_llm") else None,
        ),
        _trace_step(
            "trader",
            input_summary="research conclusion, close, ATR",
            output_summary=(
                f"{result.get('recommendation', '-')}, "
                f"score={result.get('composite_score', '-')}, "
                f"position={result.get('trader_position_pct', result.get('position_pct'))}"
            ),
        ),
        _trace_step(
            "risk_manager",
            input_summary="trader proposal, regime, limit status, long-term label",
            output_summary=(
                result.get("veto_reason")
                or "; ".join(risk_notes[:2])
                or f"approved position={result.get('position_pct')}"
            ),
        ),
    ]
    if portfolio:
        trace.append(_trace_step(
            "portfolio_manager",
            input_summary="batch candidates and current holdings",
            output_summary=(
                f"{portfolio.get('action', '-')}: "
                f"{portfolio.get('rationale') or result.get('allocation_rationale') or ''}"
            ).strip(),
        ))
    return trace


def record_decision_run(
    db,
    *,
    run_type: str,
    symbol: str,
    as_of: str,
    result: dict,
    input_snapshot: dict | None = None,
    notes: str | None = None,
) -> DecisionRun:
    """
    Persist a replayable decision run.

    This is intentionally called after Signal upsert so the main decision path
    remains unchanged if harness persistence fails in tests or scripts.
    """
    trace = _build_decision_trace(result)
    run = DecisionRun(
        run_id=f"{run_type}:{symbol}:{as_of}:{uuid4().hex[:8]}",
        run_type=run_type,
        symbol=symbol,
        as_of=as_of,
        profile=(result.get("rule_version") or "").split(":")[-1] or None,
        rule_version=result.get("rule_version"),
        recommendation=result.get("recommendation"),
        composite_score=result.get("composite_score"),
        input_snapshot_json=_json(input_snapshot or {}),
        agent_outputs_json=_json({
            "breakdown": result.get("breakdown", {}),
            "llm_arbitration": result.get("llm_arbitration"),
            "director": result.get("director"),
            "regime": result.get("regime"),
            "trace": trace,
        }),
        risk_decision_json=_json({
            "limit_status": result.get("limit_status"),
            "risk_notes": result.get("risk_notes", []),
            "veto_reason": result.get("veto_reason"),
            "stop_loss_executable": result.get("stop_loss_executable", True),
        }),
        final_action_json=_json({
            "stop_loss": result.get("stop_loss"),
            "take_profit": result.get("take_profit"),
            "position_pct": result.get("position_pct"),
            "trader_position_pct": result.get("trader_position_pct"),
            "portfolio_decision": result.get("portfolio_decision"),
            "allocation_rationale": result.get("allocation_rationale"),
            "confidence": result.get("confidence"),
        }),
        notes=notes,
        created_at=datetime.utcnow(),
    )
    db.add(run)
    _upsert_research_state_from_signal(db, symbol, result)
    db.commit()
    return run


def _upsert_research_state_from_signal(db, symbol: str, result: dict) -> ResearchState:
    """Update per-symbol research state with the latest signal summary."""
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
    state.last_signal_summary = _signal_summary(result)
    state.updated_at = now
    return state


def get_decision_evidence(db, symbol: str, limit: int = 10) -> list[dict]:
    """Return recent decision runs for frontend evidence-chain display."""
    rows = (
        db.query(DecisionRun)
        .filter(DecisionRun.symbol == symbol)
        .order_by(DecisionRun.as_of.desc(), DecisionRun.created_at.desc())
        .limit(limit)
        .all()
    )
    output = []
    for r in rows:
        agent_outputs = _parse(r.agent_outputs_json, {})
        output.append({
            "run_id": r.run_id,
            "run_type": r.run_type,
            "symbol": r.symbol,
            "as_of": r.as_of,
            "profile": r.profile,
            "rule_version": r.rule_version,
            "recommendation": r.recommendation,
            "composite_score": r.composite_score,
            "input_snapshot": _parse(r.input_snapshot_json, {}),
            "agent_outputs": agent_outputs,
            "trace": agent_outputs.get("trace", []),
            "risk_decision": _parse(r.risk_decision_json, {}),
            "final_action": _parse(r.final_action_json, {}),
            "eval_result": _parse(r.eval_result_json, None),
            "notes": r.notes,
            "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
        })
    return output


def get_research_state(db, symbol: str) -> dict:
    """Return research state with JSON fields parsed."""
    state = db.query(ResearchState).filter(ResearchState.symbol == symbol).first()
    if state is None:
        return {
            "symbol": symbol,
            "thesis": "",
            "risks": [],
            "open_questions": [],
            "last_signal_summary": "",
            "last_review": None,
            "updated_at": None,
        }
    return {
        "symbol": state.symbol,
        "thesis": state.thesis or "",
        "risks": _parse(state.risks_json, []),
        "open_questions": _parse(state.open_questions_json, []),
        "last_signal_summary": state.last_signal_summary or "",
        "last_review": _parse(state.last_review_json, None),
        "updated_at": state.updated_at.isoformat(timespec="seconds") if state.updated_at else None,
    }


def review_latest_signal(db, symbol: str) -> dict | None:
    """
    Attribute the latest signal that already has a next trading-day price.

    The review is intentionally rule-based: it creates a useful first-pass
    learning artifact without spending LLM budget.
    """
    sigs = (
        db.query(Signal)
        .filter(Signal.symbol == symbol)
        .order_by(Signal.date.desc())
        .limit(10)
        .all()
    )
    sig = None
    sig_price = None
    next_price = None
    for candidate in sigs:
        candidate_price = (
            db.query(Price.close)
            .filter(Price.symbol == symbol, Price.date == candidate.date)
            .first()
        )
        candidate_next = (
            db.query(Price.close)
            .filter(Price.symbol == symbol, Price.date > candidate.date)
            .order_by(Price.date.asc())
            .first()
        )
        if candidate_price and candidate_next and candidate_price[0]:
            sig = candidate
            sig_price = candidate_price
            next_price = candidate_next
            break
    if sig is None:
        return None
    assert sig_price is not None
    assert next_price is not None

    ret = (next_price[0] - sig_price[0]) / sig_price[0] * 100
    expected_up = is_entry_signal(sig.recommendation, include_legacy=True)
    correct = (expected_up and ret > 0) or (not expected_up and ret <= 0.5)

    reasons = []
    if not correct and expected_up:
        if (sig.sentiment_score or 0) > 50 and (sig.technical_score or 0) < 0:
            reasons.append("情感偏乐观但技术面转弱")
        if (sig.technical_score or 0) > 20 and (sig.sentiment_score or 0) < 0:
            reasons.append("技术面偏强但新闻情绪拖累")
        if not reasons:
            reasons.append("正向信号次日未兑现，需等待更多样本归因")
    elif correct:
        reasons.append("方向与次日走势一致")
    else:
        reasons.append("观望/规避信号未错过明显上涨")

    review = {
        "signal_date": sig.date,
        "recommendation": sig.recommendation,
        "composite_score": sig.composite_score,
        "next_day_return": round(ret, 2),
        "correct": correct,
        "attribution": reasons,
    }

    state = db.query(ResearchState).filter(ResearchState.symbol == symbol).first()
    now = datetime.utcnow()
    if state is None:
        state = ResearchState(symbol=symbol, risks_json="[]", open_questions_json="[]", created_at=now)
        db.add(state)
    state.last_review_json = _json(review)
    state.updated_at = now

    run = (
        db.query(DecisionRun)
        .filter(DecisionRun.symbol == symbol, DecisionRun.as_of == sig.date)
        .order_by(DecisionRun.created_at.desc())
        .first()
    )
    if run is not None:
        run.eval_result_json = _json(review)
    db.commit()
    return review
