"""Point-in-time market cap and money-flow feature helpers."""
from __future__ import annotations

import pandas as pd

from backend.data.database import MarketSnapshot

MARKET_FEATURE_COLS = [
    "market_cap",
    "float_market_cap",
    "shares_outstanding",
    "north_net_buy",
    "margin_balance",
    "large_order_net_inflow",
]


def attach_market_features(df: pd.DataFrame, symbol: str, db) -> pd.DataFrame:
    """Attach latest known market/flow snapshot to each row by date."""
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.symbol == symbol)
        .order_by(MarketSnapshot.date)
        .all()
    )
    out = df.copy()
    for col in MARKET_FEATURE_COLS:
        if col not in out.columns:
            out[col] = 0.0
    if not rows:
        return out

    snapshots = pd.DataFrame([{
        "snapshot_date": r.date,
        "market_cap": r.market_cap,
        "float_market_cap": r.float_market_cap,
        "shares_outstanding": r.shares_outstanding,
        "north_net_buy": r.north_net_buy,
        "margin_balance": r.margin_balance,
        "large_order_net_inflow": r.large_order_net_inflow,
    } for r in rows])
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])

    had_date_column = "date" in out.columns
    if not had_date_column:
        out["date"] = out.index.astype(str)
    out["_price_date"] = pd.to_datetime(out["date"])
    out = pd.merge_asof(
        out.sort_values("_price_date"),
        snapshots.sort_values("snapshot_date"),
        left_on="_price_date",
        right_on="snapshot_date",
        direction="backward",
        suffixes=("", "_snapshot"),
    )
    for col in MARKET_FEATURE_COLS:
        snap_col = f"{col}_snapshot"
        if snap_col in out.columns:
            out[col] = out[snap_col].combine_first(out[col])
            out = out.drop(columns=[snap_col])
        out[col] = out[col].fillna(0.0)
    drop_cols = ["_price_date", "snapshot_date"]
    if not had_date_column:
        drop_cols.append("date")
    return out.drop(columns=[c for c in drop_cols if c in out.columns])
