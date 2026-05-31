"""M27.1 alpha diagnostic report.

This tool explains why the current alpha candidate is weak before changing the
training objective or production quant weight. It reads the local feature panel,
recomputes forward-return labels for several horizons, and writes a local-only
report under ``~/.stock-sage`` by default.
"""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.alpha_factors import M27_ALPHA_FEATURE_COLS
from backend.analysis.event_taxonomy import event_score
from backend.analysis.qlib_engine import daily_rank_groups, make_rank_labels
from backend.analysis.sentiment import _cache_key
from backend.config import settings
from backend.data.database import SessionLocal
from backend.data.qlib_data import (
    FEATURE_COLS,
    FUNDAMENTAL_COLS,
    QLIB_MARKET_FEATURE_COLS,
    build_training_data,
)

DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m27_alpha_diagnostic_report.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m27_alpha_diagnostic_report.md"
DEFAULT_HORIZONS = [3, 5, 10, 20]
MIN_DAILY_NAMES = 5
N_GROUPS = 5
DEFAULT_EVENT_LOOKBACK_DAYS = 3
EVENT_AB_MIN_IC_DAYS = 20
PERSISTED_POLARITY_SOURCE = "persisted_news_sentiment_score"
SENTIMENT_CACHE_POLARITY_SOURCE = "sentiment_cache_exact_match"
TITLE_FALLBACK_POLARITY_SOURCE = "offline_title_lexicon_fallback"
POSITIVE_POLARITY_TERMS = (
    "中标",
    "签约",
    "大单",
    "订单",
    "合同",
    "获批",
    "批文",
    "许可",
    "通过审评",
    "增持",
    "回购",
    "员工持股",
    "股权激励",
    "纳入",
    "调入",
    "预增",
    "增长",
    "超预期",
    "扭亏",
    "盈利",
)
NEGATIVE_POLARITY_TERMS = (
    "减持",
    "套现",
    "被动减持",
    "处罚",
    "立案",
    "问询函",
    "警示函",
    "调查",
    "预亏",
    "亏损",
    "下滑",
    "不及预期",
    "计提",
    "违约",
    "债务",
    "冻结",
    "质押",
    "流动性",
)

warnings.filterwarnings(
    "ignore",
    message="The behavior of array concatenation with empty entries is deprecated.*",
    category=FutureWarning,
)


def _round(value: float | int | None, digits: int = 6) -> float | int | None:
    if value is None:
        return None
    if not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _safe_spearman(left: pd.Series, right: pd.Series) -> float | None:
    data = pd.DataFrame({"left": left, "right": right}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 3 or data["left"].nunique() < 2 or data["right"].nunique() < 2:
        return None
    corr = data["left"].rank(method="average").corr(data["right"].rank(method="average"))
    if corr is None or not np.isfinite(corr):
        return None
    return float(corr)


def add_horizon_labels(panel: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Add clipped forward-return labels for each requested horizon."""
    if panel.empty:
        return panel.copy()
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["symbol", "date"]).copy()
    close = pd.to_numeric(out["close"], errors="coerce")
    for horizon in horizons:
        label_col = f"label_{horizon}d"
        out[label_col] = (
            out.assign(_close=close)
            .groupby("symbol", sort=False)["_close"]
            .transform(lambda s, h=horizon: (s.shift(-h) / s - 1).clip(-0.30, 0.30))
        )
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def cross_sectional_ic(
    frame: pd.DataFrame,
    factor_col: str,
    label_col: str,
    *,
    min_names: int = MIN_DAILY_NAMES,
) -> pd.Series:
    """Return daily cross-sectional Spearman IC for a factor and label."""
    rows: list[tuple[pd.Timestamp, float]] = []
    for date, group in frame.groupby("date", sort=True):
        data = group[[factor_col, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < min_names:
            continue
        corr = _safe_spearman(data[factor_col], data[label_col])
        if corr is not None:
            rows.append((pd.to_datetime(date), corr))
    return pd.Series(dict(rows), name="ic", dtype="float64")


def summarize_ic(ic: pd.Series) -> dict[str, Any]:
    """Summarize an IC series with the same mean/std/ICIR shape as Qlib validation."""
    if ic.empty:
        return {
            "ic_days": 0,
            "ic_mean": None,
            "ic_std": None,
            "icir": None,
            "ic_positive_rate": None,
        }
    std = float(ic.std())
    mean = float(ic.mean())
    return {
        "ic_days": int(len(ic)),
        "ic_mean": _round(mean),
        "ic_std": _round(std),
        "icir": _round(mean / std if std > 0 else 0.0),
        "ic_positive_rate": _round(float((ic > 0).mean())),
    }


def _normalize_sentiment(value: Any) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(score):
        return None
    if abs(score) > 1.0:
        score = score / 100.0
    return max(-1.0, min(1.0, score))


def _title_polarity_fallback(title: str) -> float | None:
    positive_hits = sum(1 for term in POSITIVE_POLARITY_TERMS if term in title)
    negative_hits = sum(1 for term in NEGATIVE_POLARITY_TERMS if term in title)
    net = positive_hits - negative_hits
    if net == 0:
        return None
    return max(-1.0, min(1.0, 0.25 * net))


def _sentiment_cache_result(db: Any, titles: list[str], symbol: str) -> dict[str, Any] | None:
    if db is None or not titles:
        return None
    try:
        from backend.data.database import SentimentCache

        cache_key, _titles_hash = _cache_key(titles, symbol)
        row = db.query(SentimentCache).filter(SentimentCache.cache_key == cache_key).first()
        if not row:
            return None
        payload = json.loads(row.result_json)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _sentiment_cache_payload(
    titles: list[str],
    symbol: str,
    *,
    db: Any = None,
    sentiment_cache_lookup: Any = None,
) -> tuple[dict[str, Any] | None, str, str]:
    cache_key, titles_hash = _cache_key(titles, symbol)
    if sentiment_cache_lookup:
        return sentiment_cache_lookup(titles, symbol), cache_key, titles_hash
    return _sentiment_cache_result(db, titles, symbol), cache_key, titles_hash


def _resolve_window_sentiment(
    items: list[dict[str, Any]],
    *,
    symbol: str,
    db: Any = None,
    sentiment_cache_lookup: Any = None,
) -> dict[str, Any]:
    persisted_scores = [
        score
        for score in (_normalize_sentiment(item.get("sentiment_score")) for item in items)
        if score is not None
    ]
    titles = [str(item["title"]) for item in items]
    if persisted_scores:
        cache_key, titles_hash = _cache_key(titles, symbol)
        return {
            "polarity_score": float(np.mean(persisted_scores)),
            "polarity_source": PERSISTED_POLARITY_SOURCE,
            "cache_key": cache_key,
            "titles_hash": titles_hash,
            "cache_hit": None,
            "cache_miss": False,
            "fallback_source": None,
        }

    cached, cache_key, titles_hash = _sentiment_cache_payload(
        titles,
        symbol,
        db=db,
        sentiment_cache_lookup=sentiment_cache_lookup,
    )
    if cached is not None:
        score = _normalize_sentiment(cached.get("sentiment"))
        if score is not None:
            return {
                "polarity_score": score,
                "polarity_source": SENTIMENT_CACHE_POLARITY_SOURCE,
                "cache_key": cache_key,
                "titles_hash": titles_hash,
                "cache_hit": True,
                "cache_miss": False,
                "fallback_source": None,
            }

    fallback_scores = [
        score for score in (_title_polarity_fallback(title) for title in titles) if score is not None
    ]
    if fallback_scores:
        return {
            "polarity_score": float(np.mean(fallback_scores)),
            "polarity_source": TITLE_FALLBACK_POLARITY_SOURCE,
            "cache_key": cache_key,
            "titles_hash": titles_hash,
            "cache_hit": cached is not None,
            "cache_miss": cached is None,
            "fallback_source": TITLE_FALLBACK_POLARITY_SOURCE,
        }
    return {
        "polarity_score": None,
        "polarity_source": None,
        "cache_key": cache_key,
        "titles_hash": titles_hash,
        "cache_hit": cached is not None,
        "cache_miss": cached is None,
        "fallback_source": None,
    }


def quantile_report(
    frame: pd.DataFrame,
    factor_col: str,
    label_col: str,
    *,
    orientation: int = 1,
    n_groups: int = N_GROUPS,
) -> dict[str, Any]:
    """Bucket rows by oriented factor score per date and summarize label returns."""
    rows: list[dict[str, Any]] = []
    data = frame[["date", factor_col, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
    for date, group in data.groupby("date", sort=True):
        if len(group) < n_groups:
            continue
        group = group.copy()
        group["_score"] = pd.to_numeric(group[factor_col], errors="coerce") * orientation
        if group["_score"].nunique() < n_groups:
            continue
        try:
            group["bucket"] = pd.qcut(group["_score"], n_groups, labels=False, duplicates="drop")
        except ValueError:
            continue
        for bucket, sub in group.groupby("bucket", sort=True):
            rows.append({
                "date": date,
                "bucket": int(bucket),
                "ret": float(sub[label_col].mean()),
            })

    bucket_df = pd.DataFrame(rows)
    if bucket_df.empty:
        return {"quantiles": [], "top_bottom": None, "monotonic": False}

    by_bucket = bucket_df.groupby("bucket")["ret"].agg(["mean", "count"]).sort_index()
    quantiles = [
        {
            "bucket": int(idx),
            "mean_return": _round(row["mean"]),
            "count": int(row["count"]),
        }
        for idx, row in by_bucket.iterrows()
    ]
    means = by_bucket["mean"]
    top_bottom = float(means.iloc[-1] - means.iloc[0]) if len(means) >= 2 else None
    monotonic = bool(len(means) >= 3 and means.is_monotonic_increasing and (top_bottom or 0.0) > 0)
    return {
        "quantiles": quantiles,
        "top_bottom": _round(top_bottom),
        "monotonic": monotonic,
    }


def _feature_group(feature: str) -> str:
    if feature in M27_ALPHA_FEATURE_COLS:
        return "m27_alpha"
    if feature in FUNDAMENTAL_COLS:
        return "fundamental"
    if feature in QLIB_MARKET_FEATURE_COLS:
        return "market"
    if feature in {"vol_ratio_20", "turnover_proxy_20", "amihud_20", "volatility_20", "vol_skew_20"}:
        return "liquidity_volatility"
    if feature.startswith("mom_") or feature.startswith("rev_") or "ma" in feature or feature in {
        "rsi14",
        "macd_hist_norm",
        "bb_pct",
        "atr_ratio",
    }:
        return "technical"
    return "other"


def single_factor_diagnostics(
    panel: pd.DataFrame,
    features: list[str],
    label_col: str,
    *,
    min_names: int = MIN_DAILY_NAMES,
    include_quantiles: bool = True,
) -> list[dict[str, Any]]:
    """Build per-factor IC and quantile diagnostics sorted by absolute ICIR/IC."""
    diagnostics: list[dict[str, Any]] = []
    for feature in features:
        if feature not in panel.columns:
            continue
        data = panel[["date", feature, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if data.empty:
            continue
        ic = cross_sectional_ic(data, feature, label_col, min_names=min_names)
        summary = summarize_ic(ic)
        ic_mean = summary["ic_mean"]
        orientation = 1 if (ic_mean is None or float(ic_mean) >= 0) else -1
        q: dict[str, Any] = {"quantiles": [], "top_bottom": None, "monotonic": False}
        if include_quantiles:
            q = quantile_report(data, feature, label_col, orientation=orientation)
        pass_ic = bool(ic_mean is not None and abs(float(ic_mean)) >= settings.qlib_train_ic_floor)
        icir = summary["icir"]
        pass_icir = bool(icir is not None and abs(float(icir)) >= settings.qlib_train_icir_floor)
        diagnostics.append({
            "feature": feature,
            "group": _feature_group(feature),
            **summary,
            "orientation": "positive" if orientation == 1 else "negative",
            "quantiles": q["quantiles"],
            "top_bottom_oriented": q["top_bottom"],
            "monotonic_oriented": q["monotonic"],
            "passes_abs_ic_floor": pass_ic,
            "passes_abs_icir_floor": pass_icir,
            "passes_single_factor_gate": bool(pass_ic and pass_icir and q["monotonic"]),
        })
    return sorted(
        diagnostics,
        key=lambda row: (
            abs(float(row["icir"] or 0.0)),
            abs(float(row["ic_mean"] or 0.0)),
            bool(row["monotonic_oriented"]),
        ),
        reverse=True,
    )


def attach_selected_quantile_reports(
    table: list[dict[str, Any]],
    panel: pd.DataFrame,
    label_col: str,
    *,
    selected_features: set[str],
) -> list[dict[str, Any]]:
    """Attach expensive quantile/monotonic diagnostics only for reportable factors."""
    out: list[dict[str, Any]] = []
    for row in table:
        row = dict(row)
        if row["feature"] in selected_features:
            data = panel[["date", row["feature"], label_col]].replace([np.inf, -np.inf], np.nan).dropna()
            orientation = 1 if row["orientation"] == "positive" else -1
            q = quantile_report(data, row["feature"], label_col, orientation=orientation)
            row["quantiles"] = q["quantiles"]
            row["top_bottom_oriented"] = q["top_bottom"]
            row["monotonic_oriented"] = q["monotonic"]
            row["passes_single_factor_gate"] = bool(
                row["passes_abs_ic_floor"] and row["passes_abs_icir_floor"] and q["monotonic"]
            )
        out.append(row)
    return out


def horizon_comparison(panel: pd.DataFrame, horizons: list[int], features: list[str]) -> dict[str, Any]:
    """Compare which forward-return horizon gives cleaner IC/ICIR signal."""
    result: dict[str, Any] = {}
    for horizon in horizons:
        label_col = f"label_{horizon}d"
        table = single_factor_diagnostics(panel, features, label_col, include_quantiles=False)
        m27_rows = [row for row in table if row["group"] == "m27_alpha"]
        result[str(horizon)] = {
            "label_col": label_col,
            "best_factor": _compact_factor(table[0]) if table else None,
            "best_m27_alpha_factor": _compact_factor(m27_rows[0]) if m27_rows else None,
            "abs_ic_icir_pass_count": int(
                sum(bool(row["passes_abs_ic_floor"] and row["passes_abs_icir_floor"]) for row in table)
            ),
            "monotonic_factor_count": None,
        }
    return result


def _compact_factor(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "feature": row["feature"],
        "group": row["group"],
        "ic_mean": row["ic_mean"],
        "icir": row["icir"],
        "orientation": row["orientation"],
        "passes_abs_ic_floor": row["passes_abs_ic_floor"],
        "passes_abs_icir_floor": row["passes_abs_icir_floor"],
    }


def segment_diagnostics(
    panel: pd.DataFrame,
    factor_col: str,
    label_col: str,
    segment_col: str,
    *,
    min_rows: int = 200,
) -> list[dict[str, Any]]:
    """Row-level segment Spearman diagnostics for industries or regimes."""
    rows: list[dict[str, Any]] = []
    for segment, group in panel.groupby(segment_col, dropna=False, sort=True):
        data = group[[factor_col, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < min_rows:
            continue
        corr = _safe_spearman(data[factor_col], data[label_col])
        rows.append({
            "segment": str(segment),
            "n_rows": int(len(data)),
            "spearman": _round(corr),
            "mean_label": _round(float(data[label_col].mean())),
        })
    return sorted(rows, key=lambda row: abs(float(row["spearman"] or 0.0)), reverse=True)


def add_volatility_regime(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    if "volatility_20" not in out.columns:
        out["volatility_regime"] = "unknown"
        return out
    data = pd.to_numeric(out["volatility_20"], errors="coerce")
    try:
        out["volatility_regime"] = pd.qcut(data, 3, labels=["low_vol", "mid_vol", "high_vol"], duplicates="drop")
    except ValueError:
        out["volatility_regime"] = "unknown"
    out["volatility_regime"] = out["volatility_regime"].astype(str).replace("nan", "unknown")
    return out


def ranker_label_distribution(panel: pd.DataFrame, label_col: str) -> dict[str, Any]:
    """Summarize LambdaRank label and group cardinality pressure."""
    data = panel[["date", "symbol", label_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        return {"n_rows": 0}
    data = data.sort_values(["date", "symbol"]).rename(columns={label_col: "label"})
    labels = make_rank_labels(data)
    groups = pd.Series(daily_rank_groups(data), dtype="float64")
    return {
        "n_rows": int(len(data)),
        "n_dates": int(data["date"].nunique()),
        "max_daily_group": int(groups.max()) if not groups.empty else 0,
        "median_daily_group": _round(float(groups.median())) if not groups.empty else None,
        "p95_daily_group": _round(float(groups.quantile(0.95))) if not groups.empty else None,
        "max_label": int(labels.max()) if not labels.empty else 0,
        "label_gain_required": int(labels.max()) + 1 if not labels.empty else 0,
        "median_label": _round(float(labels.median())) if not labels.empty else None,
    }


def _event_ab_row_frame(
    panel: pd.DataFrame,
    news_rows: list[dict[str, Any]],
    *,
    universe_symbols: set[str],
    label_col: str,
    lookback_days: int = DEFAULT_EVENT_LOOKBACK_DAYS,
    db: Any = None,
    sentiment_cache_lookup: Any = None,
) -> pd.DataFrame:
    columns = [
        "date",
        "symbol",
        label_col,
        "news_count",
        "titles",
        "cache_key",
        "titles_hash",
        "cache_hit",
        "cache_miss",
        "fallback_source",
        "polarity_score",
        "polarity_available",
        "polarity_source",
        "event_score",
        "event_score_mode",
        "event_type_count",
    ]
    if panel.empty or not news_rows:
        return pd.DataFrame(columns=columns)

    data = panel[["date", "symbol", label_col]].copy()
    data["date"] = pd.to_datetime(data["date"]).dt.normalize()
    data = data[data["symbol"].isin(universe_symbols)].dropna(subset=[label_col])
    if data.empty:
        return pd.DataFrame(columns=columns)

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in news_rows:
        symbol = str(item.get("symbol") or "")
        if symbol not in universe_symbols:
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        published_at = pd.to_datetime(item.get("published_at"), errors="coerce")
        if pd.isna(published_at):
            continue
        by_symbol.setdefault(symbol, []).append({
            "title": title,
            "published_at": published_at.normalize(),
            "sentiment_score": item.get("sentiment_score"),
        })
    for rows in by_symbol.values():
        rows.sort(key=lambda row: row["published_at"])

    ab_rows: list[dict[str, Any]] = []
    for row in data.itertuples(index=False):
        symbol = str(row.symbol)
        date = pd.Timestamp(row.date).normalize()
        start = date - pd.Timedelta(days=lookback_days)
        items = [
            item for item in by_symbol.get(symbol, [])
            if start <= item["published_at"] <= date
        ][-15:]
        if not items:
            continue

        titles = [item["title"] for item in items]
        sentiment = _resolve_window_sentiment(
            items,
            symbol=symbol,
            db=db,
            sentiment_cache_lookup=sentiment_cache_lookup,
        )
        polarity_score = sentiment["polarity_score"]
        polarity_source = sentiment["polarity_source"]
        polarity_available = polarity_score is not None
        adjusted = event_score(polarity_score or 0.0, titles)
        event_available = polarity_available or adjusted["event_score_mode"] == "event_override"

        ab_rows.append({
            "date": date,
            "symbol": symbol,
            label_col: getattr(row, label_col),
            "news_count": len(items),
            "titles": titles,
            "cache_key": sentiment["cache_key"],
            "titles_hash": sentiment["titles_hash"],
            "cache_hit": sentiment["cache_hit"],
            "cache_miss": sentiment["cache_miss"],
            "fallback_source": sentiment["fallback_source"],
            "polarity_score": polarity_score,
            "polarity_available": polarity_available,
            "polarity_source": polarity_source,
            "event_score": adjusted["event_score"] if event_available else None,
            "event_score_mode": adjusted["event_score_mode"],
            "event_type_count": len(adjusted["event_types"]),
        })
    return pd.DataFrame(ab_rows, columns=columns)


def _cache_miss_windows(rows: pd.DataFrame) -> list[dict[str, Any]]:
    if rows.empty or "cache_miss" not in rows.columns:
        return []
    missing = rows[rows["cache_miss"].fillna(False).astype(bool)].copy()
    if missing.empty:
        return []
    missing = missing.sort_values(["symbol", "date"])
    windows: list[dict[str, Any]] = []
    for row in missing.itertuples(index=False):
        fallback_source = None if pd.isna(row.fallback_source) else row.fallback_source
        polarity_source = None if pd.isna(row.polarity_source) else row.polarity_source
        windows.append({
            "symbol": str(row.symbol),
            "date": pd.Timestamp(row.date).date().isoformat(),
            "titles": list(row.titles),
            "cache_key": str(row.cache_key),
            "titles_hash": str(row.titles_hash),
            "news_count": int(row.news_count),
            "fallback_source": fallback_source,
            "polarity_source": polarity_source,
            "event_score_mode": row.event_score_mode,
        })
    return windows


def _write_cache_miss_windows(path: Path, rows: pd.DataFrame) -> int:
    windows = _cache_miss_windows(rows)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cache_miss_windows": len(windows),
        "windows": windows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(windows)


def _event_variant_validation(
    rows: pd.DataFrame,
    *,
    score_col: str,
    label_col: str,
    summary: dict[str, Any],
    data_quality_blockers: list[str],
) -> dict[str, Any]:
    data = rows[rows[score_col].notna()] if not rows.empty else rows
    quantiles = quantile_report(data, score_col, label_col, orientation=1)
    ic_mean = summary.get("ic_mean")
    icir = summary.get("icir")
    ic_days = int(summary.get("ic_days") or 0)
    passes_ic = bool(ic_mean is not None and float(ic_mean) >= settings.qlib_train_ic_floor)
    passes_icir = bool(icir is not None and float(icir) >= settings.qlib_train_icir_floor)
    passes_min_days = bool(ic_days >= EVENT_AB_MIN_IC_DAYS)
    passes_quantile_sample = bool(len(quantiles["quantiles"]) >= N_GROUPS)
    passes_sample = bool(passes_min_days and passes_quantile_sample)
    passes_monotonic = bool(quantiles["monotonic"])
    monotonic_ok = bool((not settings.qlib_train_require_monotonic) or passes_monotonic)

    failure_reasons: list[str] = []
    if not passes_ic:
        failure_reasons.append("ic_below_floor")
    if not passes_icir:
        failure_reasons.append("icir_below_floor")
    if not monotonic_ok:
        failure_reasons.append("not_monotonic")
    if not passes_min_days:
        failure_reasons.append("insufficient_ic_days")
    if not passes_quantile_sample:
        failure_reasons.append("insufficient_quantile_cross_section")
    failure_reasons.extend(data_quality_blockers)

    return {
        "orientation": "positive",
        "quantiles": quantiles["quantiles"],
        "top_bottom_oriented": quantiles["top_bottom"],
        "monotonic_oriented": passes_monotonic,
        "min_ic_days": EVENT_AB_MIN_IC_DAYS,
        "passes_min_ic_days": passes_min_days,
        "passes_quantile_sample": passes_quantile_sample,
        "passes_sample_gate": passes_sample,
        "passes_ic_floor": passes_ic,
        "passes_icir_floor": passes_icir,
        "passes_quantile_monotonic_gate": monotonic_ok,
        "data_quality_blockers": data_quality_blockers,
        "passes_event_ab_gate": not failure_reasons,
        "gate_blockers": failure_reasons,
    }


def _event_variant_comparison(
    polarity_summary: dict[str, Any],
    event_summary: dict[str, Any],
    polarity_validation: dict[str, Any],
    event_validation: dict[str, Any],
) -> dict[str, Any]:
    polarity_ic = polarity_summary.get("ic_mean")
    event_ic = event_summary.get("ic_mean")
    polarity_icir = polarity_summary.get("icir")
    event_icir = event_summary.get("icir")
    event_beats_pure_ic = bool(
        polarity_ic is not None and event_ic is not None and float(event_ic) > float(polarity_ic)
    )
    event_beats_pure_icir = bool(
        polarity_icir is not None and event_icir is not None and float(event_icir) > float(polarity_icir)
    )
    if event_validation["passes_event_ab_gate"] and event_beats_pure_ic and event_beats_pure_icir:
        recommended_variant = "polarity_plus_event"
    elif polarity_validation["passes_event_ab_gate"]:
        recommended_variant = "pure_polarity_shadow_candidate"
    else:
        recommended_variant = "none"
    return {
        "event_beats_pure_ic": event_beats_pure_ic,
        "event_beats_pure_icir": event_beats_pure_icir,
        "recommended_variant": recommended_variant,
        "production_unchanged": True,
    }


def event_ab_diagnostics(
    panel: pd.DataFrame,
    news_rows: list[dict[str, Any]],
    *,
    universe_symbols: set[str],
    label_col: str,
    lookback_days: int = DEFAULT_EVENT_LOOKBACK_DAYS,
    min_names: int = MIN_DAILY_NAMES,
    db: Any = None,
    sentiment_cache_lookup: Any = None,
    cache_missing_output: Path | None = None,
) -> dict[str, Any]:
    """Compare pure polarity vs event-aware sentiment IC without calling external APIs."""
    rows = _event_ab_row_frame(
        panel,
        news_rows,
        universe_symbols=universe_symbols,
        label_col=label_col,
        lookback_days=lookback_days,
        db=db,
        sentiment_cache_lookup=sentiment_cache_lookup,
    )
    coverage = {
        "universe_symbols": int(len(universe_symbols)),
        "news_items": int(len(news_rows)),
        "rows_with_news": int(len(rows)),
        "rows_with_polarity": int(rows["polarity_available"].sum()) if not rows.empty else 0,
        "rows_with_persisted_polarity": int(
            rows["polarity_source"].fillna("").str.contains(PERSISTED_POLARITY_SOURCE, regex=False).sum()
        ) if not rows.empty else 0,
        "rows_with_cache_polarity": int(
            rows["polarity_source"].fillna("").str.contains(SENTIMENT_CACHE_POLARITY_SOURCE, regex=False).sum()
        ) if not rows.empty else 0,
        "rows_with_fallback_polarity": int(
            rows["polarity_source"].fillna("").str.contains(TITLE_FALLBACK_POLARITY_SOURCE, regex=False).sum()
        ) if not rows.empty else 0,
        "cache_miss_windows": int(rows["cache_miss"].fillna(False).astype(bool).sum()) if not rows.empty else 0,
        "polarity_sources": rows["polarity_source"].dropna().value_counts().sort_index().to_dict()
        if not rows.empty
        else {},
        "rows_with_event_override": int((rows["event_score_mode"] == "event_override").sum()) if not rows.empty else 0,
        "event_type_hits": int(rows["event_type_count"].sum()) if not rows.empty else 0,
        "lookback_days": int(lookback_days),
        "min_daily_names": int(min_names),
    }

    polarity_rows = rows[rows["polarity_available"]] if not rows.empty else rows
    event_rows = rows[rows["event_score"].notna()] if not rows.empty else rows
    polarity_summary = summarize_ic(cross_sectional_ic(polarity_rows, "polarity_score", label_col, min_names=min_names))
    event_summary = summarize_ic(cross_sectional_ic(event_rows, "event_score", label_col, min_names=min_names))

    delta_ic = None
    if polarity_summary["ic_mean"] is not None and event_summary["ic_mean"] is not None:
        delta_ic = _round(float(event_summary["ic_mean"]) - float(polarity_summary["ic_mean"]))

    data_quality_blockers: list[str] = []
    if coverage["cache_miss_windows"] > 0:
        data_quality_blockers.append("cache_miss_windows_open")
    if coverage["rows_with_fallback_polarity"] > 0:
        data_quality_blockers.append("fallback_polarity_used")
    polarity_validation = _event_variant_validation(
        polarity_rows,
        score_col="polarity_score",
        label_col=label_col,
        summary=polarity_summary,
        data_quality_blockers=data_quality_blockers,
    )
    event_validation = _event_variant_validation(
        event_rows,
        score_col="event_score",
        label_col=label_col,
        summary=event_summary,
        data_quality_blockers=data_quality_blockers,
    )
    variant_comparison = _event_variant_comparison(
        polarity_summary,
        event_summary,
        polarity_validation,
        event_validation,
    )

    blockers: list[str] = []
    if coverage["rows_with_news"] == 0:
        blockers.append("no_test3_news_rows")
    if coverage["rows_with_polarity"] == 0:
        blockers.append("no_cached_or_persisted_polarity_scores")
    if polarity_summary["ic_days"] == 0:
        blockers.append("insufficient_daily_polarity_cross_section")
    if event_summary["ic_days"] == 0:
        blockers.append("insufficient_daily_event_cross_section")

    cache_miss_output = None
    if cache_missing_output is not None:
        written_count = _write_cache_miss_windows(cache_missing_output, rows)
        cache_miss_output = {
            "path": str(cache_missing_output),
            "windows": written_count,
        }

    status = "ok" if not blockers else "blocked"
    report = {
        "status": status,
        "event_ab_gate": {
            "ic_floor": settings.qlib_train_ic_floor,
            "icir_floor": settings.qlib_train_icir_floor,
            "require_monotonic": settings.qlib_train_require_monotonic,
            "min_daily_names": int(min_names),
            "min_ic_days": EVENT_AB_MIN_IC_DAYS,
            "min_quantile_buckets": N_GROUPS,
            "requires_no_cache_miss": True,
            "requires_no_fallback": True,
            "orientation": "positive",
            "n_variants_tested": 2,
            "multiple_comparison_warning": (
                "event lookback and pure/event variants are exploratory; require fresh OOS/forward "
                "confirmation before any production promotion"
            ),
        },
        "coverage": coverage,
        "polarity": polarity_summary,
        "polarity_event": event_summary,
        "pure_polarity_validation": polarity_validation,
        "polarity_event_validation": event_validation,
        "variant_comparison": variant_comparison,
        "delta_ic": delta_ic,
        "blockers": blockers,
    }
    if cache_miss_output is not None:
        report["cache_miss_output"] = cache_miss_output
    return report


def _load_universe_symbols(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    return {
        str(row.get("symbol") if isinstance(row, dict) else row)
        for row in rows
        if (row.get("symbol") if isinstance(row, dict) else row)
    }


def _load_news_rows_for_symbols(db: Any, symbols: set[str]) -> list[dict[str, Any]]:
    from backend.data.database import NewsItem

    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol.in_(symbols))
        .order_by(NewsItem.symbol.asc(), NewsItem.published_at.asc())
        .all()
    )
    return [
        {
            "symbol": row.symbol,
            "title": row.title,
            "published_at": row.published_at,
            "sentiment_score": row.sentiment_score,
        }
        for row in rows
    ]


def build_diagnosis(report: dict[str, Any]) -> dict[str, Any]:
    table = report.get("single_factor_5d") or []
    horizons = report.get("horizon_comparison") or {}
    findings: list[str] = []
    best = table[0] if table else None
    m27_rows = [row for row in table if row.get("group") == "m27_alpha"]
    gate_pass_count = int(sum(bool(row.get("passes_single_factor_gate")) for row in table))

    if best:
        findings.append(
            f"Best standalone 5d factor is {best['feature']} "
            f"(IC={best['ic_mean']}, ICIR={best['icir']}, monotonic={best['monotonic_oriented']})."
        )
    if gate_pass_count == 0:
        findings.append("No standalone 5d factor clears the IC/ICIR/monotonic gate.")
    if m27_rows and best and m27_rows[0]["feature"] != best["feature"]:
        findings.append(
            f"Best M27 alpha factor is {m27_rows[0]['feature']} "
            f"(IC={m27_rows[0]['ic_mean']}, ICIR={m27_rows[0]['icir']}), below the overall leader."
        )

    best_horizon = None
    for horizon, payload in horizons.items():
        candidate = payload.get("best_factor") or {}
        score = abs(float(candidate.get("icir") or 0.0))
        if best_horizon is None or score > best_horizon[0]:
            best_horizon = (score, horizon, candidate)
    if best_horizon and best_horizon[1] != "5":
        findings.append(
            f"Strongest single-factor ICIR appears at {best_horizon[1]}d via "
            f"{best_horizon[2].get('feature')} (ICIR={best_horizon[2].get('icir')})."
        )

    if gate_pass_count == 0:
        action = "redesign_label_objective_before_more_feature_work"
    elif best_horizon and best_horizon[1] != "5":
        action = "test_horizon_shift_before_retraining"
    else:
        action = "retrain_with_current_feature_set_and_validate_again"
    return {
        "primary_findings": findings,
        "recommended_next_action": action,
    }


def build_report(
    panel: pd.DataFrame,
    *,
    horizons: list[int] | None = None,
    top_n: int = 20,
    event_ab: dict[str, Any] | None = None,
) -> dict[str, Any]:
    horizons = horizons or DEFAULT_HORIZONS
    panel = add_horizon_labels(panel, horizons)
    panel = add_volatility_regime(panel)
    features = [feature for feature in FEATURE_COLS if feature in panel.columns]
    if "label_5d" in panel.columns:
        label_col = "label_5d"
    elif horizons and f"label_{horizons[0]}d" in panel.columns:
        label_col = f"label_{horizons[0]}d"
    else:
        label_col = "label"
    single_5d = single_factor_diagnostics(panel, features, label_col, include_quantiles=False)
    selected_features = {row["feature"] for row in single_5d[:top_n]}
    selected_features.update(row["feature"] for row in single_5d if row["group"] == "m27_alpha")
    single_5d = attach_selected_quantile_reports(
        single_5d,
        panel,
        label_col,
        selected_features=selected_features,
    )
    top_factor = single_5d[0]["feature"] if single_5d else None
    top_m27 = next((row["feature"] for row in single_5d if row["group"] == "m27_alpha"), None)

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gate": {
            "ic_floor": settings.qlib_train_ic_floor,
            "icir_floor": settings.qlib_train_icir_floor,
            "require_monotonic": settings.qlib_train_require_monotonic,
        },
        "sample": {
            "n_rows": int(len(panel)),
            "n_symbols": int(panel["symbol"].nunique()) if "symbol" in panel.columns else 0,
            "n_dates": int(panel["date"].nunique()) if "date" in panel.columns else 0,
            "n_features": int(len(features)),
            "start": str(panel["date"].min().date()) if len(panel) else None,
            "end": str(panel["date"].max().date()) if len(panel) else None,
        },
        "horizons": horizons,
        "single_factor_5d": single_5d[:top_n],
        "m27_alpha_5d": [row for row in single_5d if row["group"] == "m27_alpha"],
        "horizon_comparison": horizon_comparison(panel, horizons, features),
        "ranker_labels_5d": ranker_label_distribution(panel, label_col),
        "industry_segments": segment_diagnostics(panel, top_factor, label_col, "industry")[:20] if top_factor else [],
        "volatility_segments": segment_diagnostics(panel, top_factor, label_col, "volatility_regime", min_rows=100)
        if top_factor
        else [],
        "m27_industry_segments": segment_diagnostics(panel, top_m27, label_col, "industry")[:20] if top_m27 else [],
    }
    if event_ab is not None:
        report["event_ab_5d"] = event_ab
    report["diagnosis"] = build_diagnosis(report)
    return report


def report_to_markdown(report: dict[str, Any]) -> str:
    sample = report["sample"]
    gate = report["gate"]
    diagnosis = report["diagnosis"]
    lines = [
        "# M27.1 Alpha Diagnostic Report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- sample: {sample['n_rows']} rows / {sample['n_symbols']} symbols / {sample['n_dates']} dates",
        f"- window: {sample['start']} ~ {sample['end']}",
        f"- gate: IC>={gate['ic_floor']}, ICIR>={gate['icir_floor']}, monotonic_required={gate['require_monotonic']}",
        "",
        "## Diagnosis",
        "",
    ]
    for finding in diagnosis["primary_findings"]:
        lines.append(f"- {finding}")
    lines += [
        f"- recommended_next_action: {diagnosis['recommended_next_action']}",
        "",
        "## Top 5d Single Factors",
        "",
        "| feature | group | IC | ICIR | orientation | top-bottom | monotonic | gate |",
        "| --- | --- | ---: | ---: | --- | ---: | --- | --- |",
    ]
    for row in report["single_factor_5d"]:
        lines.append(
            f"| {row['feature']} | {row['group']} | {row['ic_mean']} | {row['icir']} | "
            f"{row['orientation']} | {row['top_bottom_oriented']} | "
            f"{row['monotonic_oriented']} | {row['passes_single_factor_gate']} |"
        )

    lines += [
        "",
        "## Horizon Comparison",
        "",
        "| horizon | best_factor | IC | ICIR | abs_IC_ICIR_pass_count | m27_best | m27_IC | m27_ICIR |",
        "| ---: | --- | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for horizon, payload in report["horizon_comparison"].items():
        best = payload.get("best_factor") or {}
        m27 = payload.get("best_m27_alpha_factor") or {}
        lines.append(
            f"| {horizon}d | {best.get('feature')} | {best.get('ic_mean')} | {best.get('icir')} | "
            f"{payload.get('abs_ic_icir_pass_count')} | {m27.get('feature')} | {m27.get('ic_mean')} | {m27.get('icir')} |"
        )

    ranker = report["ranker_labels_5d"]
    lines += [
        "",
        "## Ranker Label Distribution",
        "",
        f"- n_dates: {ranker.get('n_dates')}",
        f"- max_daily_group: {ranker.get('max_daily_group')}",
        f"- p95_daily_group: {ranker.get('p95_daily_group')}",
        f"- max_label: {ranker.get('max_label')}",
        f"- label_gain_required: {ranker.get('label_gain_required')}",
        "",
        "## Volatility Segments",
        "",
        "| segment | rows | spearman | mean_label |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in report["volatility_segments"]:
        lines.append(f"| {row['segment']} | {row['n_rows']} | {row['spearman']} | {row['mean_label']} |")
    if "event_ab_5d" in report:
        event_ab = report["event_ab_5d"]
        event_gate = event_ab.get("event_ab_gate") or {}
        coverage = event_ab["coverage"]
        polarity = event_ab["polarity"]
        polarity_event = event_ab["polarity_event"]
        polarity_validation = event_ab.get("pure_polarity_validation") or {}
        event_validation = event_ab.get("polarity_event_validation") or {}
        comparison = event_ab.get("variant_comparison") or {}
        lines += [
            "",
            "## M27.3 Event Sentiment A/B",
            "",
            f"- status: {event_ab['status']}",
            f"- event_ab_gate: IC>={event_gate.get('ic_floor')}, ICIR>={event_gate.get('icir_floor')}, "
            f"monotonic_required={event_gate.get('require_monotonic')}, "
            f"min_ic_days={event_gate.get('min_ic_days')}, "
            f"min_quantile_buckets={event_gate.get('min_quantile_buckets')}, "
            f"requires_no_cache_miss={event_gate.get('requires_no_cache_miss')}, "
            f"requires_no_fallback={event_gate.get('requires_no_fallback')}, "
            f"n_variants_tested={event_gate.get('n_variants_tested')}",
            f"- multiple_comparison_warning: {event_gate.get('multiple_comparison_warning')}",
            f"- coverage: news_rows={coverage['news_items']}, rows_with_news={coverage['rows_with_news']}, "
            f"rows_with_polarity={coverage['rows_with_polarity']}, "
            f"rows_with_persisted_polarity={coverage.get('rows_with_persisted_polarity', 0)}, "
            f"rows_with_cache_polarity={coverage.get('rows_with_cache_polarity', 0)}, "
            f"rows_with_fallback_polarity={coverage.get('rows_with_fallback_polarity', 0)}, "
            f"cache_miss_windows={coverage.get('cache_miss_windows', 0)}, "
            f"rows_with_event_override={coverage['rows_with_event_override']}",
            f"- polarity_sources: {coverage.get('polarity_sources') or {}}",
            f"- cache_miss_output: {event_ab.get('cache_miss_output') or 'not_requested'}",
            f"- blockers: {', '.join(event_ab['blockers']) if event_ab['blockers'] else 'none'}",
            f"- recommended_variant: {comparison.get('recommended_variant')}",
            "",
            "| variant | IC days | IC | ICIR | positive_rate | top-bottom | monotonic | sample_gate | gate | gate_blockers |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
            f"| pure_polarity | {polarity['ic_days']} | {polarity['ic_mean']} | "
            f"{polarity['icir']} | {polarity['ic_positive_rate']} | "
            f"{polarity_validation.get('top_bottom_oriented')} | "
            f"{polarity_validation.get('monotonic_oriented')} | "
            f"{polarity_validation.get('passes_sample_gate')} | "
            f"{polarity_validation.get('passes_event_ab_gate')} | "
            f"{polarity_validation.get('gate_blockers') or []} |",
            f"| polarity_plus_event | {polarity_event['ic_days']} | {polarity_event['ic_mean']} | "
            f"{polarity_event['icir']} | {polarity_event['ic_positive_rate']} | "
            f"{event_validation.get('top_bottom_oriented')} | "
            f"{event_validation.get('monotonic_oriented')} | "
            f"{event_validation.get('passes_sample_gate')} | "
            f"{event_validation.get('passes_event_ab_gate')} | "
            f"{event_validation.get('gate_blockers') or []} |",
            f"| delta |  | {event_ab['delta_ic']} |  |  |  |  |  |  |  |",
        ]
    lines += [
        "",
        "## Industry Segments For Top Factor",
        "",
        "| segment | rows | spearman | mean_label |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in report["industry_segments"][:12]:
        lines.append(f"| {row['segment']} | {row['n_rows']} | {row['spearman']} | {row['mean_label']} |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizons", nargs="*", type=int, default=DEFAULT_HORIZONS)
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--active-only", action="store_true")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--event-ab", action="store_true", help="Run M27.3 test3 event sentiment IC A/B")
    parser.add_argument("--universe-path", type=Path, help="Universe JSON for --event-ab, e.g. paper_trading/test3_universe.json")
    parser.add_argument("--event-lookback-days", type=int, default=DEFAULT_EVENT_LOOKBACK_DAYS)
    parser.add_argument(
        "--event-ab-cache-missing-output",
        type=Path,
        help="Write exact sentiment_cache miss title windows for --event-ab to this JSON path",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true", help="Print markdown report to stdout")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db = SessionLocal()
    try:
        panel = build_training_data(db, min_rows=args.min_rows, include_inactive=not args.active_only)
        event_ab = None
        if args.event_ab:
            if not args.universe_path:
                raise SystemExit("--event-ab requires --universe-path")
            universe_symbols = _load_universe_symbols(args.universe_path)
            panel = panel[panel["symbol"].isin(universe_symbols)].copy()
            panel = add_horizon_labels(panel, args.horizons)
            label_col = "label_5d" if "label_5d" in panel.columns else f"label_{args.horizons[0]}d"
            news_rows = _load_news_rows_for_symbols(db, universe_symbols)
            event_ab = event_ab_diagnostics(
                panel,
                news_rows,
                universe_symbols=universe_symbols,
                label_col=label_col,
                lookback_days=args.event_lookback_days,
                db=db,
                cache_missing_output=args.event_ab_cache_missing_output,
            )
        report = build_report(panel, horizons=args.horizons, top_n=args.top_n, event_ab=event_ab)
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown = report_to_markdown(report)
        args.markdown_output.write_text(markdown, encoding="utf-8")
        if args.print:
            print(markdown)
        print(f"JSON report: {args.json_output}")
        print(f"Markdown report: {args.markdown_output}")
        print(f"Recommended next action: {report['diagnosis']['recommended_next_action']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
