"""News routes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.schemas import NewsOut
from backend.data.database import NewsItem, get_db

router = APIRouter()


@router.get("/news/{symbol}", response_model=list[NewsOut])
def get_news(symbol: str, hours: int = 48, db: Session = Depends(get_db)):
    """Return recent news items for a symbol within the past hours."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at >= cutoff)
        .order_by(NewsItem.published_at.desc())
        .limit(30)
        .all()
    )
    return [
        NewsOut(
            id=r.id,
            title=r.title,
            url=r.url,
            published_at=r.published_at.strftime("%Y-%m-%d %H:%M"),
            source=r.source,
            sentiment_score=r.sentiment_score,
        )
        for r in rows
    ]
