"""LightGBM Alpha model training and status routes."""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks

from backend.data.database import SessionLocal

router = APIRouter()


def _train_task() -> None:
    """Background task: train the LightGBM Alpha model."""
    from backend.analysis.qlib_engine import train

    db = SessionLocal()
    try:
        train(db)
    finally:
        db.close()


@router.post("/model/train")
def trigger_train(background_tasks: BackgroundTasks):
    """Manually trigger LightGBM Alpha retraining (background)."""
    background_tasks.add_task(_train_task)
    return {"status": "training started"}


@router.get("/model/status")
def model_status():
    """Return model file existence and last-modified time."""
    from backend.analysis.qlib_engine import MODEL_PATH

    if MODEL_PATH.exists():
        mtime = os.path.getmtime(MODEL_PATH)
        return {
            "exists": True,
            "path": str(MODEL_PATH),
            "updated_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "size_kb": round(MODEL_PATH.stat().st_size / 1024, 1),
        }
    return {"exists": False}
