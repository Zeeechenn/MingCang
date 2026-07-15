"""Watchlist and long-term label routes."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.api.routes._shared import latest_signal, signal_to_schema
from backend.api.schemas import LongTermLabelOut, WatchlistItem
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
    from backend.data.market_profiles import instrument_key

    return LongTermLabelOut(
        symbol=lt.symbol,
        market=lt.market,
        asset_key=instrument_key(lt.market, lt.symbol),
        date=lt.date,
        label=lt.label,
        score=lt.score,
        votes=lt.votes,
        key_findings=lt.key_findings,
        expires_at=lt.expires_at,
        quality=lt.quality,
        constraint_eligible=lt.constraint_eligible,
        quality_notes=lt.quality_notes,
    )


@router.get("/watchlist", response_model=list[WatchlistItem])
def get_watchlist(db: Session = Depends(get_db)):
    """Return all active watchlist stocks with their latest signal and long-term label."""
    from backend.agents.long_term.storage import bulk_get_labels
    from backend.decision.market_policy import signal_scope_for

    stocks = db.query(Stock).filter(Stock.active).all()
    production_symbols = [s.symbol for s in stocks if s.market == "CN"]
    labels = bulk_get_labels(production_symbols, db) if production_symbols else {}
    result = []
    for s in stocks:
        scope = signal_scope_for(s.market, s.symbol)
        sig = latest_signal(s.symbol, db, market=s.market) if scope in {"production", "gray"} else None
        if s.market == "CN":
            lt = labels.get(s.symbol)
        else:
            from backend.agents.long_term.storage import get_active_label

            lt = get_active_label(s.symbol, db, market=s.market)
        result.append(WatchlistItem(
            symbol=s.symbol,
            name=s.name,
            market=s.market,
            asset_key=s.asset_key,
            currency=s.currency,
            timezone=s.timezone,
            lot_size=s.lot_size,
            signal_scope=scope,
            industry=s.industry,
            latest_signal=signal_to_schema(sig) if sig else None,
            long_term_label=label_to_schema(lt),
        ))
    return result


@router.get("/long-term/{symbol}", response_model=LongTermLabelOut)
def get_long_term_label(symbol: str, market: str | None = None, db: Session = Depends(get_db)):
    """Return the most recent unexpired long-term label for a symbol."""
    from backend.agents.long_term.storage import get_active_label

    lt = get_active_label(symbol, db, market=market)
    if lt is None:
        raise HTTPException(404, "No active long-term label")
    return label_to_schema(lt)


@router.post(
    "/long-term/{symbol}/run",
    response_model=LongTermLabelOut,
    dependencies=[Depends(agent_write_guard("long_term.run"))],
)
def run_long_term_label(symbol: str, market: str | None = None, db: Session = Depends(get_db)):
    """Run the long-term analyst team for one symbol and return the saved label."""
    from backend.agents.long_term.storage import save_label
    from backend.agents.long_term.team import LongTermTeam
    from backend.data.instruments import resolve_stock
    from backend.decision.market_policy import is_signal_eligible_stock

    stock = resolve_stock(db, symbol, market=market)
    if stock is None:
        raise HTTPException(404, f"stock {symbol} not found")
    if not is_signal_eligible_stock(stock):
        raise HTTPException(400, "HK/US long-term labels require the explicit gray allowlist")
    if stock.market == "CN":
        label = LongTermTeam().run(stock.symbol, stock.name, db)
    else:
        from backend.agents.long_term.global_team import run_global_long_term

        label = run_global_long_term(stock, db)
    save_label(label, db)
    return label_to_schema(label)


@router.post(
    "/long-term/run",
    dependencies=[Depends(agent_write_guard("long_term.run"))],
)
def trigger_long_term_team(background_tasks: BackgroundTasks):
    """Manually trigger the active-watchlist long-term analyst team in the background."""
    from backend.scheduler import job_weekly_longterm

    background_tasks.add_task(job_weekly_longterm)
    return {"status": "long-term team triggered"}


@router.post(
    "/watchlist",
    dependencies=[Depends(agent_write_guard("watchlist.add"))],
)
def add_stock(
    symbol: str,
    name: str,
    market: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Add or reactivate a stock in the watchlist and trigger backfill."""
    if market not in ("CN", "HK", "US"):
        raise HTTPException(400, "market must be CN, HK, or US")
    from backend.data.market_profiles import instrument_key, normalize_symbol

    symbol = normalize_symbol(symbol, market)
    key = instrument_key(market, symbol)
    existing = db.query(Stock).filter(Stock.asset_key == key).first()
    if existing:
        existing.active = True
        existing.name = name or existing.name
    else:
        db.add(Stock(symbol=symbol, name=name, market=market, active=True))
    db.commit()
    background_tasks.add_task(_backfill_task, symbol, market)
    return {"status": "ok", "backfill": "started"}


@router.delete(
    "/watchlist/{symbol}",
    dependencies=[Depends(agent_write_guard("watchlist.remove"))],
)
def remove_stock(symbol: str, market: str | None = None, db: Session = Depends(get_db)):
    """Soft-delete a stock from the watchlist (sets active=False)."""
    from backend.data.instruments import resolve_stock

    stock = resolve_stock(db, symbol, market=market)
    if stock:
        stock.active = False
        db.commit()
    return {"status": "ok"}
