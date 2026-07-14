"""Point-in-time fund-flow feature provider for data and research consumers.

Scoring reads DB-only point-in-time fund-flow rows; collection happens through
the M61 backfill workflow's ``fund_flow`` category.  The historical
``backend.tools.m52_flow_floor`` module remains as a compatibility adapter.
"""
from __future__ import annotations

from datetime import datetime
from math import tanh
from statistics import median
from typing import Any

from backend.data.database import FundFlow, SessionLocal
from backend.data.degradation import emit_degradation


def fetch_flow_data_pit(symbol: str, as_of: datetime) -> list[dict[str, Any]] | None:
    """Return the latest 65 FundFlow rows visible at ``as_of`` in chronological order."""
    db = SessionLocal()
    try:
        rows = (
            db.query(FundFlow)
            .filter(FundFlow.symbol == symbol, FundFlow.trade_date <= as_of)
            .order_by(FundFlow.trade_date.desc())
            .limit(65)
            .all()
        )
        if not rows:
            emit_degradation(
                component="m52_flow_floor",
                category="fund_flow",
                provider="db",
                error="coverage_gap:no_pit_data",
                context={"symbol": symbol, "as_of": as_of},
            )
            return None
        return [
            {
                "trade_date": row.trade_date,
                "main_net": row.main_net,
                "super_large_net": row.super_large_net,
                "large_net": row.large_net,
                "medium_net": row.medium_net,
                "small_net": row.small_net,
            }
            for row in reversed(rows)
        ]
    finally:
        db.close()


def compute_s_flow_data(raw: list[dict[str, Any]] | None) -> float | None:
    """Compute ``tanh(recent5 / (median(abs(rolling_5d_main_net)) * 3))``.

    This is a bounded [-1, 1], per-stock self-normalized v1 heuristic pending
    IC validation; M61 P4 fusion backtest judges whether it survives.
    """
    if not raw:
        return None
    values = [float(value) for row in raw if (value := row.get("main_net")) is not None]
    if len(values) < 25:
        return None

    rolling = [sum(values[idx : idx + 5]) for idx in range(0, len(values) - 4)]
    scale = median(abs(value) for value in rolling)
    if scale == 0:
        return None
    recent5 = sum(values[-5:])
    return float(tanh(recent5 / (scale * 3)))
