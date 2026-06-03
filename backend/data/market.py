"""行情数据拉取：A股多源 fallback，美股用 yfinance."""
import functools
import importlib.util
import json
import logging
import subprocess
import time
from datetime import UTC, date, datetime, timedelta

import akshare as ak
import pandas as pd
import yfinance as yf

from backend.config import settings
from backend.data.providers import (
    fetch_daily_with_fallback,
    fetch_index_with_fallback,
    register_daily_provider,
    register_index_provider,
)

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
DAILY_PROVIDER_ADJUSTMENTS = {
    "tickflow_cn": "forward_additive",
    "akshare_sina_cn": "qfq",
    "efinance_cn": "qfq",
    "eastmoney_cn": "qfq",
    "akshare_em_cn": "qfq",
    "tushare_qfq_cn": "qfq",
    "yfinance_hk": "auto_adjust",
    "yfinance_us": "auto_adjust",
}
INDEX_PROVIDER_ADJUSTMENTS = {
    "akshare_index_cn": "index_unadjusted",
    "eastmoney_index_cn": "index_unadjusted",
    "efinance_index_cn": "index_unadjusted",
    "yfinance_index_cn": "auto_adjust",
}


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _attach_provenance_attrs(df: pd.DataFrame, *, provider: str, adjustment: str | None) -> pd.DataFrame:
    df.attrs["source"] = provider
    df.attrs["fetched_at"] = _utcnow_naive()
    df.attrs["adjustment"] = adjustment
    return df


def register_default_market_providers() -> None:
    """Register default daily/index providers without fetching remote data."""
    if settings.tickflow_enabled and settings.tickflow_api_key:
        register_daily_provider("tickflow_cn", {"CN"}, fetch_cn_daily_tickflow, priority=-10, cooldown_seconds=30)
    register_daily_provider("akshare_sina_cn", {"CN"}, fetch_cn_daily_akshare_sina, priority=0, cooldown_seconds=30)
    if _efinance_available():
        register_daily_provider("efinance_cn", {"CN"}, fetch_cn_daily_efinance, priority=10, cooldown_seconds=60)
    register_daily_provider("eastmoney_cn", {"CN"}, fetch_cn_daily, priority=20, cooldown_seconds=60)
    register_daily_provider("akshare_em_cn", {"CN"}, fetch_cn_daily_akshare_em, priority=30, cooldown_seconds=60)
    if settings.tushare_qfq_enabled and settings.tushare_token:
        register_daily_provider("tushare_qfq_cn", {"CN"}, fetch_cn_daily_tushare_qfq, priority=50, cooldown_seconds=120)
    # M19.2: yfinance 对 A 股是后复权含分红再投，与其余源 qfq 口径冲突，不进入 CN fallback。
    # akshare_tx 当前返回结构缺 volume，暂不进入 CN 生产 fallback；保留函数供手动调试。
    register_daily_provider("yfinance_hk", {"HK"}, fetch_hk_daily, priority=90, cooldown_seconds=120)
    register_daily_provider("yfinance_us", {"US"}, fetch_us_daily, priority=90, cooldown_seconds=120)

    register_index_provider("akshare_index_cn", fetch_cn_index_akshare, priority=0, cooldown_seconds=60)
    register_index_provider("eastmoney_index_cn", fetch_cn_index_eastmoney, priority=10, cooldown_seconds=60)
    if _efinance_available():
        register_index_provider("efinance_index_cn", fetch_cn_index_efinance, priority=20, cooldown_seconds=60)
    register_index_provider("yfinance_index_cn", fetch_cn_index_yfinance, priority=90, cooldown_seconds=120)


def _cn_market_prefix(symbol: str) -> str:
    """Return the east-money market prefix digit for a CN stock symbol."""
    return "1" if symbol[:2] in ("60", "68", "11") else "0"


def _to_sina_tx_symbol(symbol: str) -> str:
    """Return sh/sz/bj-prefixed A-share symbol for AkShare Sina/Tencent endpoints."""
    if symbol.startswith(("60", "68", "11", "51", "52", "56", "58")):
        return f"sh{symbol}"
    if symbol.startswith(("43", "81", "82", "83", "87", "88", "92")):
        return f"bj{symbol}"
    return f"sz{symbol}"


def cn_yfinance_ticker(symbol: str) -> str:
    """Map an A-share symbol to a Yahoo Finance ticker suffix."""
    suffix = "SS" if symbol[:2] in ("60", "68", "11") else "SZ"
    return f"{symbol}.{suffix}"


def hk_yfinance_ticker(symbol: str) -> str:
    """Map a Hong Kong stock code to Yahoo Finance ticker format."""
    normalized = str(symbol).strip().upper()
    if normalized.endswith(".HK"):
        code = normalized[:-3]
    else:
        code = normalized
    if code.isdigit():
        if len(code) == 5 and code.startswith("0"):
            code = code[-4:]
        elif len(code) < 4:
            code = code.zfill(4)
    return f"{code}.HK"


def cn_tushare_ts_code(symbol: str) -> str:
    """Map an A-share symbol to Tushare ts_code format."""
    if symbol.startswith(("60", "68", "11", "51", "52", "56", "58")):
        suffix = "SH"
    elif symbol.startswith(("43", "81", "82", "83", "87", "88", "92")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{symbol}.{suffix}"


def _efinance_available() -> bool:
    """Return whether the optional efinance fallback dependency is installed."""
    return importlib.util.find_spec("efinance") is not None


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common Chinese/English OHLCV columns to index=date str."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out = out.rename(columns={
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "trade_date": "date",
        "vol": "volume",
    })
    if "date" not in out.columns:
        out = out.reset_index().rename(columns={"index": "date"})
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.set_index("date").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in out.columns:
            raise ValueError(f"missing OHLCV column: {col}")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def fetch_cn_daily_efinance(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share daily data via efinance/Eastmoney wrapper."""
    import efinance as ef

    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    df = ef.stock.get_quote_history(
        stock_codes=symbol,
        beg=start,
        end="20500101",
        klt=101,
        fqt=1,
    )
    return _normalize_ohlcv(df)


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """拉取A股日线数据，返回 OHLCV DataFrame（index=date str）。"""
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    secid = f"{_cn_market_prefix(symbol)}.{symbol}"
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
    result = subprocess.run(["curl", "-s", "--max-time", "10", url],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise ConnectionError(f"curl failed: {result.stderr}")
    if not result.stdout:
        raise ConnectionError("curl returned empty body")
    data = json.loads(result.stdout)
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
def fetch_cn_daily_akshare_em(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share daily data via AkShare Eastmoney endpoint."""
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start,
        end_date="20500101",
        adjust="qfq",
    )
    return _normalize_ohlcv(df)


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_akshare_sina(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share daily data via AkShare Sina endpoint."""
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_daily(
        symbol=_to_sina_tx_symbol(symbol),
        start_date=start,
        end_date="20500101",
        adjust="qfq",
    )
    return _normalize_ohlcv(df)


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_akshare_tx(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share daily data via AkShare Tencent endpoint."""
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist_tx(
        symbol=_to_sina_tx_symbol(symbol),
        start_date=start,
        end_date="20500101",
        adjust="qfq",
    )
    return _normalize_ohlcv(df)


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_tushare(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share unadjusted daily data via Tushare Pro; not used in fallback until qfq conversion exists."""
    if not settings.tushare_token:
        raise ValueError("TUSHARE_TOKEN is not configured")
    try:
        import tushare as ts
    except ImportError:
        raise RuntimeError("tushare 包未安装，运行：pip install tushare") from None

    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    pro = ts.pro_api(settings.tushare_token)
    df = pro.daily(
        ts_code=cn_tushare_ts_code(symbol),
        start_date=start,
        end_date=end,
        fields="trade_date,open,high,low,close,vol",
    )
    return _normalize_ohlcv(df)


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_tickflow(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share daily data via TickFlow forward_additive adjustment."""
    if not settings.tickflow_enabled:
        raise ValueError("TICKFLOW_ENABLED is false")
    if not settings.tickflow_api_key:
        raise ValueError("TICKFLOW_API_KEY is not configured")

    from backend.data.tickflow import fetch_tickflow_daily

    return fetch_tickflow_daily(
        symbol,
        "CN",
        days=days,
        adjust="forward_additive",
    )


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_tushare_qfq(symbol: str, days: int = 365) -> pd.DataFrame:
    """A-share qfq daily data via Tushare Pro daily + adj_factor."""
    if not settings.tushare_qfq_enabled:
        raise ValueError("TUSHARE_QFQ_ENABLED is false")

    from backend.data.tushare_qfq import fetch_tushare_qfq_daily

    return fetch_tushare_qfq_daily(symbol, days=days)


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_daily_yfinance(symbol: str, days: int = 365) -> pd.DataFrame:
    """Yahoo Finance A-share daily data。

    yfinance 的 `auto_adjust=True` 返回后复权含分红再投，与其余 CN 源
    （efinance/eastmoney/akshare 全部 qfq）口径不一致，会导致除权日 OHLC
    与 ATR/技术分错位。仅保留函数供手动调试，**不再注册到 CN fallback**。
    """
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


@_retry(max_attempts=3, delay=1.0)
def fetch_hk_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """Fetch Hong Kong stock daily data via Yahoo Finance."""
    ticker = yf.Ticker(hk_yfinance_ticker(symbol))
    df = ticker.history(period=f"{days}d", interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No yfinance data for HK symbol {symbol}")
    df.index = df.index.strftime("%Y-%m-%d")
    df.index.name = "date"
    return df[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)


def fetch_daily(symbol: str, market: str, days: int = 365) -> pd.DataFrame:
    """Dispatch to the appropriate market data fetcher based on market."""
    register_default_market_providers()
    df, provider = fetch_daily_with_fallback(symbol, market, days)
    _attach_provenance_attrs(
        df,
        provider=provider,
        adjustment=DAILY_PROVIDER_ADJUSTMENTS.get(provider),
    )
    logger.debug("fetch_daily provider=%s symbol=%s market=%s rows=%d",
                 provider, symbol, market, len(df))
    return df


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_index_akshare(index_symbol: str = "sh000300", days: int = 365) -> pd.DataFrame:
    """Fetch A-share index daily data via AkShare."""
    df = ak.stock_zh_index_daily(symbol=index_symbol)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = df[df["date"] >= cutoff].copy()
    df["change_pct"] = df["close"].pct_change() * 100
    return df[["date", "close", "change_pct"]].set_index("date")


def _eastmoney_index_secid(index_symbol: str) -> str:
    code = index_symbol[2:] if index_symbol[:2].lower() in {"sh", "sz"} else index_symbol
    market = "1" if index_symbol.lower().startswith("sh") else "0"
    return f"{market}.{code}"


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_index_eastmoney(index_symbol: str = "sh000300", days: int = 365) -> pd.DataFrame:
    """Fetch A-share index daily data via Eastmoney kline endpoint."""
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={_eastmoney_index_secid(index_symbol)}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56"
        "&klt=101&fqt=1"
        f"&beg={start}&end=20500101"
        "&ut=7eea3edcaed734bea9cbfc24409ed989"
    )
    result = subprocess.run(["curl", "-s", "--max-time", "10", url],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise ConnectionError(f"curl failed: {result.stderr}")
    if not result.stdout:
        raise ConnectionError("curl returned empty body")
    data = json.loads(result.stdout)
    klines = (data.get("data") or {}).get("klines") or []
    if not klines:
        raise ValueError(f"No index kline data for {index_symbol}")
    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append({"date": parts[0], "close": float(parts[2])})
    df = pd.DataFrame(rows).set_index("date")
    df["change_pct"] = df["close"].pct_change() * 100
    return df[["close", "change_pct"]]


def fetch_cn_index_efinance(index_symbol: str = "sh000300", days: int = 365) -> pd.DataFrame:
    """Fetch A-share index daily data via efinance."""
    import efinance as ef

    code = index_symbol[2:] if index_symbol[:2].lower() in {"sh", "sz"} else index_symbol
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    df = ef.stock.get_quote_history(stock_codes=code, beg=start, end="20500101", klt=101, fqt=1)
    normalized = _normalize_ohlcv(df)
    out = normalized[["close"]].copy()
    out["change_pct"] = out["close"].pct_change() * 100
    return out


@_retry(max_attempts=3, delay=1.0)
def fetch_cn_index_yfinance(index_symbol: str = "sh000300", days: int = 365) -> pd.DataFrame:
    """Last-resort A-share index data via Yahoo Finance."""
    code = index_symbol[2:] if index_symbol[:2].lower() in {"sh", "sz"} else index_symbol
    suffix = "SS" if index_symbol.lower().startswith("sh") else "SZ"
    ticker = yf.Ticker(f"{code}.{suffix}")
    df = ticker.history(period=f"{days}d", interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No yfinance index data for {index_symbol}")
    df.index = df.index.strftime("%Y-%m-%d")
    df.index.name = "date"
    out = df[["Close"]].rename(columns={"Close": "close"})
    out["change_pct"] = out["close"].pct_change() * 100
    return out


def fetch_cn_index(index_symbol: str = "sh000300", days: int = 365) -> pd.DataFrame:
    """
    拉取A股指数日线数据，默认沪深300。
    index_symbol: "sh000300"（沪深300）/ "sh000001"（上证）/ "sh000016"（上证50）
    """
    register_default_market_providers()
    df, provider = fetch_index_with_fallback(index_symbol, days)
    _attach_provenance_attrs(
        df,
        provider=provider,
        adjustment=INDEX_PROVIDER_ADJUSTMENTS.get(provider),
    )
    logger.debug("fetch_cn_index provider=%s index=%s rows=%d", provider, index_symbol, len(df))
    return df


def load_price_df(symbol: str, db, days: int = 200) -> pd.DataFrame:
    """
    从 Price 表读取历史行情，返回 OHLCV DataFrame（index=date str，升序）。
    days=200 确保 MA60 / ATR14 有足够数据。
    """
    from datetime import date, timedelta

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


def sync_index_to_db(db, index_symbol: str = "sh000300", days: int = 365) -> int:
    """
    拉取指数日线并写入 index_prices 表，跳过已存在的日期。
    返回新写入条数。
    """
    from backend.data.database import IndexPrice

    df = fetch_cn_index(index_symbol, days=days)
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
    from backend.analysis.factors import add_all_factors
    from backend.data.database import Price, get_latest_price_date

    latest_date_str = get_latest_price_date(symbol, db)

    if latest_date_str:
        days_old = (date.today() - date.fromisoformat(latest_date_str)).days
        if days_old < BACKFILL_THRESHOLD_DAYS and not refresh_today:
            return 0
        fetch_days = max(days_old + 10, REFRESH_WINDOW_DAYS + 2 if refresh_today else 0)
    else:
        fetch_days = (years or BACKFILL_YEARS) * 365 + 10

    df = fetch_daily(symbol, market, days=fetch_days)
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")

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

    # M42: build a rolling window of the last 10 *committed* closes for each
    # candidate row so the write-time hfq guard has a baseline.  We initialise
    # from existing DB rows (already committed) and extend with rows we have
    # already accepted in this batch.  This means:
    #   - First N rows of a brand-new symbol have < 10 preceding closes →
    #     guard returns False (passes through) as documented in
    #     check_adjustment_basis_jump.
    #   - For refresh_today the deleted rows are gone before this loop runs,
    #     so the baseline comes from rows *outside* the refresh window — exactly
    #     the rows that were not contaminated.
    from statistics import median as _median

    from backend.data.price_quality import (  # local import avoids circular at module level
        HFQ_JUMP_RATIO_THRESHOLD,
        check_adjustment_basis_jump,
    )

    _PRECEDING_WINDOW = 10
    # Seed the window from existing DB closes (up to _PRECEDING_WINDOW rows),
    # ordered ascending so we keep the most-recent ones at the end.
    _seed_rows = (
        db.query(Price.close)
        .filter(Price.symbol == symbol)
        .order_by(Price.date.desc())
        .limit(_PRECEDING_WINDOW)
        .all()
    )
    # rows come back newest-first; reverse so list is oldest→newest
    _preceding_closes: list[float] = [float(r.close) for r in reversed(_seed_rows) if r.close]

    records = []
    _rejected = 0
    for date_str, row in df_factors.iterrows():
        close_val = float(row["close"])
        # M42 write-time guard: reject probable hfq-contaminated rows.
        if check_adjustment_basis_jump(close_val, _preceding_closes):
            _usable = [c for c in _preceding_closes if c > 0]
            logger.warning(
                "M42 hfq-jump guard: rejected %s %s close=%.4f "
                "(preceding 10-day median=%.4f, threshold=%.1f×) — skipping row",
                symbol, date_str, close_val,
                _median(_usable) if _usable else 0,
                HFQ_JUMP_RATIO_THRESHOLD,
            )
            _rejected += 1
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
        _preceding_closes.append(close_val)
        if len(_preceding_closes) > _PRECEDING_WINDOW:
            _preceding_closes.pop(0)

    if _rejected:
        logger.warning("M42 hfq-jump guard: rejected %d/%d rows for %s", _rejected, _rejected + len(records), symbol)

    db.bulk_save_objects(records)
    db.commit()
    return len(records)
