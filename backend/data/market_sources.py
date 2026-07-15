"""External market-data source adapters."""
import json
import subprocess
from datetime import date, timedelta

import akshare as ak
import pandas as pd
import yfinance as yf

from backend.config import settings
from backend.data.market_utils import (
    _cn_market_prefix,
    _normalize_ohlcv,
    _retry,
    _to_sina_tx_symbol,
    cn_tushare_ts_code,
    cn_yfinance_ticker,
    hk_yfinance_ticker,
)


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
def fetch_hk_daily_tickflow(symbol: str, days: int = 365) -> pd.DataFrame:
    """Hong Kong daily data via TickFlow split/dividend forward adjustment."""
    from backend.data.tickflow import fetch_tickflow_daily

    return fetch_tickflow_daily(symbol, "HK", days=days, adjust="forward")


@_retry(max_attempts=3, delay=1.0)
def fetch_us_daily_tickflow(symbol: str, days: int = 365) -> pd.DataFrame:
    """US daily data via TickFlow split/dividend forward adjustment."""
    from backend.data.tickflow import fetch_tickflow_daily

    return fetch_tickflow_daily(symbol, "US", days=days, adjust="forward")


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


def fetch_global_index_yfinance(index_symbol: str, days: int = 365) -> pd.DataFrame:
    """Fetch a HK/US benchmark index through Yahoo Finance."""
    ticker = yf.Ticker(index_symbol)
    df = ticker.history(period=f"{days}d", interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No yfinance index data for {index_symbol}")
    df.index = df.index.strftime("%Y-%m-%d")
    df.index.name = "date"
    out = df[["Close"]].rename(columns={"Close": "close"})
    out["change_pct"] = out["close"].pct_change() * 100
    return out


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
