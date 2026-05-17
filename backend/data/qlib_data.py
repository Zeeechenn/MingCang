"""AkShare/SQLite → LightGBM 特征/标签构建器"""
import logging
import numpy as np
import pandas as pd
from backend.data.database import FinancialMetric, Price, Stock
from backend.analysis.factors import add_all_factors
from backend.data.market_features import MARKET_FEATURE_COLS, attach_market_features

logger = logging.getLogger(__name__)

# LightGBM 使用的特征列（推理时必须与训练完全一致）
FEATURE_COLS = [
    "mom_5", "mom_20", "mom_60",
    "rev_10", "rev_20",
    "vol_ratio_20",
    "turnover_proxy_20",
    "amihud_20",
    "volatility_20",
    "vol_skew_20",
    "atr_ratio",
    "rsi14",
    "macd_hist_norm",
    "bb_pct",
    "close_ma20_ratio",
    "close_ma60_ratio",
    "ma20_slope",
    "ma60_slope",
    "roe",
    "revenue_yoy",
    "net_profit_yoy",
    "gross_margin",
    "asset_turnover",
    "log_market_cap",
    "log_float_market_cap",
    "north_net_buy",
    "margin_balance",
    "large_order_net_inflow",
]

FUNDAMENTAL_COLS = [
    "roe",
    "revenue_yoy",
    "net_profit_yoy",
    "gross_margin",
    "asset_turnover",
]

QLIB_MARKET_FEATURE_COLS = [
    "log_market_cap",
    "log_float_market_cap",
    "north_net_buy",
    "margin_balance",
    "large_order_net_inflow",
]


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical factors and return the enriched DataFrame with label."""
    df = add_all_factors(df.copy())
    close = df["close"]

    df["mom_5"]  = close.pct_change(5)
    df["mom_20"] = close.pct_change(20)
    df["mom_60"] = close.pct_change(60)
    df["rev_10"] = -close.pct_change(10)
    df["rev_20"] = -close.pct_change(20)

    df["vol_ratio_20"] = df["volume"] / (df["volume"].rolling(20).mean() + 1e-9)
    ret_1d = close.pct_change()
    traded_value = df["volume"] * close
    df["turnover_proxy_20"] = traded_value / (traded_value.rolling(20).mean() + 1e-9) - 1
    df["amihud_20"] = (ret_1d.abs() / (traded_value + 1e-9)).rolling(20).mean()
    df["volatility_20"] = ret_1d.rolling(20).std()
    df["vol_skew_20"] = ret_1d.rolling(20).skew()
    df["atr_ratio"] = df["atr14"] / (close + 1e-9)
    df["macd_hist_norm"] = df["macd_hist"] / (close + 1e-9)
    df["bb_pct"] = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-9)
    df["close_ma20_ratio"] = close / (df["ma20"] + 1e-9) - 1
    df["close_ma60_ratio"] = close / (df["ma60"] + 1e-9) - 1
    df["ma20_slope"] = df["ma20"].pct_change(5)
    df["ma60_slope"] = df["ma60"].pct_change(10)
    for col in FUNDAMENTAL_COLS:
        if col not in df.columns:
            df[col] = 0.0
    for col in MARKET_FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0
    df["log_market_cap"] = np.log1p(df["market_cap"].clip(lower=0))
    df["log_float_market_cap"] = np.log1p(df["float_market_cap"].clip(lower=0))
    for col in QLIB_MARKET_FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0

    # 5日前瞻收益（训练标签）
    df["label"] = close.shift(-5) / close - 1

    return df


def _attach_point_in_time_fundamentals(df: pd.DataFrame, symbol: str, db) -> pd.DataFrame:
    """
    Attach the latest known quarterly fundamentals for each price date.

    `report_date` is the best available timestamp in the current schema. If a
    later disclosure-date column is added, this helper is the only place that
    needs to switch to the stricter timestamp.
    """
    rows = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.symbol == symbol)
        .order_by(FinancialMetric.report_date)
        .all()
    )
    if not rows:
        return df

    fundamentals = pd.DataFrame([{
        "report_date": r.report_date,
        "known_date": r.disclosure_date or r.report_date,
        "roe": r.roe,
        "revenue_yoy": r.revenue_yoy,
        "net_profit_yoy": r.net_profit_yoy,
        "gross_margin": r.gross_margin,
        "asset_turnover": r.asset_turnover,
    } for r in rows])
    fundamentals["known_date"] = pd.to_datetime(fundamentals["known_date"])

    out = df.copy()
    out["_price_date"] = pd.to_datetime(out["date"])
    out = pd.merge_asof(
        out.sort_values("_price_date"),
        fundamentals.sort_values("known_date"),
        left_on="_price_date",
        right_on="known_date",
        direction="backward",
    )
    for col in FUNDAMENTAL_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.drop(columns=["_price_date", "report_date", "known_date"])


def build_training_data(db, min_rows: int = 120) -> pd.DataFrame:
    """
    读取所有自选股历史价格 → 特征矩阵 + label。
    min_rows: 该股至少需要多少行价格才纳入训练集。
    """
    stocks = db.query(Stock).filter(Stock.active == True).all()
    symbols = [s.symbol for s in stocks]
    industries = {s.symbol: s.industry for s in stocks}
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

        df = _attach_point_in_time_fundamentals(df, sym, db)
        df = attach_market_features(df, sym, db)
        df = _build_features(df)
        df["symbol"] = sym
        df["industry"] = industries.get(sym) or "UNKNOWN"
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    all_df = pd.concat(frames, ignore_index=True)
    return all_df.dropna(subset=FEATURE_COLS + ["label"])


def neutralize_by_date_industry(
    df: pd.DataFrame,
    factor_cols: list[str] | None = None,
    industry_col: str = "industry",
) -> pd.DataFrame:
    """
    Demean factors by date and industry when industry labels are available.

    This helper is intentionally not applied in build_training_data yet: live
    inference is single-symbol, so automatic neutralization during training
    would create train/serve skew. Use it only in offline cross-sectional evals
    that can neutralize both train and inference snapshots consistently.
    """
    factor_cols = factor_cols or FEATURE_COLS
    if "date" not in df.columns or industry_col not in df.columns:
        return df

    out = df.copy()
    for col in factor_cols:
        if col not in out.columns:
            continue
        means = out.groupby(["date", industry_col])[col].transform("mean")
        out[col] = out[col] - means
    return out


def build_inference_features(
    df_raw: pd.DataFrame,
    symbol: str | None = None,
    db=None,
) -> pd.Series:
    """单只股票推理特征（最后一行），可能含 NaN（数据不足时）"""
    df = df_raw.copy()
    had_date_column = "date" in df.columns
    if not had_date_column:
        df["date"] = df.index.astype(str)
    if symbol and db is not None:
        df = _attach_point_in_time_fundamentals(df, symbol, db)
        df = attach_market_features(df, symbol, db)
    df = _build_features(df)
    if not had_date_column and "date" in df.columns:
        df = df.drop(columns=["date"])
    return df[FEATURE_COLS].iloc[-1]
