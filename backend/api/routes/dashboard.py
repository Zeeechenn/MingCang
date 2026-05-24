"""Dashboard summary route."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.routes._shared import signal_to_schema
from backend.data.database import IndexPrice, Position, Price, Signal, get_db
from backend.decision.signal_policy import is_entry_signal

router = APIRouter()


def _manual_positions_summary(db: Session) -> dict:
    from backend.api.routes.positions import position_to_schema

    rows = (
        db.query(Position)
        .filter(Position.status == "open")
        .order_by(Position.opened_at.desc(), Position.id.desc())
        .all()
    )
    items = [position_to_schema(row, db).model_dump() for row in rows]
    market_value = sum(item.get("market_value") or 0 for item in items)
    cost_value = sum(item.get("cost_value") or 0 for item in items)
    pnl = market_value - cost_value
    return {
        "count": len(items),
        "market_value": round(market_value, 2),
        "cost_value": round(cost_value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / cost_value * 100, 2) if cost_value else None,
        "items": items,
    }


def _market_overview(db: Session) -> dict:
    latest = (
        db.query(IndexPrice)
        .filter(IndexPrice.symbol == "sh000300")
        .order_by(IndexPrice.date.desc())
        .first()
    )
    if latest is None:
        return {"symbol": "sh000300", "name": "沪深300", "available": False}
    return {
        "symbol": latest.symbol,
        "name": "沪深300",
        "available": True,
        "date": latest.date,
        "close": latest.close,
        "change_pct": latest.change_pct,
    }


@router.get("/dashboard/summary")
def dashboard_summary(as_of: str | None = None, db: Session = Depends(get_db)):
    """Return a read-only dashboard snapshot for the StockSage cockpit."""
    from backend.config import active_signal_weights, settings
    from backend.data.quality import build_data_coverage_report
    from backend.ops import kill_switch

    coverage = build_data_coverage_report(db)
    weights = active_signal_weights()
    latest_price_date = db.query(Price.date).order_by(Price.date.desc()).first()
    latest_signal_date = db.query(Signal.date).order_by(Signal.date.desc()).first()
    latest_date = latest_signal_date[0] if latest_signal_date else None
    latest_signals = []
    entry_count = 0
    if latest_date:
        rows = (
            db.query(Signal)
            .filter(Signal.date == latest_date)
            .order_by(Signal.composite_score.desc())
            .limit(12)
            .all()
        )
        latest_signals = [signal_to_schema(row).model_dump() for row in rows]
        entry_count = sum(1 for row in rows if is_entry_signal(row.recommendation, include_legacy=True))

    db_path = settings.database_url.removeprefix("sqlite:///")
    return {
        "system": {
            "database_ok": True,
            "database_path": db_path,
            "latest_price_date": latest_price_date[0] if latest_price_date else None,
            "kill_switch": kill_switch.current_state(),
            "profile": weights.profile,
            "entry_threshold": weights.entry_threshold,
            "weights": {
                "quant": weights.quant,
                "technical": weights.technical,
                "sentiment": weights.sentiment,
            },
        },
        "positions": _manual_positions_summary(db),
        "market_overview": _market_overview(db),
        "coverage": coverage,
        "signals": {
            "latest_date": latest_date,
            "entry_count": entry_count,
            "latest": latest_signals,
        },
    }
