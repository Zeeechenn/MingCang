"""M54 news layer v2 clean out-of-sample harness.

This harness scores historical DB news through ``news_v2_score_from_db`` and
computes forward-return IC diagnostics. It does not import legacy sentiment
analysis, postmarket jobs, or M52 variant/provider code.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data.database import SessionLocal
from backend.data.news_fusion import DEGRADED
from backend.data.news_layer_v2 import news_v2_score_from_db
from backend.llm.base import LLMProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test3_universe_50.json"
DEFAULT_OOS_NS = "oos_news_v2"
DEFAULT_LOOKBACK_DAYS = 3
HORIZONS = (3, 5)
N_BUCKETS = 5
MIN_SAMPLE_WINDOWS = 25
MIN_NON_OVERLAP_IC_DAYS = 20

SessionFactory = Callable[[], Session]


def _set_oos_namespace(ns: str = DEFAULT_OOS_NS) -> None:
    os.environ["SENTIMENT_CACHE_NS"] = ns


def _safe_spearman(xs: list[float], ys: list[float]) -> float | None:
    try:
        import pandas as pd
    except ImportError:
        return None
    a = pd.Series(xs, dtype=float)
    b = pd.Series(ys, dtype=float)
    df = pd.DataFrame({"a": a, "b": b}).replace([float("inf"), float("-inf")], float("nan")).dropna()
    if len(df) < 3 or df["a"].nunique() < 2 or df["b"].nunique() < 2:
        return None
    corr = df["a"].rank(method="average").corr(df["b"].rank(method="average"))
    if corr is None:
        return None
    if not math.isfinite(float(corr)):
        return None
    return float(corr)


def _summarize_ic(ic_series: list[float]) -> dict[str, Any]:
    import numpy as np

    arr = [v for v in ic_series if v is not None and math.isfinite(v)]
    if not arr:
        return {
            "ic_days": 0,
            "ic_mean": None,
            "ic_std": None,
            "icir": None,
            "ic_positive_rate": None,
        }
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else float("nan")
    icir = round(mean / std, 4) if std and math.isfinite(std) and std > 0 else None
    return {
        "ic_days": len(arr),
        "ic_mean": round(mean, 6),
        "ic_std": round(std, 6) if math.isfinite(std) else None,
        "icir": icir,
        "ic_positive_rate": round(float(sum(1 for v in arr if v > 0) / len(arr)), 4),
    }


def _is_monotonic_buckets(bucket_means: list[float]) -> bool:
    """True when bucket means are monotonically increasing and top-bottom > 0."""
    if len(bucket_means) < 3:
        return False
    for i in range(1, len(bucket_means)):
        if bucket_means[i] < bucket_means[i - 1]:
            return False
    return bucket_means[-1] > bucket_means[0]


def _load_prices(
    symbols: list[str],
    start: str,
    end: str,
    *,
    session_factory: SessionFactory = SessionLocal,
) -> dict[str, dict[str, float]]:
    """Return {symbol: {date_str: close}} for the given window + forward buffer."""
    if not symbols:
        return {}
    db = session_factory()
    try:
        buf_end = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=15)).strftime("%Y-%m-%d")
        placeholders = ", ".join(f":s{i}" for i in range(len(symbols)))
        params: dict[str, Any] = {"start": start, "end": buf_end}
        params.update({f"s{i}": s for i, s in enumerate(symbols)})
        rows = db.execute(
            text(
                f"SELECT symbol, date, close FROM prices "
                f"WHERE symbol IN ({placeholders}) AND date >= :start AND date <= :end "
                f"ORDER BY symbol, date"
            ),
            params,
        ).fetchall()
        result: dict[str, dict[str, float]] = {}
        for sym, d, close in rows:
            if close is None:
                continue
            result.setdefault(str(sym), {})[str(d)] = float(close)
        return result
    finally:
        db.close()


def _forward_return(prices: dict[str, float], signal_date: str, horizon: int) -> float | None:
    """Return horizon-day forward return for a symbol's price dict, or None."""
    sorted_dates = sorted(prices.keys())
    try:
        idx = sorted_dates.index(signal_date)
    except ValueError:
        candidates = [d for d in sorted_dates if d >= signal_date]
        if not candidates:
            return None
        idx = sorted_dates.index(candidates[0])
    target_idx = idx + horizon
    if target_idx >= len(sorted_dates):
        return None
    base = prices[sorted_dates[idx]]
    fwd = prices[sorted_dates[target_idx]]
    if base <= 0:
        return None
    ret = fwd / base - 1.0
    return max(-0.30, min(0.30, ret))


def _iter_signal_dates(start: str, end: str) -> list[str]:
    out: list[str] = []
    cur = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while cur <= end_dt:
        if cur.weekday() < 5:
            out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def _load_universe(path: Path, *, limit: int | None = None) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("stocks", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"universe JSON must contain a list or stocks list: {path}")

    stocks: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip()
        name = str(row.get("name") or symbol).strip()
        if symbol:
            stocks.append({"symbol": symbol, "name": name or symbol})
        if limit is not None and len(stocks) >= limit:
            break
    return stocks


def _stride_dates(dates: Sequence[Any], horizon: int) -> set[Any]:
    return {date for index, date in enumerate(sorted(dates)) if index % horizon == 0}


def _metrics_for_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    if not records:
        empty_quantile = {
            "n_buckets": 0,
            "bucket_means": [],
            "top_bottom": None,
            "monotonic": False,
        }
        return {
            f"h{horizon}d": {**_summarize_ic([]), "quantile": dict(empty_quantile)}
            for horizon in HORIZONS
        }

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    metrics_by_horizon: dict[str, Any] = {}

    for horizon in HORIZONS:
        fwd_col = f"fwd_{horizon}d"
        sub = df[["date", "symbol", "score", fwd_col]].replace([np.inf, -np.inf], np.nan)
        sub = sub.dropna(subset=["score", fwd_col])

        stride_dates = _stride_dates(sub["date"].drop_duplicates().tolist(), horizon)
        ic_series: list[float] = []
        bucket_rows: list[dict[str, Any]] = []
        for _dt, grp in sub[sub["date"].isin(stride_dates)].groupby("date", sort=True):
            grp = grp.dropna(subset=["score", fwd_col])
            if len(grp) < 3:
                continue
            corr = _safe_spearman(grp["score"].tolist(), grp[fwd_col].tolist())
            if corr is not None:
                ic_series.append(corr)

            if len(grp) >= N_BUCKETS:
                try:
                    grp = grp.copy()
                    grp["_bucket"] = pd.qcut(
                        grp["score"].rank(method="first"),
                        N_BUCKETS,
                        labels=False,
                        duplicates="drop",
                    )
                    for bucket, bucket_group in grp.groupby("_bucket", sort=True):
                        bucket_rows.append(
                            {"bucket": int(bucket), "ret": float(bucket_group[fwd_col].mean())}
                        )
                except Exception:
                    pass

        summary = _summarize_ic(ic_series)
        if bucket_rows:
            bdf = pd.DataFrame(bucket_rows).groupby("bucket")["ret"].mean().sort_index()
            bucket_means = bdf.tolist()
            monotonic = _is_monotonic_buckets(bucket_means)
            top_bottom = (
                round(float(bucket_means[-1] - bucket_means[0]), 6)
                if len(bucket_means) >= 2
                else None
            )
            quantile_summary = {
                "n_buckets": len(bucket_means),
                "bucket_means": [round(float(v), 6) for v in bucket_means],
                "top_bottom": top_bottom,
                "monotonic": monotonic,
            }
        else:
            quantile_summary = {
                "n_buckets": 0,
                "bucket_means": [],
                "top_bottom": None,
                "monotonic": False,
            }

        metrics_by_horizon[f"h{horizon}d"] = {**summary, "quantile": quantile_summary}

    return metrics_by_horizon


def _gate_blockers(metrics: dict[str, Any], total_windows: int) -> list[str]:
    blockers: list[str] = []
    for hkey in ("h3d", "h5d"):
        metric = metrics.get(hkey, {})
        ic_mean = metric.get("ic_mean")
        icir = metric.get("icir")
        ic_days = int(metric.get("ic_days") or 0)
        monotonic = bool(metric.get("quantile", {}).get("monotonic", False))
        if ic_days < MIN_NON_OVERLAP_IC_DAYS:
            blockers.append(
                f"{hkey}: insufficient non-overlap IC days "
                f"({ic_days} < {MIN_NON_OVERLAP_IC_DAYS})"
            )
        if ic_mean is None or ic_mean < 0.04:
            blockers.append(f"{hkey}: IC mean {ic_mean} < 0.04 floor")
        if icir is None or icir < 0.40:
            blockers.append(f"{hkey}: ICIR {icir} < 0.40 floor")
        if not monotonic:
            blockers.append(f"{hkey}: bucket monotonicity not satisfied")
    if total_windows < MIN_SAMPLE_WINDOWS:
        blockers.append(
            f"insufficient sample: only {total_windows} scored (symbol, date) pairs"
        )
    return blockers


class _MockProvider(LLMProvider):
    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        sentiment = 0.0
        if any(term in prompt for term in ("中标", "利好", "增长", "回购", "获批")):
            sentiment += 0.55
        if any(term in prompt for term in ("处罚", "利空", "亏损", "下滑", "减持")):
            sentiment -= 0.55
        return {
            "relevance": 0.86,
            "sentiment": max(-1.0, min(1.0, sentiment)),
            "materiality": 0.82,
            "horizon": "short",
            "event_type": "contract",
            "catalysts": ["mock_provider"],
            "risks": [],
            "confidence": 0.78,
        }


def _install_mock_provider() -> None:
    import backend.data.news_extraction as extraction

    provider = _MockProvider()
    extraction.get_provider = lambda: provider


def run_oos(
    symbols: list[str],
    start: str,
    end: str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    tier: str = "capable",
    out: Path | None = None,
    db: Session | None = None,
    session_factory: SessionFactory = SessionLocal,
    mock: bool = False,
) -> dict[str, Any]:
    _set_oos_namespace()
    if mock:
        _install_mock_provider()

    prices_by_symbol = _load_prices(symbols, start, end, session_factory=session_factory)
    owns_db = db is None
    active_db = db or session_factory()
    records: list[dict[str, Any]] = []
    skipped_degraded = 0

    try:
        for sig_date in _iter_signal_dates(start, end):
            as_of = datetime.strptime(f"{sig_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
            for symbol in symbols:
                signal = news_v2_score_from_db(
                    symbol,
                    as_of,
                    lookback_days,
                    active_db,
                    tier=tier,
                )
                if DEGRADED in signal.degradation_flags:
                    skipped_degraded += 1
                    continue

                row: dict[str, Any] = {
                    "symbol": symbol,
                    "date": sig_date,
                    "score": float(signal.composite),
                    "confidence": float(signal.confidence),
                    "degradation_flags": list(signal.degradation_flags),
                }
                prices = prices_by_symbol.get(symbol, {})
                for horizon in HORIZONS:
                    row[f"fwd_{horizon}d"] = _forward_return(prices, sig_date, horizon)
                records.append(row)
    finally:
        if owns_db:
            active_db.close()

    metrics = _metrics_for_records(records)
    gate_blockers = _gate_blockers(metrics, len(records))
    status = "ok" if not gate_blockers else ("no_data" if not records else "gate_blocked")
    result: dict[str, Any] = {
        "status": status,
        "n_symbols": len(symbols),
        "n_windows": len(records),
        "skipped_degraded": skipped_degraded,
        "metrics": metrics,
        "gate_blockers": gate_blockers
        or ["no_data: no non-degraded (symbol, date) pairs produced scores"],
        "meta": {
            "tool": "backend.tools.m54_news_v2_oos",
            "oos_namespace": os.environ.get("SENTIMENT_CACHE_NS", ""),
            "start": start,
            "end": end,
            "lookback_days": lookback_days,
            "tier": tier,
            "horizons": list(HORIZONS),
            "n_buckets": N_BUCKETS,
            "min_non_overlap_ic_days": MIN_NON_OVERLAP_IC_DAYS,
            "min_sample_windows": MIN_SAMPLE_WINDOWS,
            "mock": mock,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M54 news layer v2 clean OOS harness.")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--start", required=True, help="Inclusive signal start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Inclusive signal end date YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--tier", default="capable")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mock", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stocks = _load_universe(args.universe, limit=args.limit)
    symbols = [stock["symbol"] for stock in stocks]
    result = run_oos(
        symbols,
        args.start,
        args.end,
        lookback_days=args.lookback,
        tier=args.tier,
        out=args.out,
        mock=args.mock,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
