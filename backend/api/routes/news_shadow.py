"""Read-only M68 news-pyramid trial views plus bounded operator feedback."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.news_shadow_schemas import NewsShadowFeedbackCreate
from backend.data.database import get_db
from backend.data.news_shadow import (
    create_shadow_feedback,
    get_shadow_run,
    list_shadow_runs,
    shadow_summary,
)

router = APIRouter(prefix="/news-shadow", tags=["news-shadow"])


@router.get("/runs")
def get_news_shadow_runs(
    as_of: str | None = None,
    symbol: str | None = None,
    only_divergent: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_shadow_runs(
        db,
        as_of=as_of,
        symbol=symbol,
        only_divergent=only_divergent,
        limit=limit,
    )


@router.get("/summary")
def get_news_shadow_summary(
    as_of: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return shadow_summary(db, as_of=as_of)


@router.get("/runs/{run_id}")
def get_news_shadow_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    payload = get_shadow_run(db, run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="news shadow run not found")
    return payload


@router.post("/runs/{run_id}/feedback", status_code=201)
def post_news_shadow_feedback(
    run_id: str,
    payload: NewsShadowFeedbackCreate,
    db: Session = Depends(get_db),
) -> dict:
    feedback = create_shadow_feedback(
        db,
        run_id=run_id,
        category=payload.category,
        preferred_path=payload.preferred_path,
        evidence_ref=payload.evidence_ref,
        note=payload.note,
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="news shadow run not found")
    return feedback
