"""Cross-route helpers shared by multiple route modules."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.api.schemas import SignalOut
from backend.data.database import Signal


def latest_signal(symbol: str, db: Session, market: str | None = None) -> Signal | None:
    """Return the most recent Signal row for symbol, or None."""
    query = db.query(Signal).filter(Signal.symbol == symbol)
    if market is not None:
        query = query.filter(Signal.market == market)
    return (
        query
        .order_by(Signal.date.desc())
        .first()
    )


def signal_to_schema(sig: Signal) -> SignalOut:
    """Convert a Signal ORM row to SignalOut, parsing llm_rationale JSON."""
    rec = {
        "强买": "可小仓试错",
        "买入": "可关注",
        "卖出": "规避",
        "强卖": "规避",
    }.get(sig.recommendation, sig.recommendation)
    arb = None
    if sig.llm_rationale:
        try:
            arb = json.loads(sig.llm_rationale)
        except Exception:
            arb = {"rationale": sig.llm_rationale, "bull_points": [], "bear_points": [], "action_bias": "中性"}

    return SignalOut(
        id=sig.id,
        symbol=sig.symbol,
        market=getattr(sig, "market", "CN") or "CN",
        asset_key=getattr(sig, "asset_key", None),
        signal_scope=getattr(sig, "signal_scope", "production") or "production",
        date=sig.date,
        composite_score=sig.composite_score,
        recommendation=rec,
        confidence=sig.confidence,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit,
        limit_status=sig.limit_status,
        quant_score=sig.quant_score,
        technical_score=sig.technical_score,
        sentiment_score=sig.sentiment_score,
        llm_arbitration=arb,
        rule_version=getattr(sig, "rule_version", None),
        data_timestamp=getattr(sig, "data_timestamp", None),
    )
