"""AkShare/SQLite → LightGBM 特征/标签构建器"""
import logging
import pandas as pd
from backend.data.database import Price, Stock
from backend.analysis.factors import add_all_factors

logger = logging.getLogger(__name__)

# LightGBM 使用的特征列（推理时必须与训练完全一致）
FEATURE_COLS = [
    "mom_5", "mom_20", "mom_60",
    "vol_ratio_20",
    "atr_ratio",
    "rsi14",
    "macd_hist_norm",
    "bb_pct",
    "close_ma20_ratio",
    "close_ma60_ratio",
]


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical factors and return the enriched DataFrame with label."""
    df = add_all_factors(df.copy())
    close = df["close"]

    df["mom_5"]  = close.pct_change(5)
    df["mom_20"] = close.pct_change(20)
    df["mom_60"] = close.pct_change(60)

    df["vol_ratio_20"] = df["volume"] / (df["volume"].rolling(20).mean() + 1e-9)
    df["atr_ratio"] = df["atr14"] / (close + 1e-9)
    df["macd_hist_norm"] = df["macd_hist"] / (close + 1e-9)
    df["bb_pct"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)
    df["close_ma20_ratio"] = close / (df["ma20"] + 1e-9) - 1
    df["close_ma60_ratio"] = close / (df["ma60"] + 1e-9) - 1

    # 5日前瞻收益（训练标签）
    df["label"] = close.shift(-5) / close - 1

    return df


def build_training_data(db, min_rows: int = 120) -> pd.DataFrame:
    """
    读取所有自选股历史价格 → 特征矩阵 + label。
    min_rows: 该股至少需要多少行价格才纳入训练集。
    """
    symbols = [s.symbol for s in db.query(Stock).filter(Stock.active == True).all()]
    frames = []

    for sym in symbols:
        rows = (
            db.query(Price)
            .filter(Price.symbol == sym)
            .order_by(Price.date)
            .all()
        )
        if len(rows) < min_rows:
            logger.debug("skip %s: only %d rows", sym, len(rows))
            continue

        df = pd.DataFrame([{
            "date": r.date, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close,
            "volume": r.volume or 0.0,
        } for r in rows])

        df = _build_features(df)
        df["symbol"] = sym
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    all_df = pd.concat(frames, ignore_index=True)
    return all_df.dropna(subset=FEATURE_COLS + ["label"])


def build_inference_features(df_raw: pd.DataFrame) -> pd.Series:
    """单只股票推理特征（最后一行），可能含 NaN（数据不足时）"""
    df = _build_features(df_raw.copy())
    return df[FEATURE_COLS].iloc[-1]
