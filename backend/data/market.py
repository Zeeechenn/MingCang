"""行情数据拉取：A股用 AkShare，美股用 yfinance"""
import time
import logging
import functools
import pandas as pd
import akshare as ak
import yfinance as yf
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def _retry(max_attempts: int = 3, delay: float = 1.0):
    """简单指数退避重试装饰器（AkShare/yfinance 偶发网络超时用）"""
    def decorator(fn):
        """Retry decorator factory."""
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            """Wrapped call with retry and exponential backoff."""
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = delay * (2 ** attempt)
                    logger.warning("%s 失败（第%d次），%.1fs后重试: %s",
                                   fn.__name__, attempt + 1, wait, e)
                    time.sleep(wait)
        return wrapper
    return decorator

BACKFILL_YEARS = 5          # 首次初始化回填年数
BACKFILL_THRESHOLD_DAYS = 1   # 最新数据距今超过此天数才触发回填（日常运营=1）


def _cn_market_prefix(symbol: str) -> str:
    """Return the east-money market prefix digit for a CN stock symbol."""
    return "1" if symbol[:2] in ("60", "68", "11") else "0"


def cn_yfinance_ticker(symbol: str) -> str:
    """Map an A-share symbol to a Yahoo Finance ticker suffix."""
    suffix = "SS" if symbol[:2] in ("60", "68", "11") else "SZ"
    return f"{symbol}.{suffix}"


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """拉取A股日线数据，返回 OHLCV DataFrame（index=date str）。"""
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    secid = f"{_cn_market_prefix(symbol)}.{symbol}"
    import subprocess as _sp, json as _json
    # eastmoney API 要求逗号不能 URL 编码（%2C 会触发空响应），直接拼 URL
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56"
        "&klt=101&fqt=1"
        f"&beg={start}&end=20500101"
        "&ut=7eea3edcaed734bea9cbfc24409ed989"
    )
    # curl 走 Clash TUN，绕开 Python requests 与 TUN 的 SSL 握手问题
    result = _sp.run(["curl", "-s", "--max-time", "10", url],
                     capture_output=True, text=True)
    if result.returncode != 0:
        raise ConnectionError(f"curl failed: {result.stderr}")
    data = _json.loads(result.stdout)
    klines = (data.get("data") or {}).get("klines") or []
    if not klines:
        raise ValueError(f"No kline data for {symbol}")
    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append({
            "date":   parts[0],
            "open":   float(parts[1]),
            "close":  float(parts[2]),
            "high":   float(parts[3]),
            "low":    float(parts[4]),
            "volume": float(parts[5]),
        })
    df_result = pd.DataFrame(rows).set_index("date")
    return df_result[["open", "high", "low", "close", "volume"]]


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_yfinance(symbol: str, days: int = 365) -> pd.DataFrame:
    """Fallback A-share daily data via Yahoo Finance suffixes."""
    ticker = yf.Ticker(cn_yfinance_ticker(symbol))
    df = ticker.history(period=f"{days}d", interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No yfinance data for {symbol}")
    df.index = df.index.strftime("%Y-%m-%d")
    df.index.name = "date"
    return df[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)


@_retry(max_attempts=3, delay=1.0)
def fetch_us_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """拉取美股日线数据"""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=f"{days}d", interval="1d", auto_adjust=True)
    df.index = df.index.strftime("%Y-%m-%d")
    df.index.name = "date"
    return df[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)


def fetch_daily(symbol: str, market: str, days: int = 365) -> pd.DataFrame:
    """Dispatch to the appropriate market data fetcher based on market."""
    from backend.data.providers import fetch_daily_with_fallback, register_daily_provider

    register_daily_provider("eastmoney_cn", {"CN"}, fetch_cn_daily)
    register_daily_provider("yfinance_cn", {"CN"}, fetch_cn_daily_yfinance)
    register_daily_provider("yfinance_us", {"US"}, fetch_us_daily)
    df, provider = fetch_daily_with_fallback(symbol, market, days)
    logger.debug("fetch_daily provider=%s symbol=%s market=%s rows=%d",
                 provider, symbol, market, len(df))
    return df


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_index(index_symbol: str = "sh000300", days: int = 365) -> pd.DataFrame:
    """
    拉取A股指数日线数据，默认沪深300。
    index_symbol: "sh000300"（沪深300）/ "sh000001"（上证）/ "sh000016"（上证50）
    """
    df = ak.stock_zh_index_daily(symbol=index_symbol)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = df[df["date"] >= cutoff].copy()
    df["change_pct"] = df["close"].pct_change() * 100
    return df[["date", "close", "change_pct"]].set_index("date")


def load_price_df(symbol: str, db, days: int = 200) -> pd.DataFrame:
    """
    从 Price 表读取历史行情，返回 OHLCV DataFrame（index=date str，升序）。
    days=200 确保 MA60 / ATR14 有足够数据。
    """
    from backend.data.database import Price
    from datetime import date, timedelta

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


def sync_index_to_db(db, index_symbol: str = "sh000300", days: int = 365) -> int:
    """
    拉取指数日线并写入 index_prices 表，跳过已存在的日期。
    返回新写入条数。
    """
    from backend.data.database import IndexPrice

    df = fetch_cn_index(index_symbol, days=days)
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
        )
        for d, row in df.iterrows()
        if d not in existing
    ]
    if records:
        db.bulk_save_objects(records)
        db.commit()
    return len(records)


REFRESH_WINDOW_DAYS = 5  # refresh_today=True 时覆盖回写的最近窗口


def backfill_if_needed(symbol: str, market: str, db, years: int | None = None,
                       refresh_today: bool = False) -> int:
    """
    检查该股历史数据是否充足。若最新记录距今超过阈值（或无记录），
    自动从 AkShare/yfinance 回填最多 BACKFILL_YEARS 年数据。

    refresh_today=True 时绕过阈值短路，强制重抓最近 REFRESH_WINDOW_DAYS 天并
    覆盖写入，用于盘前/盘后任务校正当日已有价格（避免被 provider 修正前的脏数据
    污染下游技术分/ATR/止损止盈）。

    返回新写入或更新的记录条数。
    """
    from backend.data.database import Price, get_latest_price_date
    from backend.analysis.factors import add_all_factors

    latest_date_str = get_latest_price_date(symbol, db)

    if latest_date_str:
        days_old = (date.today() - date.fromisoformat(latest_date_str)).days
        if days_old < BACKFILL_THRESHOLD_DAYS and not refresh_today:
            return 0
        fetch_days = max(days_old + 10, REFRESH_WINDOW_DAYS + 2 if refresh_today else 0)
    else:
        fetch_days = (years or BACKFILL_YEARS) * 365 + 10

    df = fetch_daily(symbol, market, days=fetch_days)

    if df.empty:
        return 0

    df_factors = add_all_factors(df)

    if refresh_today and latest_date_str:
        window_start = (date.today() - timedelta(days=REFRESH_WINDOW_DAYS)).isoformat()
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

    records = []
    for date_str, row in df_factors.iterrows():
        atr = row.get("atr14")
        records.append(Price(
            symbol=symbol,
            date=date_str,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            atr14=float(atr) if atr is not None and not pd.isna(atr) else None,
        ))

    db.bulk_save_objects(records)
    db.commit()
    return len(records)
