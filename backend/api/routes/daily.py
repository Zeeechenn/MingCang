"""Canonical daily panel and explicitly recorded human research reviews."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.api.routes import m63
from backend.api.schemas import DailyPanelOut
from backend.data.database import get_db
from backend.evidence.daily_panel import build_latest_daily_panel
from backend.research.daily_review import ReviewError, list_reviews, record_outcome, record_review

router = APIRouter(prefix="/daily", tags=["daily"])


class HumanReviewIn(BaseModel):
    model_config = {"extra": "forbid"}
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    panel_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    item_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    choice: Literal["accepted", "modified", "rejected"]
    rationale: str = Field(min_length=1, max_length=4000)
    revised_text: str = Field(default="", max_length=4000)


class HumanOutcomeIn(BaseModel):
    model_config = {"extra": "forbid"}
    expected_version: int = Field(ge=1)
    observation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    status: Literal["supported", "contradicted", "inconclusive", "not_observed"]
    note: str = Field(min_length=1, max_length=4000)


@router.get("/reviews")
def daily_reviews(as_of: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"), db: Session = Depends(get_db)) -> dict:
    return list_reviews(db, as_of=as_of)


@router.post("/reviews", dependencies=[Depends(agent_write_guard("daily.review.record"))])
def save_daily_review(payload: HumanReviewIn, db: Session = Depends(get_db)) -> dict:
    try:
        return record_review(db, **payload.model_dump())
    except ReviewError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from exc


@router.post("/reviews/{review_id}/outcomes", dependencies=[Depends(agent_write_guard("daily.review.outcome"))])
def save_daily_review_outcome(review_id: str, payload: HumanOutcomeIn, db: Session = Depends(get_db)) -> dict:
    try:
        return record_outcome(db, review_id=review_id, **payload.model_dump())
    except ReviewError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from exc


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
