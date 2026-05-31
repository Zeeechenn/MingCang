"""M27.1c read-only forward shadow for the top-decile entry filter.

This diagnostic trains the M27.1b top-decile classifier only on rows with
realized labels before the shadow window, then predicts eligibility for target
window rows using features only. It does not promote, persist a model, write DB
rows, call LLM/API, or modify production signal profiles. Like the M27.1b
tools, it may read or refresh the local training-panel cache under
``~/.stock-sage/cache``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.backtest.backfill_signals import backfill_window
from backend.config import active_signal_weights
from backend.data.database import SessionLocal
from backend.data.qlib_data import FEATURE_COLS
from backend.tools.m27_alpha_diagnostic import _load_universe_symbols
from backend.tools.m27_label_objective_eval import (
    DEFAULT_HORIZON,
    TOP_DECILE_PCT,
    _round,
    _top_decile_labels,
    add_objective_labels,
    load_or_build_panel,
)
from backend.tools.m27_test3_production_profile_ab import (
    DEFAULT_UNIVERSE_PATH,
    build_profile_ab,
)
from backend.tools.m27_test3_production_profile_ab import (
    report_to_markdown as profile_report_to_markdown,
)
from backend.tools.m27_top_decile_filter_ab import filter_top_decile_candidates

DEFAULT_OUTPUT_DIR = Path.home() / ".stock-sage"
DEFAULT_OUTPUT_STEM = "m27_top_decile_forward_shadow"
DEFAULT_START = "2026-05-15"
DEFAULT_END = "2026-05-22"
MIN_TRADES_FOR_SHARPE = 50
DEFAULT_ROLLING_WINDOW_DAYS = 7
DEFAULT_ROLLING_STRIDE_DAYS = 7


def _hash_jsonable(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _universe_hash(universe_symbols: set[str]) -> str:
    return _hash_jsonable(sorted(universe_symbols))


def _provenance_fields(
    *,
    panel_meta: dict[str, Any],
    universe_symbols: set[str],
    classifier_sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sample = classifier_sample or {}
    return {
        "data_source": panel_meta.get("data_source"),
        "fetched_at": panel_meta.get("fetched_at"),
        "adjustment": panel_meta.get("adjustment"),
        "universe_hash": _universe_hash(universe_symbols),
        "train_label_realized_end": sample.get("train_label_realized_end"),
    }


def _date_str(value: Any) -> str:
    return str(pd.to_datetime(value).date())


def _with_label_realized_date(panel: pd.DataFrame, *, horizon: int) -> pd.DataFrame:
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["symbol", "date"]).copy()
    out["_label_realized_date"] = out.groupby("symbol", sort=False)["date"].shift(-horizon)
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def _target_predictions(
    panel: pd.DataFrame,
    *,
    universe_symbols: set[str],
    start: str,
    end: str,
    horizon: int,
    n_estimators: int,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    labeled = _with_label_realized_date(add_objective_labels(panel, horizon), horizon=horizon)
    raw_label = f"label_{horizon}d"
    realized_col = "_label_realized_date"
    cols = list(dict.fromkeys(["date", "symbol", realized_col, raw_label, *FEATURE_COLS]))
    data = labeled[labeled["symbol"].isin(universe_symbols)][cols].copy()
    data["date"] = pd.to_datetime(data["date"])
    data[realized_col] = pd.to_datetime(data[realized_col])
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)

    train_df = (
        data[(data["date"] < start_ts) & (data[realized_col] < start_ts)]
        .replace([np.inf, -np.inf], np.nan)
        .dropna(subset=[raw_label, realized_col, *FEATURE_COLS])
        .copy()
    )
    target_df = (
        data[(data["date"] >= start_ts) & (data["date"] <= end_ts)]
        .replace([np.inf, -np.inf], np.nan)
        .dropna(subset=FEATURE_COLS)
        .copy()
    )

    sample = {
        "train_rows": int(len(train_df)),
        "target_rows": int(len(target_df)),
        "train_symbols": int(train_df["symbol"].nunique()) if not train_df.empty else 0,
        "target_symbols": int(target_df["symbol"].nunique()) if not target_df.empty else 0,
        "train_start": _date_str(train_df["date"].min()) if not train_df.empty else None,
        "train_end": _date_str(train_df["date"].max()) if not train_df.empty else None,
        "train_label_realized_end": _date_str(train_df[realized_col].max()) if not train_df.empty else None,
        "target_start": start,
        "target_end": end,
    }
    if len(train_df) < 200 or len(target_df) == 0:
        return None, {"status": "insufficient_data", "sample": sample}

    try:
        import lightgbm as lgb
    except ImportError:
        return None, {"status": "lightgbm_unavailable", "sample": sample}

    y_train = _top_decile_labels(train_df, raw_label)
    if y_train.nunique() < 2:
        return None, {"status": "single_class_label", "sample": sample}

    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=n_estimators,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(train_df[FEATURE_COLS], y_train)
    pred = model.predict_proba(target_df[FEATURE_COLS])[:, 1]
    out = target_df[["date", "symbol"]].copy()
    out["date"] = out["date"].map(_date_str)
    out["pred"] = pred
    return out, {"status": "ok", "sample": sample, "fit": {"status": "ok", "best_iteration": None}}


def _allowed_filter_keys(predictions: pd.DataFrame, *, top_pct: float) -> tuple[set[tuple[str, str]], dict[str, Any]]:
    filtered = filter_top_decile_candidates(predictions, top_pct=top_pct)
    allowed = {(str(row.date)[:10], str(row.symbol)) for row in filtered.itertuples(index=False)}
    by_date = filtered.groupby("date").size().to_dict() if not filtered.empty else {}
    return allowed, {
        "status": "ok",
        "target_prediction_rows": int(len(predictions)),
        "allowed_filter_keys": int(len(allowed)),
        "allowed_by_date": {str(k): int(v) for k, v in by_date.items()},
        "target_start": str(predictions["date"].min()) if not predictions.empty else None,
        "target_end": str(predictions["date"].max()) if not predictions.empty else None,
    }


def build_report(
    panel: pd.DataFrame,
    *,
    panel_meta: dict[str, Any],
    inputs: list[Any],
    universe_symbols: set[str],
    start: str,
    end: str,
    horizon: int = DEFAULT_HORIZON,
    n_estimators: int = 120,
    top_pct: float = TOP_DECILE_PCT,
    exit_days: int = 5,
) -> dict[str, Any]:
    predictions, classifier = _target_predictions(
        panel,
        universe_symbols=universe_symbols,
        start=start,
        end=end,
        horizon=horizon,
        n_estimators=n_estimators,
    )
    allowed: set[tuple[str, str]] = set()
    filter_info: dict[str, Any] = {"status": classifier.get("status"), "classifier": classifier}
    if predictions is not None:
        allowed, filter_info = _allowed_filter_keys(predictions, top_pct=top_pct)
        filter_info["classifier"] = classifier
    weights = active_signal_weights()
    profile_ab = build_profile_ab(
        inputs,
        allowed_filter_keys=allowed,
        exit_days=exit_days,
        entry_threshold=weights.entry_threshold,
    )
    filtered_trades = int(profile_ab["filtered_arm"]["metrics"]["trades"])
    baseline_trades = int(profile_ab["baseline_arm"]["metrics"]["trades"])
    classifier_sample = (classifier.get("sample") or {}) if isinstance(classifier, dict) else {}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.1c",
        "purpose": "read-only forward shadow for top-decile entry filter",
        "run_mode": "offline_read_only_forward_shadow",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "model_promotion": "disabled",
        "signal_profile_unchanged": True,
        **_provenance_fields(
            panel_meta=panel_meta,
            universe_symbols=universe_symbols,
            classifier_sample=classifier_sample,
        ),
        "universe_symbols": len(universe_symbols),
        "start": start,
        "end": end,
        "horizon": horizon,
        "exit_days": exit_days,
        "top_pct": _round(top_pct),
        "panel": panel_meta,
        "filter": filter_info,
        "sample_adequacy": {
            "filtered_trades": filtered_trades,
            "baseline_trades": baseline_trades,
            "min_trades_for_sharpe": MIN_TRADES_FOR_SHARPE,
            "insufficient_for_sharpe": filtered_trades < MIN_TRADES_FOR_SHARPE,
        },
        "profile_ab": profile_ab,
        "decision": {
            "decision": "production_unchanged",
            "recommended_next_action": (
                "continue_forward_shadow"
                if baseline_trades and filtered_trades
                else "collect_more_forward_overlap_before_any_promotion"
            ),
        },
    }


def rolling_windows(
    start: str,
    end: str,
    *,
    window_days: int = DEFAULT_ROLLING_WINDOW_DAYS,
    stride_days: int = DEFAULT_ROLLING_STRIDE_DAYS,
) -> list[dict[str, str]]:
    if window_days <= 0 or stride_days <= 0:
        raise ValueError("window_days and stride_days must be positive")
    start_ts = pd.to_datetime(start).normalize()
    end_ts = pd.to_datetime(end).normalize()
    if start_ts > end_ts:
        raise ValueError("start must be on or before end")

    windows: list[dict[str, str]] = []
    current = start_ts
    while current <= end_ts:
        window_end = min(current + pd.Timedelta(days=window_days - 1), end_ts)
        windows.append({"start": _date_str(current), "end": _date_str(window_end)})
        current = current + pd.Timedelta(days=stride_days)
    return windows


def _trades(report: dict[str, Any], arm: str) -> int:
    return int((((report.get("profile_ab") or {}).get(arm) or {}).get("metrics") or {}).get("trades") or 0)


def _profile_metric(report: dict[str, Any], arm: str, metric: str) -> float | None:
    value = (((report.get("profile_ab") or {}).get(arm) or {}).get("metrics") or {}).get(metric)
    return None if value is None else float(value)


def _avg_net_return_delta(report: dict[str, Any]) -> float | None:
    value = ((report.get("profile_ab") or {}).get("delta_filtered_minus_baseline") or {}).get("avg_net_return")
    return None if value is None else float(value)


def _trade_weighted_delta(window_reports: list[dict[str, Any]]) -> float | None:
    weighted: list[tuple[float, int]] = []
    for report in window_reports:
        delta = _avg_net_return_delta(report)
        weight = _trades(report, "filtered_arm")
        if delta is not None and weight > 0:
            weighted.append((delta, weight))
    total_weight = sum(weight for _, weight in weighted)
    if total_weight <= 0:
        return None
    return _round(sum(delta * weight for delta, weight in weighted) / total_weight)


def build_rolling_report(
    window_reports: list[dict[str, Any]],
    *,
    start: str,
    end: str,
    horizon: int,
    exit_days: int,
    top_pct: float,
    window_days: int,
    stride_days: int,
    panel_meta: dict[str, Any],
    universe_symbols: set[str],
) -> dict[str, Any]:
    baseline_trades = sum(_trades(report, "baseline_arm") for report in window_reports)
    filtered_trades = sum(_trades(report, "filtered_arm") for report in window_reports)
    label_cutoffs = [
        cutoff
        for report in window_reports
        for cutoff in [
            (((report.get("filter") or {}).get("classifier") or {}).get("sample") or {}).get(
                "train_label_realized_end"
            )
            or report.get("train_label_realized_end")
        ]
        if cutoff
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.1c",
        "purpose": "read-only rolling forward shadow for top-decile entry filter",
        "run_mode": "offline_read_only_forward_shadow_rolling",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "model_promotion": "disabled",
        "signal_profile_unchanged": True,
        **_provenance_fields(panel_meta=panel_meta, universe_symbols=universe_symbols),
        "train_label_realized_end": max(label_cutoffs) if label_cutoffs else None,
        "train_label_realized_end_range": {
            "min": min(label_cutoffs) if label_cutoffs else None,
            "max": max(label_cutoffs) if label_cutoffs else None,
        },
        "universe_symbols": len(universe_symbols),
        "start": start,
        "end": end,
        "horizon": horizon,
        "exit_days": exit_days,
        "top_pct": _round(top_pct),
        "panel": panel_meta,
        "rolling": {
            "window_days": window_days,
            "stride_days": stride_days,
            "window_count": len(window_reports),
            "windows_with_filtered_trades": sum(
                1 for report in window_reports if _trades(report, "filtered_arm") > 0
            ),
        },
        "aggregate_profile_summary": {
            "ok_windows": sum(
                1 for report in window_reports if ((report.get("filter") or {}).get("status") == "ok")
            ),
            "windows_with_filtered_trades": sum(
                1 for report in window_reports if _trades(report, "filtered_arm") > 0
            ),
            "positive_avg_net_return_delta_windows": sum(
                1 for report in window_reports if (_avg_net_return_delta(report) or 0.0) > 0
            ),
            "baseline_trades_total": baseline_trades,
            "filtered_trades_total": filtered_trades,
            "trade_weighted_avg_net_return_delta": _trade_weighted_delta(window_reports),
        },
        "sample_adequacy": {
            "filtered_trades": filtered_trades,
            "baseline_trades": baseline_trades,
            "min_trades_for_sharpe": MIN_TRADES_FOR_SHARPE,
            "insufficient_for_sharpe": filtered_trades < MIN_TRADES_FOR_SHARPE,
        },
        "windows": window_reports,
        "decision": {
            "decision": "production_unchanged",
            "recommended_next_action": (
                "continue_forward_shadow"
                if filtered_trades >= MIN_TRADES_FOR_SHARPE
                else "collect_more_forward_overlap_before_any_promotion"
            ),
        },
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    if report.get("run_mode") == "offline_read_only_forward_shadow_rolling":
        return rolling_report_to_markdown(report)

    markdown = profile_report_to_markdown(report)
    markdown = markdown.replace(
        "# M27.1c Test3 Production-Profile A/B",
        "# M27.1c Top-Decile Forward Shadow",
        1,
    )
    adequacy = report.get("sample_adequacy") or {}
    if not adequacy:
        return markdown
    return "\n".join([
        markdown,
        "## Sample Adequacy",
        "",
        f"- filtered_trades: {adequacy.get('filtered_trades')}",
        f"- baseline_trades: {adequacy.get('baseline_trades')}",
        f"- min_trades_for_sharpe: {adequacy.get('min_trades_for_sharpe')}",
        f"- insufficient_for_sharpe: {adequacy.get('insufficient_for_sharpe')}",
        "",
    ])


def rolling_report_to_markdown(report: dict[str, Any]) -> str:
    adequacy = report.get("sample_adequacy") or {}
    rolling = report.get("rolling") or {}
    lines = [
        "# M27.1c Top-Decile Forward Shadow Rolling",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- run_mode: {report['run_mode']}",
        f"- non_promoting: {report['non_promoting']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- saves_model: {report['saves_model']}",
        f"- window: {report['start']} ~ {report['end']}",
        f"- exit_days: {report['exit_days']}",
        f"- rolling_window_days: {rolling.get('window_days')}",
        f"- rolling_stride_days: {rolling.get('stride_days')}",
        f"- window_count: {rolling.get('window_count')}",
        "",
        "## Sample Adequacy",
        "",
        f"- filtered_trades: {adequacy.get('filtered_trades')}",
        f"- baseline_trades: {adequacy.get('baseline_trades')}",
        f"- min_trades_for_sharpe: {adequacy.get('min_trades_for_sharpe')}",
        f"- insufficient_for_sharpe: {adequacy.get('insufficient_for_sharpe')}",
        "",
        "## Windows",
        "",
        "| start | end | baseline trades | filtered trades | insufficient_for_sharpe |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for window_report in report.get("windows") or []:
        window_adequacy = window_report.get("sample_adequacy") or {}
        lines.append(
            f"| {window_report.get('start')} | {window_report.get('end')} | "
            f"{window_adequacy.get('baseline_trades')} | {window_adequacy.get('filtered_trades')} | "
            f"{window_adequacy.get('insufficient_for_sharpe')} |"
        )
    lines.extend([
        "",
        "## Decision",
        "",
        f"- decision: {report['decision']['decision']}",
        f"- recommended_next_action: {report['decision']['recommended_next_action']}",
        "",
    ])
    return "\n".join(lines)


def _compact_date(value: str) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def default_output_paths(
    exit_days: int,
    *,
    rolling: bool = False,
    start: str | None = None,
    end: str | None = None,
) -> tuple[Path, Path]:
    if rolling and start and end:
        suffix = f"rolling_{_compact_date(start)}_{_compact_date(end)}_{exit_days}d"
    else:
        suffix = f"rolling_{exit_days}d" if rolling else f"{exit_days}d"
    stem = f"{DEFAULT_OUTPUT_STEM}_{suffix}"
    return DEFAULT_OUTPUT_DIR / f"{stem}.json", DEFAULT_OUTPUT_DIR / f"{stem}.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-path", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--exit-days", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--n-estimators", type=int, default=120)
    parser.add_argument("--top-pct", type=float, default=TOP_DECILE_PCT)
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--refresh-panel-cache", action="store_true")
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--rolling-window-days", type=int, default=DEFAULT_ROLLING_WINDOW_DAYS)
    parser.add_argument("--rolling-stride-days", type=int, default=DEFAULT_ROLLING_STRIDE_DAYS)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    default_json_output, default_markdown_output = default_output_paths(
        args.exit_days,
        rolling=args.rolling,
        start=args.start,
        end=args.end,
    )
    json_output = (args.json_output or default_json_output).expanduser()
    markdown_output = (args.markdown_output or default_markdown_output).expanduser()
    universe_symbols = _load_universe_symbols(args.universe_path)
    db = SessionLocal()
    try:
        panel, meta = load_or_build_panel(
            db,
            active_only=False,
            min_rows=args.min_rows,
            refresh_cache=args.refresh_panel_cache,
        )
    finally:
        db.close()
    if args.rolling:
        window_reports = []
        for window in rolling_windows(
            args.start,
            args.end,
            window_days=args.rolling_window_days,
            stride_days=args.rolling_stride_days,
        ):
            inputs = backfill_window(
                window["start"],
                window["end"],
                symbols=sorted(universe_symbols),
                use_llm_news=False,
                every_n_days=args.exit_days,
                allow_lookahead_quant=False,
            )
            window_reports.append(
                build_report(
                    panel,
                    panel_meta=meta,
                    inputs=inputs,
                    universe_symbols=universe_symbols,
                    start=window["start"],
                    end=window["end"],
                    horizon=args.horizon,
                    n_estimators=args.n_estimators,
                    top_pct=args.top_pct,
                    exit_days=args.exit_days,
                )
            )
        report = build_rolling_report(
            window_reports,
            start=args.start,
            end=args.end,
            horizon=args.horizon,
            exit_days=args.exit_days,
            top_pct=args.top_pct,
            window_days=args.rolling_window_days,
            stride_days=args.rolling_stride_days,
            panel_meta=meta,
            universe_symbols=universe_symbols,
        )
    else:
        inputs = backfill_window(
            args.start,
            args.end,
            symbols=sorted(universe_symbols),
            use_llm_news=False,
            every_n_days=args.exit_days,
            allow_lookahead_quant=False,
        )
        report = build_report(
            panel,
            panel_meta=meta,
            inputs=inputs,
            universe_symbols=universe_symbols,
            start=args.start,
            end=args.end,
            horizon=args.horizon,
            n_estimators=args.n_estimators,
            top_pct=args.top_pct,
            exit_days=args.exit_days,
        )
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    markdown_output.write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
