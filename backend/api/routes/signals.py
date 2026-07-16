"""Signal lookup, evaluation, and evidence routes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.routes._shared import latest_signal, signal_to_schema
from backend.api.schemas import (
    DecisionRunOut,
    SignalEvalOut,
    SignalEvalRecord,
    SignalOut,
)
from backend.data.database import Price, Signal, get_db
from backend.decision.signal_policy import is_entry_signal

router = APIRouter()


# Order matters: /signals/{symbol}/latest must register before /signals/{symbol}
# so "latest" is not parsed as a symbol.
@router.get("/signals/{symbol}/latest", response_model=SignalOut)
def get_latest_signal(symbol: str, market: str | None = None, db: Session = Depends(get_db)):
    """Return the most recent signal for a symbol."""
    sig = latest_signal(symbol, db, market=market)
    if not sig:
        raise HTTPException(404, "No signal found")
    return signal_to_schema(sig)


@router.get("/signals/{symbol}", response_model=list[SignalOut])
def get_signals(
    symbol: str,
    limit: int = 30,
    market: str | None = None,
    db: Session = Depends(get_db),
):
    """Return the most recent signals for a symbol up to limit."""
    query = db.query(Signal).filter(Signal.symbol == symbol)
    if market is not None:
        query = query.filter(Signal.market == market.upper())
    sigs = (
        query
        .order_by(Signal.date.desc())
        .limit(limit)
        .all()
    )
    return [signal_to_schema(s) for s in sigs]


@router.get("/signals/eval/{symbol}", response_model=SignalEvalOut)
def eval_signals(
    symbol: str,
    days: int = 60,
    market: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Evaluate signal accuracy over the past `days` days. For each signal, the
    next trading day's close vs. the signal-day close is compared against the
    signal direction.
    """
    cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")
    signal_query = db.query(Signal).filter(Signal.symbol == symbol, Signal.date >= cutoff)
    if market is not None:
        signal_query = signal_query.filter(Signal.market == market.upper())
    signals = (
        signal_query
        .order_by(Signal.date.asc())
        .all()
    )

    records: list[SignalEvalRecord] = []
    returns: list[float] = []
    buy_returns: list[float] = []
    neutral_returns: list[float] = []
    sell_returns: list[float] = []
    correct_count = 0
    evaluated = 0

    for sig in signals:
        # Signal.date 可能是纯日期，也可能是批次时间戳(YYYY-MM-DDTHH:MM+08:00)；
        # Price.date 永远是纯日期，所以要取信号日前缀再比较，否则时间戳信号永远匹配不到日线。
        day = str(sig.date)[:10]
        sig_price = (
            db.query(Price.close)
            .filter(Price.asset_key == sig.asset_key, Price.date == day)
            .first()
        )
        next_price = (
            db.query(Price.close)
            .filter(Price.asset_key == sig.asset_key, Price.date > day)
            .order_by(Price.date.asc())
            .first()
        )

        if sig_price and next_price and sig_price[0]:
            ret = (next_price[0] - sig_price[0]) / sig_price[0] * 100
            if is_entry_signal(sig.recommendation, include_legacy=True):
                direction = "long"
            elif sig.recommendation in ("卖出", "强卖", "规避"):
                direction = "short"
            else:
                direction = "neutral"

            correct = (
                (direction == "long" and ret > 0)
                or (direction == "short" and ret < 0)
                or (direction == "neutral" and abs(ret) <= 0.5)
            )
            if correct:
                correct_count += 1
            evaluated += 1
            returns.append(ret)
            if direction == "long":
                buy_returns.append(ret)
            elif direction == "short":
                sell_returns.append(ret)
            else:
                neutral_returns.append(ret)
            records.append(SignalEvalRecord(
                date=sig.date,
                recommendation=sig.recommendation,
                composite_score=sig.composite_score,
                next_day_return=round(ret, 2),
                correct=correct,
            ))
        else:
            records.append(SignalEvalRecord(
                date=sig.date,
                recommendation=sig.recommendation,
                composite_score=sig.composite_score,
            ))

    def _avg(lst) -> float | None:
        return round(sum(lst) / len(lst), 2) if lst else None

    return SignalEvalOut(
        symbol=symbol,
        days=days,
        total_signals=len(signals),
        evaluated=evaluated,
        win_rate=round(correct_count / evaluated * 100, 1) if evaluated else None,
        avg_return=_avg(returns),
        avg_return_on_buy=_avg(buy_returns),
        avg_return_on_neutral=_avg(neutral_returns),
        avg_return_on_sell=_avg(sell_returns),
        records=records,
    )


@router.get("/signals/{symbol}/evidence", response_model=list[DecisionRunOut])
def get_signal_evidence(symbol: str, limit: int = 10, db: Session = Depends(get_db)):
    """Return recent decision harness records for a symbol."""
    from backend.decision.harness import get_decision_evidence

    return get_decision_evidence(db, symbol, limit=limit)
