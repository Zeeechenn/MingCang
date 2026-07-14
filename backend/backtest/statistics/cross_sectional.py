"""Reusable cross-sectional rank-correlation statistics.

These helpers are domain statistics, not M27 CLI behavior.  The historical
``backend.tools.m27_alpha_diagnostic`` module re-exports them for compatibility.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_MIN_DAILY_NAMES = 5


def _round_metric(value: float | int | None, digits: int = 6) -> float | int | None:
    if value is None or not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _safe_spearman(left: pd.Series, right: pd.Series) -> float | None:
    """Return rank correlation when both sides contain enough variation."""
    data = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(data) < 3 or data["left"].nunique() < 2 or data["right"].nunique() < 2:
        return None
    corr = data["left"].rank(method="average").corr(data["right"].rank(method="average"))
    if corr is None or not np.isfinite(corr):
        return None
    return float(corr)


def cross_sectional_ic(
    frame: pd.DataFrame,
    factor_col: str,
    label_col: str,
    *,
    min_names: int = DEFAULT_MIN_DAILY_NAMES,
) -> pd.Series:
    """Return daily cross-sectional Spearman IC for a factor and label."""
    rows: list[tuple[pd.Timestamp, float]] = []
    for date, group in frame.groupby("date", sort=True):
        data = group[[factor_col, label_col]].replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(data) < min_names:
            continue
        corr = _safe_spearman(data[factor_col], data[label_col])
        if corr is not None:
            rows.append((pd.to_datetime(date), corr))
    return pd.Series(dict(rows), name="ic", dtype="float64")


def summarize_ic(ic: pd.Series) -> dict[str, Any]:
    """Summarize IC with the mean/std/ICIR shape used by quant validation."""
    if ic.empty:
        return {
            "ic_days": 0,
            "ic_mean": None,
            "ic_std": None,
            "icir": None,
            "ic_positive_rate": None,
        }
    std = float(ic.std())
    mean = float(ic.mean())
    return {
        "ic_days": int(len(ic)),
        "ic_mean": _round_metric(mean),
        "ic_std": _round_metric(std),
        "icir": _round_metric(mean / std if std > 0 else 0.0),
        "ic_positive_rate": _round_metric(float((ic > 0).mean())),
    }


__all__ = ["cross_sectional_ic", "summarize_ic"]
