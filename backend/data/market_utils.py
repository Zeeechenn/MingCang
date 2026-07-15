"""Shared helpers for market data adapters and facade orchestration."""
import functools
import importlib.util
import logging
import time
from datetime import UTC, datetime

import pandas as pd

logger = logging.getLogger("backend.data.market")


DAILY_PROVIDER_ADJUSTMENTS = {
    "tickflow_cn": "forward_additive",
    "tickflow_hk": "forward",
    "tickflow_us": "forward",
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
    "yfinance_index_hk": "auto_adjust",
    "yfinance_index_us": "auto_adjust",
}


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
                    logger.warning(
                        "%s 失败（第%d次），%.1fs后重试: %s",
                        fn.__name__,
                        attempt + 1,
                        wait,
                        e,
                    )
                    time.sleep(wait)
        return wrapper
    return decorator


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _attach_provenance_attrs(df: pd.DataFrame, *, provider: str, adjustment: str | None) -> pd.DataFrame:
    df.attrs["source"] = provider
    df.attrs["fetched_at"] = _utcnow_naive()
    df.attrs["adjustment"] = adjustment
    return df


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
