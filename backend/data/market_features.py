"""Point-in-time market cap and money-flow feature helpers."""
from __future__ import annotations

import logging

import pandas as pd

from backend.data.database import MarketSnapshot
from backend.data.degradation import emit_degradation

logger = logging.getLogger(__name__)

MARKET_FEATURE_COLS = [
    "market_cap",
    "float_market_cap",
    "shares_outstanding",
    "north_net_buy",
    "margin_balance",
    "large_order_net_inflow",
]

FAKE_FEATURE_FLAGS = {
    "north_net_buy": {
        "placeholder": True,
        "reason": "A-share per-stock northbound flow is no longer public after 2024-08.",
    },
    "large_order_net_inflow": {
        "placeholder": True,
        "reason": "Eastmoney fflow daykline is not reliably available in the local runtime.",
    },
}
_PLACEHOLDER_WARNING_EMITTED: set[tuple[str, str]] = set()


def _emit_placeholder_feature(symbol: str, col: str, source: str | None, db) -> None:
    key = (symbol, col)
    reason = FAKE_FEATURE_FLAGS.get(col, {}).get("reason", "feature values were filled from NULL to constant 0.0")
    if key not in _PLACEHOLDER_WARNING_EMITTED:
        logger.warning("market feature %s for %s is a NULL-derived placeholder: %s", col, symbol, reason)
        _PLACEHOLDER_WARNING_EMITTED.add(key)
    emit_degradation(
        "market_features",
        "fund_flow",
        col,
        "null_derived_constant_feature",
        context={"symbol": symbol, "source": source, "reason": reason},
        db=db,
    )


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
        "_snapshot_source": r.source,
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
            source = None
            if "_snapshot_source" in out.columns and out["_snapshot_source"].notna().any():
                source = str(out.loc[out["_snapshot_source"].notna(), "_snapshot_source"].iloc[-1])
            if col in FAKE_FEATURE_FLAGS and not out[snap_col].notna().any():
                _emit_placeholder_feature(symbol, col, source, db)
            out[col] = out[snap_col].combine_first(out[col])
            out = out.drop(columns=[snap_col])
        out[col] = out[col].fillna(0.0)
    drop_cols = ["_price_date", "snapshot_date", "_snapshot_source"]
    if not had_date_column:
        drop_cols.append("date")
    return out.drop(columns=[c for c in drop_cols if c in out.columns])
