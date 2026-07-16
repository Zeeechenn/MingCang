"""TickFlow read-only data adapter and availability probe.

TickFlow stays disabled by default. When explicitly enabled, market.py registers
it as the preferred CN daily provider using forward_additive adjusted prices.
"""
from __future__ import annotations

import os
import threading
import time

import pandas as pd
import requests

from backend.config import settings

# 全局请求限速：tickflow 免费档对密集请求 429 敏感（批量刷价第 ~11 支起触发），
# 支间强制最小间隔从源头压平请求速率。0 可关闭。基线可用 TICKFLOW_MIN_REQUEST_INTERVAL
# 环境变量覆盖（兜底兼容旧用法），否则读 backend.config.settings.tickflow_min_request_interval。
_throttle_lock = threading.Lock()
_last_request_at = 0.0
_consecutive_429 = 0  # 连续 429 计数，成功（含非429错误）即清零


def _min_request_interval_base() -> float:
    """支间最小请求间隔基线：env var 优先，其次 settings。"""
    env_val = os.getenv("TICKFLOW_MIN_REQUEST_INTERVAL")
    if env_val is not None:
        return float(env_val)
    return float(settings.tickflow_min_request_interval)


def _effective_request_interval() -> float:
    """429 自适应退避：有效间隔 = base * 2**min(连续429次数,3)，上限 4.0 秒。

    这是缓解而非根治——2026-07-16 晚实测首轮 45 支仅 10 支新鲜，补救轮仍触发
    429，同时段 eastmoney 代理也故障；退避只能压低 tickflow 自身触发 429 的
    频率，压不住上游代理本身的不可用。
    """
    base = _min_request_interval_base()
    if base <= 0:
        return 0.0
    with _throttle_lock:
        n = _consecutive_429
    return min(base * (2 ** min(n, 3)), 4.0)


def _note_response_status(status_code: int | None) -> None:
    """收到 429 计数+1；其余状态（含成功）清零，驱动自适应退避。"""
    global _consecutive_429
    with _throttle_lock:
        if status_code == 429:
            _consecutive_429 += 1
        else:
            _consecutive_429 = 0


def _throttle() -> None:
    """Block until at least the effective (base + 429 backoff) interval has passed."""
    global _last_request_at
    interval = _effective_request_interval()
    if interval <= 0:
        return
    with _throttle_lock:
        wait = _last_request_at + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def tickflow_symbol(symbol: str, market: str) -> str:
    """Map a MingCang symbol/market pair to TickFlow's exchange suffix format."""
    normalized = str(symbol).strip().upper()
    if "." in normalized:
        return normalized

    market = market.upper()
    if market == "CN":
        if normalized.startswith(("43", "81", "82", "83", "87", "88", "92")):
            suffix = "BJ"
        elif normalized.startswith(("60", "68", "11", "51", "52", "56", "58")):
            suffix = "SH"
        else:
            suffix = "SZ"
        return f"{normalized}.{suffix}"
    if market == "US":
        return f"{normalized}.US"
    if market == "HK":
        return f"{normalized.zfill(5)}.HK"
    raise ValueError(f"unsupported market for TickFlow: {market}")


def _normalize_tickflow_klines(payload: dict) -> pd.DataFrame:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return pd.DataFrame()

    timestamps = data.get("timestamp") or []
    rows = []
    for idx, timestamp in enumerate(timestamps):
        trade_date = (
            pd.to_datetime(timestamp, unit="ms", utc=True)
            .tz_convert("Asia/Shanghai")
            .strftime("%Y-%m-%d")
        )
        row = {"date": trade_date}
        for col in ("open", "high", "low", "close", "volume"):
            values = data.get(col) or []
            row[col] = values[idx] if idx < len(values) else None
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows).set_index("date").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def fetch_tickflow_daily(
    symbol: str,
    market: str,
    days: int = 365,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float | None = None,
    adjust: str = "forward_additive",
) -> pd.DataFrame:
    """Fetch daily OHLCV bars from TickFlow without writing local state."""
    resolved_base_url = (base_url or settings.tickflow_base_url).rstrip("/")
    resolved_api_key = api_key if api_key is not None else settings.tickflow_api_key
    headers: dict[str, str] = {"x-api-key": resolved_api_key} if resolved_api_key else {}
    params: dict[str, str | int] = {
        "symbol": tickflow_symbol(symbol, market),
        "period": "1d",
        "count": max(1, min(int(days), 10000)),
        "adjust": adjust,
    }
    _throttle()
    resp = requests.get(
        f"{resolved_base_url}/v1/klines",
        headers=headers,
        params=params,
        timeout=timeout_seconds or settings.tickflow_timeout_seconds,
    )
    _note_response_status(resp.status_code)
    resp.raise_for_status()
    return _normalize_tickflow_klines(resp.json())


def probe_tickflow_daily(symbol: str = "600519", market: str = "CN", days: int = 30) -> dict:
    """Run an explicit side-effect-free TickFlow daily-bar probe."""
    started = time.perf_counter()
    mapped_symbol = None
    if not settings.tickflow_enabled:
        return {
            "ok": False,
            "enabled": False,
            "configured": bool(settings.tickflow_api_key),
            "symbol": symbol,
            "tickflow_symbol": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "rows": 0,
            "latest_date": None,
            "error": "TICKFLOW_ENABLED=false",
        }

    try:
        mapped_symbol = tickflow_symbol(symbol, market)
        df = fetch_tickflow_daily(symbol, market, days=days)
        return {
            "ok": not df.empty,
            "enabled": True,
            "configured": bool(settings.tickflow_api_key),
            "symbol": symbol,
            "tickflow_symbol": mapped_symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "rows": int(len(df)),
            "latest_date": str(df.index[-1]) if not df.empty else None,
            "error": None if not df.empty else "empty response",
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "configured": bool(settings.tickflow_api_key),
            "symbol": symbol,
            "tickflow_symbol": mapped_symbol,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "rows": 0,
            "latest_date": None,
            "error": str(exc),
        }
