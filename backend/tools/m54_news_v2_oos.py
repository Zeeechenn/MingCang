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
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.analysis.sentiment import analyze_news
from backend.data.database import SessionLocal
from backend.data.news_fusion import DEGRADED
from backend.data.news_layer_v2 import PYRAMID_NOT_TRIGGERED, news_v2_score_from_db
from backend.llm.base import LLMProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test3_universe_50.json"
DEFAULT_OOS_NS = "oos_news_v2"
DEFAULT_VARIANT_NS = {
    "v2": DEFAULT_OOS_NS,
    "legacy-fast": "oos_legacy_fast",
    "legacy-capable": "oos_legacy_capable",
}
DEFAULT_LOOKBACK_DAYS = 3
HORIZONS = (3, 5)
N_BUCKETS = 5
MIN_SAMPLE_WINDOWS = 25
MIN_NON_OVERLAP_IC_DAYS = 20

# Degradation flags that must never feed the IC computation. DEGRADED covers
# the pre-existing low-confidence/thin-evidence fallback path; PYRAMID_NOT_TRIGGERED
# covers M54 stage-7 pyramid windows that fell through to a reused/fallback score
# without a fresh LLM call (only ever set when news_v2_pyramid_enabled=True, so
# non-pyramid legs never see it). Any window carrying either flag is excluded
# from IC/quantile diagnostics, though it may still be cached for reuse.
EXCLUDE_FROM_IC = {DEGRADED, PYRAMID_NOT_TRIGGERED}

SessionFactory = Callable[[], Session]
Variant = Literal["v2", "legacy-fast", "legacy-capable"]


def _set_oos_namespace(ns: str = DEFAULT_OOS_NS) -> None:
    os.environ["SENTIMENT_CACHE_NS"] = ns


def _ensure_score_cache_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS m54_oos_score_cache (
                namespace TEXT NOT NULL,
                symbol TEXT NOT NULL,
                sig_date TEXT NOT NULL,
                lookback_days INTEGER NOT NULL,
                tier TEXT NOT NULL,
                composite REAL NOT NULL,
                news_score REAL,
                flow_score REAL,
                confidence REAL NOT NULL,
                degradation_flags TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (namespace, symbol, sig_date, lookback_days, tier)
            )
            """
        )
    )


def _score_cache_get(
    db: Session,
    *,
    namespace: str,
    symbol: str,
    sig_date: str,
    lookback_days: int,
    tier: str,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            SELECT composite, news_score, flow_score, confidence, degradation_flags
            FROM m54_oos_score_cache
            WHERE namespace = :namespace
              AND symbol = :symbol
              AND sig_date = :sig_date
              AND lookback_days = :lookback_days
              AND tier = :tier
            """
        ),
        {
            "namespace": namespace,
            "symbol": symbol,
            "sig_date": sig_date,
            "lookback_days": lookback_days,
            "tier": tier,
        },
    ).fetchone()
    if row is None:
        return None

    data = row._mapping
    flags_raw = str(data["degradation_flags"] or "[]")
    try:
        flags = json.loads(flags_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(flags, list):
        return None
    return {
        "score": float(data["composite"]),
        "news_score": (
            None if data["news_score"] is None else float(data["news_score"])
        ),
        "flow_score": (
            None if data["flow_score"] is None else float(data["flow_score"])
        ),
        "confidence": float(data["confidence"]),
        "degradation_flags": [str(flag) for flag in flags],
    }


def _score_is_cacheable(score: dict[str, Any]) -> bool:
    flags = score.get("degradation_flags", [])
    if DEGRADED in flags:
        return False
    composite = score.get("score")
    confidence = score.get("confidence")
    if composite is None or confidence is None:
        return False
    return math.isfinite(float(composite)) and math.isfinite(float(confidence))


def _score_from_signal(signal: Any) -> dict[str, Any]:
    return {
        "score": float(signal.composite),
        "news_score": (
            None if signal.news_score is None else float(signal.news_score)
        ),
        "flow_score": (
            None if signal.flow_score is None else float(signal.flow_score)
        ),
        "confidence": float(signal.confidence),
        "degradation_flags": list(signal.degradation_flags),
    }


def _legacy_tier_for_variant(variant: Variant) -> str:
    if variant == "legacy-capable":
        return "capable"
    return ""


def _default_ns_for_variant(variant: Variant) -> str:
    return DEFAULT_VARIANT_NS[variant]


def _analyze_news_with_tier(titles: list[str], *, symbol: str, tier: str) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], cast(Any, analyze_news)(titles, symbol=symbol, tier=tier))
    except TypeError as exc:
        if "tier" not in str(exc):
            raise
        return cast(dict[str, Any], analyze_news(titles, symbol=symbol))


def _aligned_windows_get(
    db: Session,
    *,
    namespace: str,
    symbols: Iterable[str],
    start: str,
    end: str,
    lookback_days: int,
) -> set[tuple[str, str]]:
    symbol_list = list(symbols)
    if not symbol_list:
        return set()
    placeholders = ", ".join(f":s{i}" for i in range(len(symbol_list)))
    params: dict[str, Any] = {
        "namespace": namespace,
        "start": start,
        "end": end,
        "lookback_days": lookback_days,
    }
    params.update({f"s{i}": symbol for i, symbol in enumerate(symbol_list)})
    rows = db.execute(
        text(
            f"""
            SELECT symbol, sig_date
            FROM m54_oos_score_cache
            WHERE namespace = :namespace
              AND lookback_days = :lookback_days
              AND sig_date >= :start
              AND sig_date <= :end
              AND symbol IN ({placeholders})
            """
        ),
        params,
    ).fetchall()
    return {(str(row._mapping["symbol"]), str(row._mapping["sig_date"])) for row in rows}


def _news_titles_from_db(
    db: Session,
    *,
    symbol: str,
    as_of: datetime,
    lookback_days: int,
) -> list[str]:
    start_dt = datetime.combine(
        (as_of - timedelta(days=lookback_days)).date(),
        datetime.min.time(),
    )
    rows = db.execute(
        text(
            """
            SELECT title
            FROM news
            WHERE symbol = :symbol
              AND published_at >= :start_dt
              AND published_at <= :as_of
              AND title IS NOT NULL
              AND TRIM(title) != ''
            ORDER BY published_at ASC, id ASC
            """
        ),
        {
            "symbol": symbol,
            "start_dt": start_dt,
            "as_of": as_of,
        },
    ).fetchall()
    return [str(row._mapping["title"]) for row in rows]


def _legacy_score_from_db(
    db: Session,
    *,
    symbol: str,
    as_of: datetime,
    lookback_days: int,
    variant: Variant,
) -> dict[str, Any] | None:
    titles = _news_titles_from_db(
        db,
        symbol=symbol,
        as_of=as_of,
        lookback_days=lookback_days,
    )
    if not titles:
        return None
    tier = _legacy_tier_for_variant(variant)
    result = _analyze_news_with_tier(titles, symbol=symbol, tier=tier)
    sentiment = result.get("sentiment") if isinstance(result, dict) else None
    if sentiment is None:
        return None
    score = float(sentiment)
    if not math.isfinite(score):
        return None
    return {
        "score": score,
        "news_score": score,
        "flow_score": None,
        "confidence": 1.0,
        "degradation_flags": [],
    }


def _score_cache_set(
    db: Session,
    *,
    namespace: str,
    symbol: str,
    sig_date: str,
    lookback_days: int,
    tier: str,
    score: dict[str, Any],
) -> None:
    db.execute(
        text(
            """
            INSERT OR REPLACE INTO m54_oos_score_cache (
                namespace, symbol, sig_date, lookback_days, tier,
                composite, news_score, flow_score, confidence,
                degradation_flags, created_at
            )
            VALUES (
                :namespace, :symbol, :sig_date, :lookback_days, :tier,
                :composite, :news_score, :flow_score, :confidence,
                :degradation_flags, :created_at
            )
            """
        ),
        {
            "namespace": namespace,
            "symbol": symbol,
            "sig_date": sig_date,
            "lookback_days": lookback_days,
            "tier": tier,
            "composite": float(score["score"]),
            "news_score": score.get("news_score"),
            "flow_score": score.get("flow_score"),
            "confidence": float(score["confidence"]),
            "degradation_flags": json.dumps(
                score.get("degradation_flags", []),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    db.commit()


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


def _build_trading_calendar(prices_by_symbol: dict[str, dict[str, float]]) -> list[str]:
    """Union of every symbol's available price dates, sorted -- a market trading calendar.

    Built from the same 100-symbol universe fetched by ``_load_prices``, so it is
    self-consistent with no external dependency: any date on which at least one
    symbol in the universe has a bar counts as a trading day.
    """
    all_dates: set[str] = set()
    for date_map in prices_by_symbol.values():
        all_dates.update(date_map.keys())
    return sorted(all_dates)


def _forward_return(
    prices: dict[str, float],
    signal_date: str,
    horizon: int,
    calendar: Sequence[str],
) -> float | None:
    """Return horizon-day forward return, aligned to ``calendar`` positions, or None.

    ``calendar`` is a shared market trading-day calendar (see
    ``_build_trading_calendar``), not this symbol's own price-date list. Walking
    the symbol's own dates by index silently stretches the horizon across any
    gap in that symbol's series (e.g. a trading halt) -- see
    M54_OOS_PREREGISTER.md §12 bug-3. Locating both endpoints by calendar
    position and then requiring an exact-date bar for each (no nearest-available
    fallback) fixes that: a gap now yields None instead of a mislabeled horizon.
    """
    try:
        pos = calendar.index(signal_date)
    except ValueError:
        candidates = [d for d in calendar if d >= signal_date]
        if not candidates:
            return None
        pos = calendar.index(candidates[0])
    target_pos = pos + horizon
    if target_pos >= len(calendar):
        return None
    base_date = calendar[pos]
    target_date = calendar[target_pos]
    base = prices.get(base_date)
    fwd = prices.get(target_date)
    if base is None or fwd is None:
        return None
    if base <= 0:
        return None
    ret = fwd / base - 1.0
    return max(-0.30, min(0.30, ret))


def _price_coverage_check(
    symbols: list[str],
    prices_by_symbol: dict[str, dict[str, float]],
    window_dates: list[str],
    horizon: int,
    calendar: Sequence[str],
) -> dict[str, Any]:
    """Coverage of the horizon-day forward price for the tail of the signal window.

    Reuses ``_forward_return`` so "covered" means exactly what the scoring loop
    means by it (same calendar-aligned lookup, same None-on-missing semantics) --
    not a separate/approximate calendar check.
    """
    missing: list[list[str]] = []
    total = 0
    covered = 0
    for sig_date in window_dates:
        for symbol in symbols:
            total += 1
            prices = prices_by_symbol.get(symbol, {})
            if _forward_return(prices, sig_date, horizon, calendar) is not None:
                covered += 1
            else:
                missing.append([symbol, sig_date])
    coverage_pct = round(covered / total, 4) if total else None
    return {
        "window_dates": window_dates,
        "horizon": horizon,
        "n_symbols": len(symbols),
        "n_pairs_total": total,
        "n_pairs_covered": covered,
        "coverage_pct": coverage_pct,
        "n_missing": len(missing),
        "missing_sample": missing[:20],
    }


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
    ns: str | None = None,
    variant: Variant = "v2",
    align_ns: str | None = None,
    refresh: bool = False,
    out: Path | None = None,
    db: Session | None = None,
    session_factory: SessionFactory = SessionLocal,
    mock: bool = False,
    require_price_coverage: float = 0.0,
) -> dict[str, Any]:
    active_ns = ns or _default_ns_for_variant(variant)
    cache_tier = tier if variant == "v2" else _legacy_tier_for_variant(variant)
    _set_oos_namespace(active_ns)
    if mock:
        _install_mock_provider()

    prices_by_symbol = _load_prices(symbols, start, end, session_factory=session_factory)
    trading_calendar = _build_trading_calendar(prices_by_symbol)

    max_horizon = max(HORIZONS)
    all_signal_dates = _iter_signal_dates(start, end)
    tail_dates = all_signal_dates[-max_horizon:] if all_signal_dates else []
    price_coverage = _price_coverage_check(
        symbols, prices_by_symbol, tail_dates, max_horizon, trading_calendar
    )
    if require_price_coverage > 0:
        coverage_pct = price_coverage["coverage_pct"]
        actual_pct = 0.0 if coverage_pct is None else coverage_pct * 100
        if actual_pct < require_price_coverage:
            raise ValueError(
                "price coverage insufficient: "
                f"{actual_pct:.2f}% < required {require_price_coverage:.2f}% "
                f"for tail window {tail_dates} (horizon={max_horizon}d, "
                f"{price_coverage['n_pairs_covered']}/{price_coverage['n_pairs_total']} pairs covered). "
                "Backfill/refresh prices before scoring, otherwise horizon legs may see "
                "different in-flight price snapshots (see M54_OOS_PREREGISTER §11)."
            )

    owns_db = db is None
    active_db = db or session_factory()
    records: list[dict[str, Any]] = []
    skipped_degraded = 0
    skipped_not_triggered = 0
    cache_hits = 0
    cache_misses = 0
    cache_writes = 0

    try:
        _ensure_score_cache_schema(active_db)
        aligned_windows = (
            _aligned_windows_get(
                active_db,
                namespace=align_ns,
                symbols=symbols,
                start=start,
                end=end,
                lookback_days=lookback_days,
            )
            if align_ns
            else None
        )
        for sig_date in _iter_signal_dates(start, end):
            as_of = datetime.strptime(f"{sig_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
            for symbol in symbols:
                if aligned_windows is not None and (symbol, sig_date) not in aligned_windows:
                    continue
                score = None
                if not refresh:
                    score = _score_cache_get(
                        active_db,
                        namespace=active_ns,
                        symbol=symbol,
                        sig_date=sig_date,
                        lookback_days=lookback_days,
                        tier=cache_tier,
                    )
                if score is None:
                    cache_misses += 1
                    if variant == "v2":
                        signal = news_v2_score_from_db(
                            symbol,
                            as_of,
                            lookback_days,
                            active_db,
                            tier=tier,
                        )
                        score = _score_from_signal(signal)
                    else:
                        score = _legacy_score_from_db(
                            active_db,
                            symbol=symbol,
                            as_of=as_of,
                            lookback_days=lookback_days,
                            variant=variant,
                        )
                    if score is None:
                        continue
                    if _score_is_cacheable(score):
                        _score_cache_set(
                            active_db,
                            namespace=active_ns,
                            symbol=symbol,
                            sig_date=sig_date,
                            lookback_days=lookback_days,
                            tier=cache_tier,
                            score=score,
                        )
                        cache_writes += 1
                else:
                    cache_hits += 1

                flags = score["degradation_flags"]
                if DEGRADED in flags:
                    skipped_degraded += 1
                    continue
                if PYRAMID_NOT_TRIGGERED in flags:
                    skipped_not_triggered += 1
                    continue

                row: dict[str, Any] = {
                    "symbol": symbol,
                    "date": sig_date,
                    "score": float(score["score"]),
                    "confidence": float(score["confidence"]),
                    "degradation_flags": list(score["degradation_flags"]),
                }
                prices = prices_by_symbol.get(symbol, {})
                for horizon in HORIZONS:
                    row[f"fwd_{horizon}d"] = _forward_return(
                        prices, sig_date, horizon, trading_calendar
                    )
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
        "skipped_not_triggered": skipped_not_triggered,
        "metrics": metrics,
        "gate_blockers": gate_blockers
        or ["no_data: no non-degraded (symbol, date) pairs produced scores"],
        "meta": {
            "tool": "backend.tools.m54_news_v2_oos",
            "variant": variant,
            "oos_namespace": os.environ.get("SENTIMENT_CACHE_NS", ""),
            "align_ns": align_ns,
            "start": start,
            "end": end,
            "lookback_days": lookback_days,
            "tier": tier,
            "refresh": refresh,
            "cache_table": "m54_oos_score_cache",
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_writes": cache_writes,
            "horizons": list(HORIZONS),
            "n_buckets": N_BUCKETS,
            "min_non_overlap_ic_days": MIN_NON_OVERLAP_IC_DAYS,
            "min_sample_windows": MIN_SAMPLE_WINDOWS,
            "mock": mock,
            "skipped_degraded": skipped_degraded,
            "skipped_not_triggered": skipped_not_triggered,
            "price_coverage": price_coverage,
            "require_price_coverage": require_price_coverage,
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
    parser.add_argument(
        "--variant",
        choices=tuple(DEFAULT_VARIANT_NS),
        default="v2",
        help="Scoring leg: v2, legacy-fast, or legacy-capable",
    )
    parser.add_argument("--ns", default=None, help="OOS score-cache namespace")
    parser.add_argument(
        "--align-ns",
        default=None,
        help="Only score windows already present in this OOS score-cache namespace",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore cached window scores")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument(
        "--require-price-coverage",
        type=float,
        default=0.0,
        metavar="PCT",
        help=(
            "Minimum forward-price coverage (0-100) required for the window's "
            "tail signal dates (last max(horizons) days, at horizon=max(horizons)) "
            "before scoring proceeds. Default 0 = only report meta.price_coverage, "
            "never raise. See M54_OOS_PREREGISTER §11 bug (a)."
        ),
    )
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
        ns=args.ns,
        variant=args.variant,
        align_ns=args.align_ns,
        refresh=args.refresh,
        out=args.out,
        mock=args.mock,
        require_price_coverage=args.require_price_coverage,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
