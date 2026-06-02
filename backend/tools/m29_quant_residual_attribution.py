"""M29.5 read-only quant residual attribution and interaction audit.

This tool asks whether the current quant score has independent information
after the technical + sentiment/event score is known. It is a shadow diagnostic:
it does not write DB rows, call LLM/API providers, train or save models, or
change production signal configuration.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.qlib_engine import qlib_score
from backend.backtest.backfill_signals import _forward_returns, _load_price_pit, backfill_window
from backend.backtest.compare_paths import SignalInput
from backend.backtest.costs import annualized_sharpe, net_return
from backend.config import settings
from backend.data.database import IndexPrice, SessionLocal
from backend.decision.aggregator import _effective_sentiment_score
from backend.tools.m27_alpha_diagnostic import (
    _load_universe_symbols,
    cross_sectional_ic,
    quantile_report,
    summarize_ic,
)
from backend.tools.m27_label_objective_eval import _round
from backend.tools.m27_test3_production_profile_ab import DEFAULT_UNIVERSE_PATH

DEFAULT_START = "2025-11-01"
DEFAULT_END = "2026-05-14"
DEFAULT_EVERY_N_DAYS = 5
DEFAULT_EXIT_DAYS = 5
DEFAULT_HORIZONS = (1, 3, 5, 10)
DEFAULT_QUANT_WEIGHTS = (0.0, 0.225, 0.45)
DEFAULT_JSON_OUTPUT = Path("/private/tmp/m29_quant_residual_attribution_v1.json")
DEFAULT_MARKDOWN_OUTPUT = Path("/private/tmp/m29_quant_residual_attribution_v1.md")
DEFAULT_INDEX_SYMBOL = "sh000300"
MIN_DAILY_NAMES = 5
MIN_BUCKET_ROWS = 20


@dataclass(frozen=True)
class WeightProfile:
    name: str
    quant: float
    technical: float
    sentiment: float
    entry_threshold: float


def _profile_for_quant_weight(quant_weight: float, *, entry_threshold: float = 25.0) -> WeightProfile:
    remaining = max(0.0, 1.0 - quant_weight)
    return WeightProfile(
        name=f"q_{str(quant_weight).replace('.', '_')}",
        quant=quant_weight,
        technical=remaining * 0.6,
        sentiment=remaining * 0.4,
        entry_threshold=entry_threshold,
    )


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _score_components(inp: SignalInput) -> dict[str, Any]:
    sentiment_raw = float(inp.sentiment_result.get("sentiment") or 0.0)
    sentiment_effective = _effective_sentiment_score(sentiment_raw, inp.sentiment_result)
    latest = inp.technical_result.get("latest") or {}
    close = float(inp.close or latest.get("close") or 0.0)
    atr = float(inp.atr or latest.get("atr14") or 0.0)
    event_score_mode = str(inp.sentiment_result.get("event_score_mode") or "")
    key_events = inp.sentiment_result.get("key_events") or []
    return {
        "date": inp.date[:10],
        "symbol": inp.symbol,
        "quant_score": float(inp.qlib_result.get("score") or 0.0),
        "quant_model": inp.qlib_result.get("model"),
        "technical_score": float(inp.technical_result.get("score") or 0.0),
        "sentiment_score": sentiment_effective * 100.0,
        "raw_sentiment_score": sentiment_raw * 100.0,
        "event_score_mode": event_score_mode or None,
        "has_event": bool(key_events or event_score_mode == "event_override"),
        "close": close,
        "atr": atr,
        "atr_ratio": atr / close if close > 0 else None,
    }


def _composite(row: dict[str, Any], profile: WeightProfile) -> float:
    value = (
        float(row["quant_score"]) * profile.quant
        + float(row["technical_score"]) * profile.technical
        + float(row["sentiment_score"]) * profile.sentiment
    )
    if not math.isfinite(value):
        value = 0.0
    return round(max(-100.0, min(100.0, value)), 6)


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in returns:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
    return _round(max_dd)


def _max_open_positions(rows: list[dict[str, Any]], *, exit_days: int) -> int:
    if not rows:
        return 0
    dates = sorted({row["date"] for row in rows})
    date_index = {date: idx for idx, date in enumerate(dates)}
    active = [0 for _ in dates]
    for row in rows:
        start = date_index[row["date"]]
        end = min(len(active), start + max(1, exit_days))
        for idx in range(start, end):
            active[idx] += 1
    return max(active) if active else 0


def _trade_metrics(trades: list[dict[str, Any]], *, exit_days: int) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in trades if _is_finite(row.get("net_return"))]
    if not returns:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "avg_net_return": None,
            "median_net_return": None,
            "total_compounded_return": None,
            "sharpe": None,
            "max_drawdown": None,
            "max_open_positions": 0,
            "max_daily_entries": 0,
        }
    wins = [ret for ret in returns if ret > 0]
    total = 1.0
    for ret in returns:
        total *= 1.0 + ret
    daily_counts = Counter(row["date"] for row in trades)
    return {
        "trades": len(returns),
        "wins": len(wins),
        "losses": len(returns) - len(wins),
        "win_rate": _round(len(wins) / len(returns)),
        "avg_net_return": _round(statistics.mean(returns)),
        "median_net_return": _round(statistics.median(returns)),
        "total_compounded_return": _round(total - 1.0),
        "sharpe": _round(annualized_sharpe(returns, avg_hold_days=exit_days)),
        "max_drawdown": _max_drawdown(returns),
        "max_open_positions": _max_open_positions(trades, exit_days=exit_days),
        "max_daily_entries": max(daily_counts.values()) if daily_counts else 0,
    }


def _entry_rows(frame: pd.DataFrame, profile: WeightProfile, *, exit_days: int) -> list[dict[str, Any]]:
    composite_col = f"composite_{profile.name}"
    ret_col = f"forward_return_{exit_days}d"
    out: list[dict[str, Any]] = []
    clean = frame[["date", "symbol", composite_col, ret_col]].replace([np.inf, -np.inf], np.nan).dropna()
    for row in clean.itertuples(index=False):
        composite = float(getattr(row, composite_col))
        if composite <= profile.entry_threshold:
            continue
        gross = float(getattr(row, ret_col))
        out.append({
            "date": str(row.date),
            "symbol": str(row.symbol),
            "composite_score": _round(composite),
            "gross_return": _round(gross),
            "net_return": _round(net_return(gross)),
        })
    return out


def _delta_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "trades",
        "win_rate",
        "avg_net_return",
        "median_net_return",
        "total_compounded_return",
        "sharpe",
        "max_drawdown",
        "max_open_positions",
        "max_daily_entries",
    ]
    delta: dict[str, Any] = {}
    for key in keys:
        left_value = left.get(key)
        right_value = right.get(key)
        if _is_finite(left_value) and _is_finite(right_value):
            delta[key] = _round(float(left_value or 0.0) - float(right_value or 0.0))
        else:
            delta[key] = None
    return delta


def _build_frame(
    inputs: list[SignalInput],
    *,
    horizons: tuple[int, ...],
    benchmark_returns: dict[tuple[str, int], float | None] | None = None,
) -> pd.DataFrame:
    benchmark_returns = benchmark_returns or {}
    rows: list[dict[str, Any]] = []
    for inp in inputs:
        row = _score_components(inp)
        for horizon in horizons:
            gross = inp.forward_return_at(horizon)
            row[f"forward_return_{horizon}d"] = gross
            bench = benchmark_returns.get((inp.date[:10], horizon))
            row[f"benchmark_return_{horizon}d"] = bench
            row[f"excess_return_{horizon}d"] = (gross - bench) if gross is not None and bench is not None else None
        rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["technical_sentiment_score"] = frame["technical_score"] * 0.6 + frame["sentiment_score"] * 0.4
    frame["quant_only_score"] = frame["quant_score"]
    frame["technical_only_score"] = frame["technical_score"]
    frame["sentiment_event_only_score"] = frame["sentiment_score"]
    try:
        frame["volatility_bucket"] = pd.qcut(
            pd.to_numeric(frame["atr_ratio"], errors="coerce"),
            3,
            labels=["low_vol", "mid_vol", "high_vol"],
            duplicates="drop",
        ).astype(str)
    except ValueError:
        frame["volatility_bucket"] = "unknown"
    tech_median = float(frame["technical_score"].median()) if not frame["technical_score"].empty else 0.0
    frame["technical_bucket"] = np.where(frame["technical_score"] >= tech_median, "strong_technical", "weak_technical")
    frame["sentiment_bucket"] = np.where(frame["sentiment_score"] >= 0, "positive_sentiment", "negative_sentiment")
    frame["event_bucket"] = np.where(frame["has_event"], "event", "no_event")
    return frame


def _ic_summary(frame: pd.DataFrame, score_col: str, label_col: str) -> dict[str, Any]:
    data = frame[["date", score_col, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
    if data.empty:
        return {"ic_mean": None, "icir": None, "ic_days": 0, "ic_positive_rate": None}
    return summarize_ic(cross_sectional_ic(data, score_col, label_col, min_names=MIN_DAILY_NAMES))


def _residual_frame(frame: pd.DataFrame, *, label_col: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    cols = ["date", "symbol", "quant_score", "technical_sentiment_score", label_col]
    data = frame[cols].replace([np.inf, -np.inf], np.nan).dropna()
    for _, group in data.groupby("date", sort=True):
        if len(group) < MIN_DAILY_NAMES:
            continue
        x = group["technical_sentiment_score"].astype(float).to_numpy()
        y = group[label_col].astype(float).to_numpy()
        if float(np.std(x)) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            resid = y - (slope * x + intercept)
        else:
            resid = y - float(np.mean(y))
        out = group[["date", "symbol", "quant_score"]].copy()
        out["residual_return"] = resid
        rows.append(out)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "symbol", "quant_score", "residual_return"])


def _residual_ic(frame: pd.DataFrame, *, horizon: int) -> dict[str, Any]:
    label_col = f"forward_return_{horizon}d"
    residual = _residual_frame(frame, label_col=label_col)
    if residual.empty:
        return {
            "ic_mean": None,
            "icir": None,
            "ic_days": 0,
            "quantiles": [],
            "top_bottom": None,
            "monotonic": False,
            "gate_pass": False,
        }
    ic = summarize_ic(cross_sectional_ic(residual, "quant_score", "residual_return", min_names=MIN_DAILY_NAMES))
    quantiles = quantile_report(residual, "quant_score", "residual_return", orientation=1)
    gate_pass = bool(
        ic.get("ic_mean") is not None
        and float(ic["ic_mean"]) >= settings.qlib_train_ic_floor
        and ic.get("icir") is not None
        and float(ic["icir"]) >= settings.qlib_train_icir_floor
        and quantiles.get("monotonic")
    )
    return {
        **ic,
        "quantiles": quantiles.get("quantiles", []),
        "top_bottom": quantiles.get("top_bottom"),
        "monotonic": bool(quantiles.get("monotonic")),
        "gate_pass": gate_pass,
    }


def _residual_ic_suite(frame: pd.DataFrame, *, horizons: tuple[int, ...]) -> dict[str, Any]:
    score_cols = [
        "technical_only_score",
        "sentiment_event_only_score",
        "technical_sentiment_score",
        "quant_only_score",
        "composite_q_0_45",
    ]
    out: dict[str, Any] = {}
    for horizon in horizons:
        label_col = f"forward_return_{horizon}d"
        out[str(horizon)] = {
            "label_col": label_col,
            "score_ic": {score_col: _ic_summary(frame, score_col, label_col) for score_col in score_cols},
            "quant_residual_to_technical_sentiment": _residual_ic(frame, horizon=horizon),
        }
    return out


def _interaction_buckets(frame: pd.DataFrame, *, exit_days: int) -> dict[str, Any]:
    label_col = f"forward_return_{exit_days}d"
    out: dict[str, Any] = {}
    for bucket_col in ("technical_bucket", "sentiment_bucket", "event_bucket", "volatility_bucket"):
        rows = []
        for value, group in frame.groupby(bucket_col, dropna=False, sort=True):
            clean = group[["date", "quant_score", label_col]].replace([np.inf, -np.inf], np.nan).dropna()
            if len(clean) < MIN_BUCKET_ROWS:
                rows.append({
                    "bucket": str(value),
                    "rows": int(len(clean)),
                    "n_dates": int(clean["date"].nunique()) if not clean.empty else 0,
                    "ic_mean": None,
                    "icir": None,
                    "ic_days": 0,
                    "top_bottom": None,
                    "monotonic": False,
                    "sample_blocker": "insufficient_bucket_rows",
                })
                continue
            ic = _ic_summary(clean, "quant_score", label_col)
            quantiles = quantile_report(clean, "quant_score", label_col, orientation=1)
            rows.append({
                "bucket": str(value),
                "rows": int(len(clean)),
                "n_dates": int(clean["date"].nunique()),
                "ic_mean": ic.get("ic_mean"),
                "icir": ic.get("icir"),
                "ic_days": ic.get("ic_days"),
                "top_bottom": quantiles.get("top_bottom"),
                "monotonic": bool(quantiles.get("monotonic")),
                "sample_blocker": None,
            })
        out[bucket_col] = rows
    return out


def _quant_sweep(frame: pd.DataFrame, *, profiles: list[WeightProfile], exit_days: int) -> dict[str, Any]:
    baseline_profile = profiles[0]
    baseline_entries = _entry_rows(frame, baseline_profile, exit_days=exit_days)
    baseline_keys = {(row["date"], row["symbol"]) for row in baseline_entries}
    baseline_metrics = _trade_metrics(baseline_entries, exit_days=exit_days)
    arms: dict[str, Any] = {}
    for profile in profiles:
        entries = _entry_rows(frame, profile, exit_days=exit_days)
        metrics = _trade_metrics(entries, exit_days=exit_days)
        keys = {(row["date"], row["symbol"]) for row in entries}
        added = sorted(keys - baseline_keys)
        dropped = sorted(baseline_keys - keys)
        arms[profile.name] = {
            "weights": asdict(profile),
            "metrics": metrics,
            "delta_vs_q_0": _delta_metrics(metrics, baseline_metrics),
            "marginal_entries_vs_q_0": {
                "added_count": len(added),
                "dropped_count": len(dropped),
                "added_sample": [{"date": date, "symbol": symbol} for date, symbol in added[:20]],
                "dropped_sample": [{"date": date, "symbol": symbol} for date, symbol in dropped[:20]],
            },
            "sample": entries[:20],
        }
    return {
        "entry_threshold_fixed": baseline_profile.entry_threshold,
        "tech_sent_ratio_fixed": "60:40 of non-quant weight",
        "exit_days": exit_days,
        "arms": arms,
    }


def _trade_attribution(frame: pd.DataFrame, *, horizons: tuple[int, ...]) -> dict[str, Any]:
    base = "composite_q_0_0"
    full = "composite_q_0_45"
    rows: list[dict[str, Any]] = []
    horizon_cols = [
        col
        for horizon in horizons
        for col in (f"forward_return_{horizon}d", f"excess_return_{horizon}d")
    ]
    clean = frame[[
        "date",
        "symbol",
        "quant_score",
        "technical_score",
        "sentiment_score",
        base,
        full,
        *horizon_cols,
    ]].replace(
        [np.inf, -np.inf],
        np.nan,
    )
    for row in clean.itertuples(index=False):
        base_score = float(getattr(row, base))
        full_score = float(getattr(row, full))
        base_entry = base_score > 25.0
        full_entry = full_score > 25.0
        if base_entry and full_entry:
            direction = "unchanged_entry"
        elif (not base_entry) and full_entry:
            direction = "added_by_quant"
        elif base_entry and not full_entry:
            direction = "dropped_by_quant"
        else:
            direction = "unchanged_skip"
        out = {
            "date": str(row.date),
            "symbol": str(row.symbol),
            "direction": direction,
            "composite_without_quant": _round(base_score),
            "composite_with_quant": _round(full_score),
            "composite_delta": _round(full_score - base_score),
            "quant_score": _round(float(row.quant_score)),
            "technical_score": _round(float(row.technical_score)),
            "sentiment_score": _round(float(row.sentiment_score)),
            "crossed_entry_threshold": base_entry != full_entry,
        }
        for horizon in horizons:
            ret_col = f"forward_return_{horizon}d"
            excess_col = f"excess_return_{horizon}d"
            ret_value = getattr(row, ret_col)
            excess_value = getattr(row, excess_col)
            out[ret_col] = _round(float(ret_value)) if _is_finite(ret_value) else None
            out[excess_col] = _round(float(excess_value)) if _is_finite(excess_value) else None
        rows.append(out)
    changed = [row for row in rows if row["crossed_entry_threshold"]]
    changed_sorted = sorted(changed, key=lambda row: abs(float(row["composite_delta"] or 0.0)), reverse=True)
    by_direction = Counter(row["direction"] for row in rows)
    return {
        "comparison": "q_0_45_minus_q_0_0_fixed_threshold_25",
        "rows": len(rows),
        "crossed_entry_threshold_count": len(changed),
        "direction_counts": dict(sorted(by_direction.items())),
        "largest_threshold_crossers": changed_sorted[:30],
    }


def _forward_coverage(frame: pd.DataFrame, *, horizons: tuple[int, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    row_count = int(len(frame))
    for horizon in horizons:
        ret_col = f"forward_return_{horizon}d"
        excess_col = f"excess_return_{horizon}d"
        return_count = int(frame[ret_col].replace([np.inf, -np.inf], np.nan).notna().sum()) if ret_col in frame else 0
        excess_count = (
            int(frame[excess_col].replace([np.inf, -np.inf], np.nan).notna().sum()) if excess_col in frame else 0
        )
        out[str(horizon)] = {
            "rows": row_count,
            "rows_with_forward_return": return_count,
            "rows_missing_forward_return": row_count - return_count,
            "rows_with_excess_return": excess_count,
            "rows_missing_excess_return": row_count - excess_count,
        }
    return out


def build_report(
    inputs: list[SignalInput],
    *,
    start: str,
    end: str,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    quant_weights: tuple[float, ...] = DEFAULT_QUANT_WEIGHTS,
    exit_days: int = DEFAULT_EXIT_DAYS,
    universe_symbols: int | None = None,
    benchmark_returns: dict[tuple[str, int], float | None] | None = None,
) -> dict[str, Any]:
    profiles = [_profile_for_quant_weight(weight) for weight in quant_weights]
    frame = _build_frame(inputs, horizons=horizons, benchmark_returns=benchmark_returns)
    if not frame.empty:
        for profile in profiles:
            frame[f"composite_{profile.name}"] = frame.apply(
                lambda row, current_profile=profile: _composite(row.to_dict(), current_profile),
                axis=1,
            )
        if "composite_q_0_45" not in frame.columns:
            frame["composite_q_0_45"] = frame[f"composite_{profiles[-1].name}"]
        if "composite_q_0_0" not in frame.columns:
            frame["composite_q_0_0"] = frame[f"composite_{profiles[0].name}"]

    residual = _residual_ic_suite(frame, horizons=horizons) if not frame.empty else {}
    exit_residual = ((residual.get(str(exit_days)) or {}).get("quant_residual_to_technical_sentiment") or {})
    quant_models = Counter(str(row.get("quant_model") or "unknown") for row in frame.to_dict("records"))
    coverage = _forward_coverage(frame, horizons=horizons) if not frame.empty else {}
    blockers = [
        "historical_current_model_attribution_only",
        "post_registration_fresh_forward_missing",
        "stride_icir_missing",
        "requires_human_confirmation",
        "m29_5_attribution_audit_non_promoting",
    ]
    data_quality_blockers: list[str] = ["lookahead_quant_warning"]
    for horizon, counts in coverage.items():
        if counts["rows_missing_forward_return"]:
            data_quality_blockers.append(f"future_return_{horizon}d_missing")
        if counts["rows_missing_excess_return"]:
            data_quality_blockers.append(f"excess_return_{horizon}d_missing")
    if not exit_residual.get("gate_pass"):
        blockers.append("quant_residual_gate_not_passed")
    if exit_residual.get("monotonic") is False:
        blockers.append("quant_residual_not_monotonic")
    if not inputs:
        blockers.append("no_signal_inputs")
        data_quality_blockers.append("no_signal_inputs")

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": "m29_quant_residual_attribution.v1",
        "milestone": "M29.5",
        "purpose": "read-only fixed-threshold quant sweep, trade attribution, residual IC, and interaction buckets",
        "run_mode": "read_only_quant_residual_attribution",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "trains_model": False,
        "signal_profile_unchanged": True,
        "model_promotion": "disabled",
        "lookahead_quant_warning": True,
        "start": start,
        "end": end,
        "horizons": list(horizons),
        "exit_days": exit_days,
        "universe_symbols": universe_symbols,
        "sample": {
            "signal_inputs": len(inputs),
            "scored_rows": int(len(frame)),
            "rows_with_nonzero_quant": int((frame["quant_score"] != 0).sum()) if not frame.empty else 0,
            "rows_with_event": int(frame["has_event"].sum()) if not frame.empty else 0,
            "quant_models": dict(sorted(quant_models.items())),
        },
        "forward_coverage": coverage,
        "promotion_gate": {
            "ic_floor": settings.qlib_train_ic_floor,
            "icir_floor": settings.qlib_train_icir_floor,
            "require_monotonic": settings.qlib_train_require_monotonic,
            "requires_fresh_forward": True,
            "requires_human_confirmation": True,
        },
        "quant_sweep": _quant_sweep(frame, profiles=profiles, exit_days=exit_days) if not frame.empty else {},
        "trade_attribution": _trade_attribution(frame, horizons=horizons) if not frame.empty else {},
        "residual_ic": residual,
        "interaction_buckets": _interaction_buckets(frame, exit_days=exit_days) if not frame.empty else {},
        "multiple_comparison": {
            "n_quant_weights": len(quant_weights),
            "n_horizons": len(horizons),
            "n_interaction_families": 4,
            "warning": "Exploratory attribution across weights, horizons, and buckets; any positive result requires fresh OOS/forward confirmation.",
        },
        "blockers": blockers,
        "data_quality_blockers": data_quality_blockers,
        "decision": {
            "decision": "keep_quant_disabled",
            "promotable": False,
            "recommended_next_action": "append_shadow_artifact_to_m29_ledger_and_wait_for_fresh_forward_coverage",
            "rationale": (
                "M29.5 attribution is shadow evidence. Do not restore quant unless residual IC is stable, "
                "monotonic, fresh-forward confirmed, provenance-clean, and manually approved."
            ),
            "blockers": blockers,
        },
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    sample = report.get("sample") or {}
    sweep = report.get("quant_sweep") or {}
    arms = sweep.get("arms") or {}
    exit_days = report.get("exit_days")
    exit_residual = ((report.get("residual_ic") or {}).get(str(exit_days)) or {}).get(
        "quant_residual_to_technical_sentiment",
        {},
    )
    lines = [
        "# M29.5 Quant Residual Attribution",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- run_mode: {report['run_mode']}",
        f"- non_promoting: {report['non_promoting']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- saves_model: {report['saves_model']}",
        f"- trains_model: {report['trains_model']}",
        f"- lookahead_quant_warning: {report['lookahead_quant_warning']}",
        f"- window: {report['start']} ~ {report['end']}",
        f"- signal_inputs: {sample.get('signal_inputs')}",
        f"- rows_with_nonzero_quant: {sample.get('rows_with_nonzero_quant')}",
        "",
        "## Quant Sweep",
        "",
        "| profile | Q | T | S | trades | avg net return | sharpe | max drawdown | max open positions | delta trades vs Q0 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, arm in arms.items():
        weights = arm.get("weights") or {}
        metrics = arm.get("metrics") or {}
        delta = arm.get("delta_vs_q_0") or {}
        lines.append(
            f"| {name} | {weights.get('quant')} | {weights.get('technical')} | {weights.get('sentiment')} | "
            f"{metrics.get('trades')} | {metrics.get('avg_net_return')} | {metrics.get('sharpe')} | "
            f"{metrics.get('max_drawdown')} | {metrics.get('max_open_positions')} | {delta.get('trades')} |"
        )
    lines.extend([
        "",
        "## Residual IC",
        "",
        f"- exit_days: {exit_days}",
        f"- quant_residual_ic: {exit_residual.get('ic_mean')}",
        f"- quant_residual_icir: {exit_residual.get('icir')}",
        f"- quant_residual_monotonic: {exit_residual.get('monotonic')}",
        f"- quant_residual_gate_pass: {exit_residual.get('gate_pass')}",
        "",
        "## Trade Attribution",
        "",
        f"- comparison: {(report.get('trade_attribution') or {}).get('comparison')}",
        f"- crossed_entry_threshold_count: {(report.get('trade_attribution') or {}).get('crossed_entry_threshold_count')}",
        f"- direction_counts: {(report.get('trade_attribution') or {}).get('direction_counts')}",
        "",
        "## Decision",
        "",
        f"- decision: {report['decision']['decision']}",
        f"- promotable: {report['decision']['promotable']}",
        f"- blockers: {', '.join(report.get('blockers') or [])}",
        f"- recommended_next_action: {report['decision']['recommended_next_action']}",
        "",
    ])
    return "\n".join(lines)


def _benchmark_forward_return(db, date: str, horizon: int, *, index_symbol: str) -> float | None:
    start_row = (
        db.query(IndexPrice.date, IndexPrice.close)
        .filter(IndexPrice.symbol == index_symbol, IndexPrice.date <= date)
        .order_by(IndexPrice.date.desc())
        .first()
    )
    if not start_row or not start_row.close:
        return None
    future_rows = (
        db.query(IndexPrice.date, IndexPrice.close)
        .filter(IndexPrice.symbol == index_symbol, IndexPrice.date > date)
        .order_by(IndexPrice.date.asc())
        .limit(horizon)
        .all()
    )
    if len(future_rows) < horizon or not future_rows[-1].close:
        return None
    return float(future_rows[-1].close) / float(start_row.close) - 1.0


def _benchmark_returns_for_inputs(
    db,
    inputs: list[SignalInput],
    *,
    horizons: tuple[int, ...],
    index_symbol: str,
) -> dict[tuple[str, int], float | None]:
    dates = sorted({inp.date[:10] for inp in inputs})
    return {
        (date, horizon): _benchmark_forward_return(db, date, horizon, index_symbol=index_symbol)
        for date in dates
        for horizon in horizons
    }


def _extend_forward_returns(db, inputs: list[SignalInput], *, max_days: int) -> None:
    for inp in inputs:
        if len(inp.forward_returns) >= max_days:
            continue
        inp.forward_returns = _forward_returns(db, inp.symbol, inp.date[:10], inp.close, n=max_days)


def _force_current_quant_scores(db, inputs: list[SignalInput]) -> None:
    """Compute current-model quant scores for attribution even when production Q weight is zero."""
    for inp in inputs:
        df = _load_price_pit(db, inp.symbol, inp.date[:10], days_back=200)
        if len(df) < 60:
            inp.qlib_result = {
                "score": 0.0,
                "model": "unavailable_insufficient_pit_price_history",
                "lookahead_warning": True,
                "as_of": inp.date[:10],
            }
            continue
        result = dict(qlib_score(df, symbol=inp.symbol, db=db))
        result["lookahead_warning"] = True
        result["as_of"] = inp.date[:10]
        result["attribution_only"] = True
        inp.qlib_result = result


def _parse_csv_numbers(raw: str) -> tuple[float, ...]:
    return tuple(float(part.strip()) for part in raw.split(",") if part.strip())


def _parse_csv_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in raw.split(",") if part.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-path", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--every-n-days", type=int, default=DEFAULT_EVERY_N_DAYS)
    parser.add_argument("--exit-days", type=int, default=DEFAULT_EXIT_DAYS)
    parser.add_argument("--horizons", default=",".join(str(item) for item in DEFAULT_HORIZONS))
    parser.add_argument("--quant-weights", default=",".join(str(item) for item in DEFAULT_QUANT_WEIGHTS))
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX_SYMBOL)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    horizons = _parse_csv_ints(args.horizons)
    quant_weights = _parse_csv_numbers(args.quant_weights)
    universe = _load_universe_symbols(args.universe_path)
    inputs = backfill_window(
        args.start,
        args.end,
        symbols=sorted(universe),
        use_llm_news=False,
        every_n_days=args.every_n_days,
        allow_lookahead_quant=True,
    )
    db = SessionLocal()
    try:
        _force_current_quant_scores(db, inputs)
        _extend_forward_returns(db, inputs, max_days=max(horizons))
        benchmark_returns = _benchmark_returns_for_inputs(
            db,
            inputs,
            horizons=horizons,
            index_symbol=args.index_symbol,
        )
    finally:
        db.close()
    report = build_report(
        inputs,
        start=args.start,
        end=args.end,
        horizons=horizons,
        quant_weights=quant_weights,
        exit_days=args.exit_days,
        universe_symbols=len(universe),
        benchmark_returns=benchmark_returns,
    )
    args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.expanduser().write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
