"""Price bar routes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.schemas import PriceBar
from backend.data.database import Price, get_db

router = APIRouter()


@router.get("/prices/{symbol}", response_model=list[PriceBar])
def get_prices(symbol: str, days: int = 120, db: Session = Depends(get_db)):
    """Return OHLCV price bars for a symbol over the past days."""
    cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date >= cutoff)
        .order_by(Price.date.asc())
        .all()
    )
    return [
        PriceBar(
            time=r.date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume or 0.0,
        )
        for r in rows
    ]
