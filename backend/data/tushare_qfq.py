"""Tushare qfq daily-bar adapter.

The legacy Tushare daily fetcher intentionally stays out of the production
fallback chain because ``pro.daily`` returns unadjusted prices.  This module
combines daily bars with ``adj_factor`` and emits StockSage's qfq-compatible
OHLCV shape.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, cast

import pandas as pd
import requests

from backend.config import settings

_ADJ_FACTOR_CACHE: dict[tuple[str, str, str], pd.DataFrame] = {}
_LAST_ADJ_FACTOR_CALL = 0.0


class TushareQfqError(RuntimeError):
    """Raised when Tushare qfq data cannot be fetched or normalized safely."""


def _cn_tushare_ts_code(symbol: str) -> str:
    if symbol.startswith(("60", "68", "11", "51", "52", "56", "58")):
        suffix = "SH"
    elif symbol.startswith(("43", "81", "82", "83", "87", "88", "92")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{symbol}.{suffix}"


def reset_tushare_qfq_cache() -> None:
    """Clear in-process Tushare qfq caches for tests and explicit probes."""
    global _LAST_ADJ_FACTOR_CALL
    _ADJ_FACTOR_CACHE.clear()
    _LAST_ADJ_FACTOR_CALL = 0.0


def _call_tushare(
    api_name: str,
    params: dict,
    fields: str,
    *,
    token: str,
    base_url: str,
    timeout_seconds: float,
) -> pd.DataFrame:
    payload = {
        "api_name": api_name,
        "token": token,
        "params": params,
        "fields": fields,
    }
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.post(base_url, json=cast(Any, payload), timeout=timeout_seconds)
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as exc:
        raise TushareQfqError(f"Tushare {api_name} HTTP request failed: {exc}") from exc
    except ValueError as exc:
        raise TushareQfqError(f"Tushare {api_name} returned invalid JSON") from exc

    if body.get("code") != 0:
        msg = body.get("msg") or "unknown Tushare error"
        raise TushareQfqError(f"Tushare {api_name} API error: code={body.get('code')} msg={msg}")
    data = body.get("data") or {}
    columns = data.get("fields") or []
    items = data.get("items") or []
    if not isinstance(columns, list) or not isinstance(items, list):
        raise TushareQfqError(f"Tushare {api_name} returned malformed data")
    return pd.DataFrame(items, columns=columns)


def _fetch_adj_factor(
    ts_code: str,
    start_date: str,
    end_date: str,
    *,
    token: str,
    base_url: str,
    timeout_seconds: float,
    min_interval_seconds: float,
) -> pd.DataFrame:
    global _LAST_ADJ_FACTOR_CALL
    cache_key = (ts_code, start_date, end_date)
    cached = _ADJ_FACTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    now = time.monotonic()
    wait_seconds = min_interval_seconds - (now - _LAST_ADJ_FACTOR_CALL)
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    df = _call_tushare(
        "adj_factor",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        "ts_code,trade_date,adj_factor",
        token=token,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    _LAST_ADJ_FACTOR_CALL = time.monotonic()
    _ADJ_FACTOR_CACHE[cache_key] = df.copy()
    return df


def _normalize_qfq(daily: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame:
    if daily.empty or adj.empty:
        return pd.DataFrame()
    missing_daily = {"trade_date", "open", "high", "low", "close", "vol"} - set(daily.columns)
    missing_adj = {"trade_date", "adj_factor"} - set(adj.columns)
    if missing_daily:
        raise TushareQfqError(f"Tushare daily missing fields: {sorted(missing_daily)}")
    if missing_adj:
        raise TushareQfqError(f"Tushare adj_factor missing fields: {sorted(missing_adj)}")

    bars = daily.copy()
    factors = adj[["trade_date", "adj_factor"]].copy()
    bars["trade_date"] = bars["trade_date"].astype(str)
    factors["trade_date"] = factors["trade_date"].astype(str)
    factors["adj_factor"] = pd.to_numeric(factors["adj_factor"], errors="coerce")
    merged = bars.merge(factors, on="trade_date", how="inner")
    if merged.empty:
        return pd.DataFrame()
    missing_dates = set(bars["trade_date"]) - set(merged["trade_date"])
    if missing_dates:
        sample = ", ".join(sorted(missing_dates)[:3])
        raise TushareQfqError(
            f"Tushare adj_factor missing for {len(missing_dates)} daily rows: {sample}"
        )

    latest_date = merged["trade_date"].max()
    latest_factor = merged.loc[merged["trade_date"] == latest_date, "adj_factor"].iloc[0]
    if pd.isna(latest_factor) or float(latest_factor) == 0:
        raise TushareQfqError("invalid latest Tushare adj_factor")

    ratio = pd.to_numeric(merged["adj_factor"], errors="coerce") / float(latest_factor)
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(merged["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(merged[column], errors="coerce") * ratio
    out["volume"] = pd.to_numeric(merged["vol"], errors="coerce")
    out = out.set_index("date").sort_index()
    return out[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def fetch_tushare_qfq_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """Fetch qfq-compatible A-share daily OHLCV bars from Tushare Pro."""
    if not settings.tushare_token:
        raise ValueError("TUSHARE_TOKEN is not configured; cannot fetch Tushare qfq daily bars")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    end_date = date.today().strftime("%Y%m%d")
    ts_code = _cn_tushare_ts_code(symbol)
    daily = _call_tushare(
        "daily",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        "ts_code,trade_date,open,high,low,close,vol",
        token=settings.tushare_token,
        base_url=settings.tushare_http_base_url,
        timeout_seconds=settings.tushare_timeout_seconds,
    )
    adj = _fetch_adj_factor(
        ts_code,
        start_date,
        end_date,
        token=settings.tushare_token,
        base_url=settings.tushare_http_base_url,
        timeout_seconds=settings.tushare_timeout_seconds,
        min_interval_seconds=settings.tushare_adj_factor_min_interval_seconds,
    )
    return _normalize_qfq(daily, adj)


def probe_tushare_qfq_daily(symbol: str = "600519", days: int = 30) -> dict:
    """Run a side-effect-free Tushare qfq probe without database writes."""
    started = time.perf_counter()
    if not settings.tushare_qfq_enabled:
        return {
            "ok": False,
            "enabled": False,
            "configured": bool(settings.tushare_token),
            "symbol": symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "rows": 0,
            "latest_date": None,
            "adjustment": "qfq",
            "error": "TUSHARE_QFQ_ENABLED=false",
        }
    try:
        df = fetch_tushare_qfq_daily(symbol, days=days)
        return {
            "ok": not df.empty,
            "enabled": True,
            "configured": bool(settings.tushare_token),
            "symbol": symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "rows": int(len(df)),
            "latest_date": str(df.index[-1]) if not df.empty else None,
            "adjustment": "qfq",
            "error": None if not df.empty else "empty response",
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "configured": bool(settings.tushare_token),
            "symbol": symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "rows": 0,
            "latest_date": None,
            "adjustment": "qfq",
            "error": str(exc),
        }
