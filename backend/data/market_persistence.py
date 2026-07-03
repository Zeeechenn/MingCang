"""Database read/write helpers for market data."""
import logging
from collections.abc import Callable
from datetime import date, timedelta
from statistics import median as _median

import pandas as pd

logger = logging.getLogger("backend.data.market")

BACKFILL_YEARS = 5          # 首次初始化回填年数
BACKFILL_THRESHOLD_DAYS = 1   # 最新数据距今超过此天数才触发回填（日常运营=1）
REFRESH_WINDOW_DAYS = 5  # refresh_today=True 时覆盖回写的最近窗口


def load_price_df(symbol: str, db, days: int = 200) -> pd.DataFrame:
    """
    从 Price 表读取历史行情，返回 OHLCV DataFrame（index=date str，升序）。
    days=200 确保 MA60 / ATR14 有足够数据。
    """
    from backend.data.database import Price

    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date >= cutoff)
        .order_by(Price.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(
        [{"date": r.date, "open": r.open, "high": r.high,
          "low": r.low, "close": r.close, "volume": r.volume}
         for r in rows]
    ).set_index("date")


def sync_index_to_db(
    db,
    index_symbol: str = "sh000300",
    days: int = 365,
    *,
    fetch_cn_index_fn: Callable[..., pd.DataFrame],
) -> int:
    """
    拉取指数日线并写入 index_prices 表，跳过已存在的日期。
    返回新写入条数。
    """
    from backend.data.database import IndexPrice

    df = fetch_cn_index_fn(index_symbol, days=days)
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")
    existing = {
        r[0] for r in db.query(IndexPrice.date)
        .filter(IndexPrice.symbol == index_symbol).all()
    }
    records = [
        IndexPrice(
            symbol=index_symbol,
            date=d,
            close=float(row["close"]),
            change_pct=float(row["change_pct"]) if pd.notna(row.get("change_pct")) else None,
            source=source,
            fetched_at=fetched_at,
            adjustment=adjustment,
        )
        for d, row in df.iterrows()
        if d not in existing
    ]
    if records:
        db.bulk_save_objects(records)
        db.commit()
    return len(records)


def backfill_if_needed(
    symbol: str,
    market: str,
    db,
    years: int | None = None,
    refresh_today: bool = False,
    *,
    fetch_daily_fn: Callable[..., pd.DataFrame],
    backfill_years: int = BACKFILL_YEARS,
    backfill_threshold_days: int = BACKFILL_THRESHOLD_DAYS,
    refresh_window_days: int = REFRESH_WINDOW_DAYS,
) -> int:
    """
    检查该股历史数据是否充足。若最新记录距今超过阈值（或无记录），
    自动从 AkShare/yfinance 回填最多 BACKFILL_YEARS 年数据。

    refresh_today=True 时绕过阈值短路，强制重抓最近 REFRESH_WINDOW_DAYS 天并
    覆盖写入，用于盘前/盘后任务校正当日已有价格（避免被 provider 修正前的脏数据
    污染下游技术分/ATR/止损止盈）。

    返回新写入或更新的记录条数。
    """
    from backend.analysis.factors import add_all_factors
    from backend.data.database import Price, get_latest_price_date

    latest_date_str = get_latest_price_date(symbol, db)

    if latest_date_str:
        days_old = (date.today() - date.fromisoformat(latest_date_str)).days
        if days_old < backfill_threshold_days and not refresh_today:
            return 0
        fetch_days = max(days_old + 10, refresh_window_days + 2 if refresh_today else 0)
    else:
        fetch_days = (years or backfill_years) * 365 + 10

    df = fetch_daily_fn(symbol, market, days=fetch_days)
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")

    if df.empty:
        return 0

    df_factors = add_all_factors(df)

    if refresh_today and latest_date_str:
        window_start = (date.today() - timedelta(days=refresh_window_days)).isoformat()
        df_factors = df_factors[df_factors.index >= window_start]
    elif latest_date_str:
        df_factors = df_factors[df_factors.index > latest_date_str]

    if df_factors.empty:
        return 0

    if refresh_today:
        dates_to_replace = list(df_factors.index)
        db.query(Price).filter(
            Price.symbol == symbol,
            Price.date.in_(dates_to_replace),
        ).delete(synchronize_session=False)

    # M42/M58: build a rolling window of the last 10 *committed* closes for
    # each candidate row so the write-time adjustment-jump guard (up-splice
    # M42 + down-splice M58) has a baseline.  We initialise from existing DB
    # rows (already committed) and extend with rows we have already accepted
    # in this batch.  This means:
    #   - First N rows of a brand-new symbol have < 10 preceding closes →
    #     guard returns False (passes through) as documented in
    #     check_adjustment_basis_jump.
    #   - For refresh_today the deleted rows are gone before this loop runs,
    #     so the baseline comes from rows *outside* the refresh window — exactly
    #     the rows that were not contaminated.
    from backend.data.price_quality import (  # local import avoids circular at module level
        HFQ_JUMP_RATIO_THRESHOLD,
        check_adjustment_basis_jump,
    )

    preceding_window = 10
    # Seed the window from existing DB closes (up to preceding_window rows),
    # ordered ascending so we keep the most-recent ones at the end.
    seed_rows = (
        db.query(Price.close)
        .filter(Price.symbol == symbol)
        .order_by(Price.date.desc())
        .limit(preceding_window)
        .all()
    )
    # rows come back newest-first; reverse so list is oldest→newest
    preceding_closes: list[float] = [float(r.close) for r in reversed(seed_rows) if r.close]

    records = []
    rejected = 0
    for date_str, row in df_factors.iterrows():
        close_val = float(row["close"])
        # M42/M58 write-time guard: reject probable adjustment-basis-splice
        # rows, both the up-direction hfq-scale jump (M42) and the symmetric
        # down-direction splice (M58).
        if check_adjustment_basis_jump(close_val, preceding_closes):
            usable = [c for c in preceding_closes if c > 0]
            logger.warning(
                "M42/M58 adjustment-jump guard: rejected %s %s close=%.4f "
                "(preceding 10-day median=%.4f, threshold=%.1f×) — skipping row",
                symbol, date_str, close_val,
                _median(usable) if usable else 0,
                HFQ_JUMP_RATIO_THRESHOLD,
            )
            rejected += 1
            continue
        atr = row.get("atr14")
        records.append(Price(
            symbol=symbol,
            date=date_str,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=close_val,
            volume=float(row["volume"]),
            atr14=float(atr) if atr is not None and not pd.isna(atr) else None,
            source=source,
            fetched_at=fetched_at,
            adjustment=adjustment,
        ))
        # Slide the window forward with the accepted close.
        preceding_closes.append(close_val)
        if len(preceding_closes) > preceding_window:
            preceding_closes.pop(0)

    if rejected:
        logger.warning(
            "M42 hfq-jump guard: rejected %d/%d rows for %s",
            rejected,
            rejected + len(records),
            symbol,
        )

    db.bulk_save_objects(records)
    db.commit()
    return len(records)
