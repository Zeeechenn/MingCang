"""M27 classic alpha factors for the LightGBM feature panel."""
from __future__ import annotations

import numpy as np
import pandas as pd

ALPHA_FACTOR_COLS = [
    "rev_mom_12_1_z",
    "turnover_anomaly_z",
    "price_volume_divergence_z",
    "sector_rel_strength_20_z",
]
M27_ALPHA_FEATURE_COLS = ALPHA_FACTOR_COLS


def rolling_zscore(
    series: pd.Series,
    window: int = 60,
    *,
    min_periods: int | None = None,
) -> pd.Series:
    """Rolling z-score with finite, neutral fallback for early windows."""
    values = pd.to_numeric(series, errors="coerce")
    min_periods = min_periods or max(5, window // 3)
    mean = values.rolling(window, min_periods=min_periods).mean()
    std = values.rolling(window, min_periods=min_periods).std()
    z = (values - mean) / std.replace(0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def add_classic_alpha_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add single-symbol M27 factors.

    `sector_rel_strength_20_z` is filled as neutral here and overwritten by
    `attach_sector_relative_strength` when a cross-sectional panel is available.
    """
    out = df.copy()
    close = pd.to_numeric(out["close"], errors="coerce")
    volume = pd.to_numeric(out.get("volume", 0.0), errors="coerce").fillna(0.0)

    long_12_1 = close.shift(21) / close.shift(252) - 1
    shorter_fallback = close.shift(21) / close.shift(60) - 1
    out["rev_mom_12_1"] = -long_12_1.combine_first(shorter_fallback)

    turnover_proxy = volume / (volume.rolling(20, min_periods=5).mean() + 1e-9) - 1
    out["turnover_anomaly"] = rolling_zscore(turnover_proxy, window=60)

    price_strength = rolling_zscore(close.pct_change(20), window=60)
    volume_strength = rolling_zscore(volume.pct_change(20), window=60)
    out["price_volume_divergence"] = price_strength - volume_strength

    out["sector_rel_strength_20"] = out.get("sector_rel_strength_20", 0.0)
    out["rev_mom_12_1_z"] = rolling_zscore(out["rev_mom_12_1"], window=120)
    out["turnover_anomaly_z"] = rolling_zscore(out["turnover_anomaly"], window=60)
    out["price_volume_divergence_z"] = rolling_zscore(out["price_volume_divergence"], window=60)
    out["sector_rel_strength_20_z"] = rolling_zscore(out["sector_rel_strength_20"], window=60)
    return out


def add_single_stock_alpha_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Compatibility alias for the qlib feature builder."""
    return add_classic_alpha_factors(df)


def attach_sector_relative_strength(
    panel: pd.DataFrame,
    *,
    industry_col: str = "industry",
    momentum_col: str = "mom_20",
) -> pd.DataFrame:
    """Add per-symbol strength versus same-date industry peers."""
    if "date" not in panel.columns or industry_col not in panel.columns or momentum_col not in panel.columns:
        return panel

    out = panel.copy()
    industry = out[industry_col].fillna("UNKNOWN")
    peer_mean = out.assign(_industry=industry).groupby(["date", "_industry"])[momentum_col].transform("mean")
    out["sector_rel_strength_20"] = out[momentum_col] - peer_mean
    if "symbol" in out.columns:
        out["sector_rel_strength_20_z"] = (
            out.sort_values(["symbol", "date"])
            .groupby("symbol", sort=False)["sector_rel_strength_20"]
            .transform(lambda s: rolling_zscore(s, window=60))
            .reindex(out.index)
        )
    else:
        out["sector_rel_strength_20_z"] = rolling_zscore(out["sector_rel_strength_20"], window=60)
    return out


def add_cross_sectional_alpha_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """Compatibility alias for cross-sectional M27 factor enrichment."""
    return attach_sector_relative_strength(panel)


def latest_sector_relative_strength(symbol: str, latest_date: str, db) -> float:
    """Best-effort latest 20-day relative strength versus same-industry peers."""
    try:
        from backend.data.database import Price, Stock

        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        if stock is None or not stock.industry:
            return 0.0
        peers = (
            db.query(Stock.symbol)
            .filter(Stock.industry == stock.industry, Stock.market == stock.market)
            .all()
        )
        peer_symbols = [row[0] for row in peers]
        if len(peer_symbols) < 2:
            return 0.0

        strengths: dict[str, float] = {}
        for peer in peer_symbols:
            rows = (
                db.query(Price.close)
                .filter(Price.symbol == peer, Price.date <= latest_date)
                .order_by(Price.date.desc())
                .limit(21)
                .all()
            )
            closes = [float(row[0] or 0.0) for row in reversed(rows)]
            if len(closes) >= 21 and closes[0] > 0 and closes[-1] > 0:
                strengths[peer] = closes[-1] / closes[0] - 1
        if symbol not in strengths or len(strengths) < 2:
            return 0.0
        return float(strengths[symbol] - pd.Series(strengths).mean())
    except Exception:
        return 0.0
