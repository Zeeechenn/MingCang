"""Read-only canonical daily panel routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.routes import m63
from backend.api.schemas import DailyPanelOut
from backend.data.database import get_db
from backend.evidence.daily_panel import build_latest_daily_panel

router = APIRouter(prefix="/daily", tags=["daily"])


def _latest_report_or_none(mode: str) -> dict[str, str] | None:
    try:
        return m63.latest_m63_report(mode)
    except HTTPException:
        return None


def _queue_or_empty() -> dict[str, list[dict[str, Any]]]:
    try:
        return m63.get_m63_queue()
    except Exception:  # noqa: BLE001 - daily panel must degrade instead of failing.
        return {"pending": [], "done": []}


def _discretion_or_empty(db: Session) -> list[dict[str, Any]]:
    try:
        return m63.latest_m59_discretion_cards(db)
    except Exception:  # noqa: BLE001 - observe-only shadow cards are optional.
        return []


@router.get("/panel/latest", response_model=DailyPanelOut)
def latest_daily_panel(
    mode: str = Query(default="postmarket", pattern="^(postmarket)$"),
    as_of: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Return the single Stage5 daily panel entrypoint."""

    return build_latest_daily_panel(
        db,
        mode=mode,
        as_of=as_of,
        m63_report=_latest_report_or_none(mode),
        m63_queue=_queue_or_empty(),
        discretion_cards=_discretion_or_empty(db),
    )
