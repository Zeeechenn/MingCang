"""Financial Skills routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.data.database import get_db

router = APIRouter()


@router.post("/skills/daily-review/run")
def run_daily_review_endpoint(as_of: str | None = None, db: Session = Depends(get_db)):
    """Run the Daily-Trade-Review skill and persist a Markdown report."""
    from backend.skills.daily_review import build_daily_review

    return build_daily_review(db, as_of=as_of, persist=True).to_dict()


@router.get("/skills/watch-events")
def get_watch_events_endpoint(as_of: str | None = None, db: Session = Depends(get_db)):
    """Return deterministic Stock-Watcher events for active watchlist stocks."""
    from backend.skills.watcher import scan_watch_events

    return [event.to_dict() for event in scan_watch_events(db, as_of=as_of)]
