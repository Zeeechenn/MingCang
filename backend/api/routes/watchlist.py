"""Watchlist and long-term label routes."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.schemas import LongTermLabelOut, WatchlistItem
from backend.api.routes._shared import latest_signal, signal_to_schema
from backend.data.database import SessionLocal, Stock, get_db

router = APIRouter()


def _backfill_task(symbol: str, market: str) -> None:
    """Background task: backfill price data for the given symbol."""
    from backend.data.market import backfill_if_needed

    db = SessionLocal()
    try:
        backfill_if_needed(symbol, market, db, refresh_today=True)
    finally:
        db.close()


def label_to_schema(lt) -> LongTermLabelOut | None:
    """Convert a LongTermLabel ORM row to the API schema, or None."""
    if lt is None:
        return None
    return LongTermLabelOut(
        symbol=lt.symbol,
        date=lt.date,
        label=lt.label,
        score=lt.score,
        votes=lt.votes,
        key_findings=lt.key_findings,
        expires_at=lt.expires_at,
    )


@router.get("/watchlist", response_model=list[WatchlistItem])
def get_watchlist(db: Session = Depends(get_db)):
    """Return all active watchlist stocks with their latest signal and long-term label."""
    from backend.agents.long_term.storage import bulk_get_labels

    stocks = db.query(Stock).filter(Stock.active == True).all()
    labels = bulk_get_labels([s.symbol for s in stocks], db) if stocks else {}
    result = []
    for s in stocks:
        sig = latest_signal(s.symbol, db)
        lt = labels.get(s.symbol)
        result.append(WatchlistItem(
            symbol=s.symbol,
            name=s.name,
            market=s.market,
            industry=s.industry,
            latest_signal=signal_to_schema(sig) if sig else None,
            long_term_label=label_to_schema(lt),
        ))
    return result


@router.get("/long-term/{symbol}", response_model=LongTermLabelOut)
def get_long_term_label(symbol: str, db: Session = Depends(get_db)):
    """Return the most recent unexpired long-term label for a symbol."""
    from backend.agents.long_term.storage import get_active_label

    lt = get_active_label(symbol, db)
    if lt is None:
        raise HTTPException(404, "No active long-term label")
    return label_to_schema(lt)


@router.post("/long-term/run")
def trigger_long_term_team(background_tasks: BackgroundTasks):
    """Manually trigger the long-term analyst team in the background."""
    from backend.scheduler import job_weekly_longterm

    background_tasks.add_task(job_weekly_longterm)
    return {"status": "long-term team triggered"}


@router.post("/watchlist")
def add_stock(
    symbol: str,
    name: str,
    market: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Add or reactivate a stock in the watchlist and trigger backfill."""
    if market not in ("CN", "US"):
        raise HTTPException(400, "market must be CN or US")
    existing = db.query(Stock).filter(Stock.symbol == symbol).first()
    if existing:
        existing.active = True
    else:
        db.add(Stock(symbol=symbol, name=name, market=market))
    db.commit()
    background_tasks.add_task(_backfill_task, symbol, market)
    return {"status": "ok", "backfill": "started"}


@router.delete("/watchlist/{symbol}")
def remove_stock(symbol: str, db: Session = Depends(get_db)):
    """Soft-delete a stock from the watchlist (sets active=False)."""
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock:
        stock.active = False
        db.commit()
    return {"status": "ok"}
