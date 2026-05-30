"""M27.1c read-only top-decile entry-filter A/B report.

This local-only diagnostic reuses the M27.1b top-decile classifier and training
panel to compare validation-window baseline candidates with candidates kept by
a daily top-decile probability filter. It does not promote, persist, or wire a
model into production.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.qlib_engine import _time_split
from backend.backtest.alphalens_qlib import build_validation_report
from backend.data.database import SessionLocal
from backend.data.qlib_data import FEATURE_COLS
from backend.tools.m27_label_objective_eval import (
    DEFAULT_HORIZON,
    TOP_DECILE_PCT,
    _fit_predict,
    _round,
    _top_indices,
    _validation_frame,
    add_objective_labels,
    load_or_build_panel,
    stride_predictions,
    top_decile_metrics,
)

DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m27_top_decile_filter_ab_report.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m27_top_decile_filter_ab_report.md"


def _candidate_return_metrics(candidates: pd.DataFrame) -> dict[str, Any]:
    clean = candidates.replace([np.inf, -np.inf], np.nan).dropna(subset=["label"])
    if clean.empty:
        return {
            "candidate_count": 0,
            "n_symbols": 0,
            "n_dates": 0,
            "mean_forward_return": None,
            "median_forward_return": None,
            "win_rate": None,
            "avg_candidates_per_date": None,
        }
    by_date = clean.groupby("date", sort=True)["label"].mean()
    return {
        "candidate_count": int(len(clean)),
        "n_symbols": int(clean["symbol"].nunique()),
        "n_dates": int(pd.to_datetime(clean["date"]).nunique()),
        "mean_forward_return": _round(float(clean["label"].mean())),
        "median_forward_return": _round(float(clean["label"].median())),
        "win_rate": _round(float((clean["label"] > 0).mean())),
        "avg_candidates_per_date": _round(float(clean.groupby("date").size().mean())),
        "daily_equal_weight_mean_return": _round(float(by_date.mean())),
    }


def _delta(filtered: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "candidate_count",
        "n_symbols",
        "n_dates",
        "mean_forward_return",
        "median_forward_return",
        "win_rate",
        "avg_candidates_per_date",
        "daily_equal_weight_mean_return",
    ]
    out: dict[str, Any] = {}
    for key in keys:
        left = filtered.get(key)
        right = baseline.get(key)
        out[key] = _round(float(left) - float(right)) if left is not None and right is not None else None
    return out


def filter_top_decile_candidates(predictions: pd.DataFrame, *, top_pct: float = TOP_DECILE_PCT) -> pd.DataFrame:
    """Keep the highest classifier-probability rows per validation date."""
    if predictions.empty:
        return predictions.copy()
    kept: list[pd.DataFrame] = []
    for _, group in predictions.groupby("date", sort=True):
        kept.append(group.loc[_top_indices(group["pred"], top_pct=top_pct)])
    return pd.concat(kept, ignore_index=True) if kept else predictions.iloc[0:0].copy()


def build_candidate_ab(predictions: pd.DataFrame, *, horizon: int, top_pct: float = TOP_DECILE_PCT) -> dict[str, Any]:
    baseline = predictions.copy()
    filtered = filter_top_decile_candidates(predictions, top_pct=top_pct)
    baseline_stride = stride_predictions(baseline, stride=horizon)
    filtered_stride = stride_predictions(filtered, stride=horizon)
    baseline_metrics = _candidate_return_metrics(baseline)
    filtered_metrics = _candidate_return_metrics(filtered)
    baseline_stride_metrics = _candidate_return_metrics(baseline_stride)
    filtered_stride_metrics = _candidate_return_metrics(filtered_stride)
    return {
        "top_pct": _round(top_pct),
        "baseline_definition": "all validation-window symbol-date rows from the M27.1b panel before this filter",
        "filtered_definition": "daily top-decile rows by the M27.1b raw horizon top-decile classifier probability",
        "baseline_entry_candidates": baseline_metrics,
        "top_decile_filtered_candidates": filtered_metrics,
        "delta_filtered_minus_baseline": _delta(filtered_metrics, baseline_metrics),
        "non_overlapping_stride": {
            "stride": horizon,
            "baseline_entry_candidates": baseline_stride_metrics,
            "top_decile_filtered_candidates": filtered_stride_metrics,
            "delta_filtered_minus_baseline": _delta(filtered_stride_metrics, baseline_stride_metrics),
        },
    }


def _top_decile_predictions(
    panel: pd.DataFrame,
    *,
    horizon: int,
    n_estimators: int,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    panel = add_objective_labels(panel, horizon)
    raw_label = f"label_{horizon}d"
    cols = list(dict.fromkeys(["date", "symbol", raw_label, *FEATURE_COLS]))
    data = panel[cols].replace([np.inf, -np.inf], np.nan).dropna(subset=[raw_label, *FEATURE_COLS])
    train_df, val_df = _time_split(data)
    sample = {
        "n_rows": int(len(data)),
        "train_rows": int(len(train_df)),
        "validation_rows": int(len(val_df)),
        "n_symbols": int(data["symbol"].nunique()) if not data.empty else 0,
        "validation_start": str(pd.to_datetime(val_df["date"]).min().date()) if not val_df.empty else None,
        "validation_end": str(pd.to_datetime(val_df["date"]).max().date()) if not val_df.empty else None,
    }
    if len(train_df) < 200 or len(val_df) < 50:
        return None, {"status": "insufficient_data", "sample": sample}

    pred, fit_info = _fit_predict(
        train_df,
        val_df,
        objective="top_decile_classifier",
        target_label_col=raw_label,
        n_estimators=n_estimators,
    )
    if pred is None:
        return None, {"status": fit_info.get("status", "fit_failed"), "sample": sample, "fit": fit_info}
    return _validation_frame(val_df, pred, raw_label), {"status": "ok", "sample": sample, "fit": fit_info}


def build_report(
    panel: pd.DataFrame,
    *,
    panel_meta: dict[str, Any],
    horizon: int = DEFAULT_HORIZON,
    n_estimators: int = 120,
    top_pct: float = TOP_DECILE_PCT,
) -> dict[str, Any]:
    predictions, info = _top_decile_predictions(panel, horizon=horizon, n_estimators=n_estimators)
    classifier_validation = None
    candidate_ab = None
    decile_overlap = None
    if predictions is not None:
        sample = info.get("sample") or {}
        classifier_validation = build_validation_report(
            predictions,
            label=f"m27_1c_raw_{horizon}d_top_decile_filter_classifier",
            sample=sample,
        )
        candidate_ab = build_candidate_ab(predictions, horizon=horizon, top_pct=top_pct)
        decile_overlap = top_decile_metrics(predictions, top_pct=top_pct)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.1c",
        "purpose": "read-only offline A/B for a top-decile classifier entry filter",
        "run_mode": "offline_read_only_validation",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "model_promotion": "disabled",
        "note": (
            "Diagnostic report only: compares validation-window candidate pools and does not modify "
            "aggregator, scheduler, config, DB rows, or production model artifacts."
        ),
        "panel": panel_meta,
        "horizon": horizon,
        "n_estimators": n_estimators,
        "top_pct": _round(top_pct),
        "classifier": info,
        "classifier_raw_return_validation": classifier_validation,
        "top_decile_overlap_metrics": decile_overlap,
        "candidate_ab": candidate_ab,
        "decision": {
            "decision": "production_unchanged",
            "recommended_next_action": "review_offline_filter_ab_before_any_separate_trading_backtest",
        },
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    panel = report.get("panel") or {}
    classifier = report.get("classifier") or {}
    validation = report.get("classifier_raw_return_validation") or {}
    metrics = validation.get("metrics") or {}
    gates = validation.get("gates") or {}
    ab = report.get("candidate_ab") or {}
    baseline = ab.get("baseline_entry_candidates") or {}
    filtered = ab.get("top_decile_filtered_candidates") or {}
    delta = ab.get("delta_filtered_minus_baseline") or {}
    stride = ab.get("non_overlapping_stride") or {}
    stride_delta = stride.get("delta_filtered_minus_baseline") or {}
    lines = [
        "# M27.1c Top-Decile Filter A/B",
        "",
        f"- generated_at: {report.get('generated_at')}",
        f"- run_mode: {report.get('run_mode')}",
        f"- non_promoting: {report.get('non_promoting')}",
        f"- production_unchanged: {report.get('production_unchanged')}",
        f"- writes_db: {report.get('writes_db')}",
        f"- calls_llm_or_api: {report.get('calls_llm_or_api')}",
        f"- saves_model: {report.get('saves_model')}",
        f"- panel: {panel.get('n_rows')} rows / {panel.get('n_symbols')} symbols / cache_hit={panel.get('cache_hit')}",
        f"- window: {panel.get('start')} ~ {panel.get('end')}",
        f"- horizon: {report.get('horizon')}d / top_pct={report.get('top_pct')}",
        f"- classifier_status: {classifier.get('status')}",
        "",
        "## Classifier Validation",
        "",
        f"- IC: {metrics.get('ic_mean')} / ICIR: {metrics.get('icir')} / monotonic: {gates.get('pass_monotonic')}",
        f"- production gate pass: {gates.get('pass')}",
        "",
        "## Candidate A/B",
        "",
        f"- baseline_definition: {ab.get('baseline_definition')}",
        f"- filtered_definition: {ab.get('filtered_definition')}",
        "",
        "| pool | candidates | symbols | dates | mean fwd return | win rate | avg/day | daily ew return |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| baseline | {baseline.get('candidate_count')} | {baseline.get('n_symbols')} | "
        f"{baseline.get('n_dates')} | {baseline.get('mean_forward_return')} | {baseline.get('win_rate')} | "
        f"{baseline.get('avg_candidates_per_date')} | {baseline.get('daily_equal_weight_mean_return')} |",
        f"| filtered | {filtered.get('candidate_count')} | {filtered.get('n_symbols')} | "
        f"{filtered.get('n_dates')} | {filtered.get('mean_forward_return')} | {filtered.get('win_rate')} | "
        f"{filtered.get('avg_candidates_per_date')} | {filtered.get('daily_equal_weight_mean_return')} |",
        f"| delta | {delta.get('candidate_count')} | {delta.get('n_symbols')} | {delta.get('n_dates')} | "
        f"{delta.get('mean_forward_return')} | {delta.get('win_rate')} | "
        f"{delta.get('avg_candidates_per_date')} | {delta.get('daily_equal_weight_mean_return')} |",
        "",
        "## Non-Overlapping Stride",
        "",
        f"- stride: {stride.get('stride')}",
        f"- delta_mean_forward_return: {stride_delta.get('mean_forward_return')}",
        f"- delta_daily_equal_weight_mean_return: {stride_delta.get('daily_equal_weight_mean_return')}",
        "",
        "## Decision",
        "",
        f"- decision: {(report.get('decision') or {}).get('decision')}",
        f"- recommended_next_action: {(report.get('decision') or {}).get('recommended_next_action')}",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--n-estimators", type=int, default=120)
    parser.add_argument("--top-pct", type=float, default=TOP_DECILE_PCT)
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--active-only", action="store_true", default=True)
    parser.add_argument("--include-inactive", action="store_true")
    parser.add_argument("--refresh-panel-cache", action="store_true")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    active_only = not args.include_inactive
    db = SessionLocal()
    try:
        panel, meta = load_or_build_panel(
            db,
            active_only=active_only,
            min_rows=args.min_rows,
            refresh_cache=args.refresh_panel_cache,
        )
    finally:
        db.close()

    report = build_report(
        panel,
        panel_meta=meta,
        horizon=args.horizon,
        n_estimators=args.n_estimators,
        top_pct=args.top_pct,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    else:
        print(f"JSON report: {args.json_output}")
        print(f"Markdown report: {args.markdown_output}")
        print(f"Decision: {report['decision']['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
