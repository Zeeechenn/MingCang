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
from backend.analysis.qlib_engine import daily_rank_groups, make_rank_labels
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
        q = {"quantiles": [], "top_bottom": None, "monotonic": False}
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
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true", help="Print markdown report to stdout")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db = SessionLocal()
    try:
        panel = build_training_data(db, min_rows=args.min_rows, include_inactive=not args.active_only)
        report = build_report(panel, horizons=args.horizons, top_n=args.top_n)
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
