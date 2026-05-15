"""
技术因子计算：ATR / RSI / MA / MACD / 布林带 / ADX (阶段B 新增) / ICU EMA (阶段B 新增)
ADX 用于震荡市过滤，ICU 均线对趋势捕捉更灵敏（中泰证券 20230412 研报）。
"""
import pandas as pd
import numpy as np


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range over the given period."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index over the given period."""
    delta = close.diff().fillna(0.0)
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rsi = pd.Series(50.0, index=close.index, dtype=float)
    both_zero = (gain == 0) & (loss == 0)
    gain_only = (gain > 0) & (loss == 0)
    loss_only = (gain == 0) & (loss > 0)
    normal = ~(both_zero | gain_only | loss_only)
    rsi[gain_only] = 100.0
    rsi[loss_only] = 0.0
    rs = gain[normal] / loss[normal]
    rsi[normal] = 100 - 100 / (1 + rs)
    return rsi


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD, signal line, and histogram."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig


def calc_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate Bollinger Bands: upper, mid, lower."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + std_mult * std, mid, mid - std_mult * std


def calc_stop_take(close: float, atr: float, atr_mult: float = 2.0, rr: float = 2.0) -> tuple[float, float]:
    """返回 (stop_loss, take_profit)"""
    risk = atr * atr_mult
    stop_loss = close - risk
    take_profit = close + risk * rr
    return round(stop_loss, 3), round(take_profit, 3)


def calc_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    ADX/+DI/-DI（Wilder DMI 指标）— 阶段B 新增
    ADX < 20: 震荡市；20-40: 趋势市；> 40: 强趋势。
    返回 (adx, plus_di, minus_di) 三个 Series。
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + 1e-9)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / (atr + 1e-9)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx, plus_di, minus_di


def calc_icu_ma(close: pd.Series, fast: int = 13, slow: int = 26) -> tuple[pd.Series, pd.Series]:
    """
    ICU 均线（EMA 替代 SMA，对趋势更敏感）— 中泰证券研报
    返回 (ema_fast, ema_slow)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return ema_fast, ema_slow


def add_all_factors(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """Compute and add all technical factor columns to a copy of df."""
    df = df.copy()
    df["atr14"] = calc_atr(df, atr_period)
    df["rsi14"] = calc_rsi(df["close"])
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["macd"], df["macd_signal"], df["macd_hist"] = calc_macd(df["close"])
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = calc_bollinger(df["close"])
    df["adx14"], df["plus_di"], df["minus_di"] = calc_adx(df, period=atr_period)
    df["icu_fast"], df["icu_slow"] = calc_icu_ma(df["close"])
    return df
