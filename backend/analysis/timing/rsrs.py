"""
RSRS（阻力支撑相对强度）大盘择时
参考：光大证券 20170501 / 20191117 研报。

核心思想：对每根K线用最近 N 日的 (low, high) 做 OLS，斜率 β 反映"价格上行 vs 下行的弹性"。
β 标准化后 > 0.7 视为大盘看多，< -0.7 视为看空。

仅需沪深300指数 OHLC 数据。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rolling_beta(low: pd.Series, high: pd.Series, window: int) -> pd.Series:
    """对 (low, high) 的窗口内做 OLS，返回斜率 β"""
    betas = np.full(len(low), np.nan)
    for i in range(window - 1, len(low)):
        x = low.iloc[i - window + 1: i + 1].values
        y = high.iloc[i - window + 1: i + 1].values
        if np.std(x) < 1e-9:
            continue
        slope, _ = np.polyfit(x, y, 1)
        betas[i] = slope
    return pd.Series(betas, index=low.index)


def compute_rsrs(df: pd.DataFrame, window: int = 18, zscore_lookback: int = 600) -> pd.DataFrame:
    """
    输入指数 OHLC DataFrame（含 high/low 列），输出加上 rsrs_beta / rsrs_z 两列。
    rsrs_z > 0.7 → 看多；< -0.7 → 看空；中间区间不操作。
    """
    df = df.copy()
    df["rsrs_beta"] = _rolling_beta(df["low"], df["high"], window)
    min_periods = min(zscore_lookback, window * 5)
    mean = df["rsrs_beta"].rolling(zscore_lookback, min_periods=min_periods).mean()
    std = df["rsrs_beta"].rolling(zscore_lookback, min_periods=min_periods).std()
    std = std.where(std >= 1e-9)
    df["rsrs_z"] = (df["rsrs_beta"] - mean) / std
    return df


def latest_rsrs_z(index_close_high_low: pd.DataFrame, window: int = 18,
                  zscore_lookback: int = 600) -> float | None:
    """
    便捷函数：给定指数最近 OHLC，返回最新 z 值。
    无足够数据时返回 None。
    """
    if len(index_close_high_low) < window + 20:
        return None
    if "high" not in index_close_high_low.columns or "low" not in index_close_high_low.columns:
        return None
    df = compute_rsrs(index_close_high_low, window=window, zscore_lookback=zscore_lookback)
    z = df["rsrs_z"].iloc[-1]
    return float(z) if pd.notna(z) else None
