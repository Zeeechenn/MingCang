"""AkShare/SQLite → LightGBM 特征/标签构建器"""
import logging

import numpy as np
import pandas as pd

from backend.analysis.alpha_factors import (
    M27_ALPHA_FEATURE_COLS,
    add_cross_sectional_alpha_factors,
    add_single_stock_alpha_factors,
    rolling_zscore,
)
from backend.analysis.factors import add_all_factors
from backend.data.database import FinancialMetric, Price, Stock
from backend.data.market_features import MARKET_FEATURE_COLS, attach_market_features

logger = logging.getLogger(__name__)

# LightGBM 使用的特征列（推理时必须与训练完全一致）
#
# 注：以下市场端特征因数据源不可得已剔除（详见 market_snapshots.py 文档）：
#   - log_float_market_cap：无独立流通市值历史源，与 log_market_cap 完全相关
#   - north_net_buy：2024-08 后个股北向数据政策性下架
#   - large_order_net_inflow：fflow daykline 端点在本机 Clash TUN 下空响应
PRODUCTION_FEATURE_COLS = [
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
    "margin_balance",
]

FEATURE_COLS = [
    *PRODUCTION_FEATURE_COLS,
    *M27_ALPHA_FEATURE_COLS,
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
    "margin_balance",
]


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical factors and return the enriched DataFrame with label."""
    df = add_all_factors(df.copy())
    df = add_single_stock_alpha_factors(df)
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

    # 5日前瞻收益（训练标签），±30% 截断去除数据异常/复权跳点
    df["label"] = (close.shift(-5) / close - 1).clip(-0.30, 0.30)

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


def build_training_data(
    db,
    min_rows: int = 120,
    include_inactive: bool = False,
    feature_cols: list[str] | None = None,
) -> pd.DataFrame:
    """
    读取历史价格 → 特征矩阵 + label。
    min_rows: 该股至少需要多少行价格才纳入训练集。
    include_inactive: True 时同时纳入 active=False 的扩盘股（M26.1 训练用）。
    """
    if include_inactive:
        stocks = db.query(Stock).all()
    else:
        stocks = db.query(Stock).filter(Stock.active).all()
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
            "_price_source": r.source,
            "_price_fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            "_price_adjustment": r.adjustment,
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
    all_df = add_cross_sectional_alpha_factors(all_df)
    required_feature_cols = feature_cols or FEATURE_COLS
    return all_df.dropna(subset=required_feature_cols + ["label"])


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
    if symbol and db is not None and "date" in df.columns:
        df = _attach_sector_relative_strength_for_inference(df, symbol, db)
    if not had_date_column and "date" in df.columns:
        df = df.drop(columns=["date"])
    return df[FEATURE_COLS].iloc[-1]


def _attach_sector_relative_strength_for_inference(
    df: pd.DataFrame,
    symbol: str,
    db,
) -> pd.DataFrame:
    """Match training's sector-relative-strength z-score for single-symbol inference."""
    if df.empty or "date" not in df.columns:
        return df

    try:
        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        if stock is None or not stock.industry:
            return df
        peers = (
            db.query(Stock.symbol)
            .filter(Stock.industry == stock.industry, Stock.market == stock.market)
            .all()
        )
        peer_symbols = [row[0] for row in peers]
        if len(peer_symbols) < 2 or symbol not in peer_symbols:
            return df

        dates = pd.to_datetime(df["date"], errors="coerce")
        latest_date = dates.max()
        if pd.isna(latest_date):
            return df

        rows = (
            db.query(Price.symbol, Price.date, Price.close)
            .filter(Price.symbol.in_(peer_symbols), Price.date <= latest_date.strftime("%Y-%m-%d"))
            .order_by(Price.symbol, Price.date)
            .all()
        )
        if not rows:
            return df

        prices = pd.DataFrame(
            [{"symbol": row[0], "date": row[1], "close": row[2]} for row in rows]
        )
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
        prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
        prices = prices.dropna(subset=["date", "close"]).sort_values(["symbol", "date"])
        if prices.empty:
            return df

        prices["mom_20"] = prices.groupby("symbol", sort=False)["close"].pct_change(20)
        peer_mean = prices.groupby("date", sort=False)["mom_20"].mean().rename("peer_mean_mom_20")
        target = prices[prices["symbol"] == symbol][["date", "mom_20"]].rename(
            columns={"mom_20": "target_mom_20"}
        )
        relative = target.merge(peer_mean, left_on="date", right_index=True, how="left")
        relative["sector_rel_strength_20"] = relative["target_mom_20"] - relative["peer_mean_mom_20"]
        relative["sector_rel_strength_20_z"] = rolling_zscore(
            relative["sector_rel_strength_20"],
            window=60,
        )
        relative = relative.set_index("date")

        out = df.copy()
        raw_existing = pd.to_numeric(
            out.get("sector_rel_strength_20", pd.Series(0.0, index=out.index)),
            errors="coerce",
        ).fillna(0.0)
        z_existing = pd.to_numeric(
            out.get("sector_rel_strength_20_z", pd.Series(0.0, index=out.index)),
            errors="coerce",
        ).fillna(0.0)
        raw = dates.map(relative["sector_rel_strength_20"])
        z = dates.map(relative["sector_rel_strength_20_z"])
        out["sector_rel_strength_20"] = raw.fillna(raw_existing)
        out["sector_rel_strength_20_z"] = z.fillna(z_existing)
        return out
    except Exception as e:
        logger.debug("sector relative inference feature fallback for %s: %s", symbol, e)
        return df
