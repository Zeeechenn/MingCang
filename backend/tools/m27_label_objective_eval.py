"""M27.1b label/objective evaluation.

This local-only tool tests whether changing the alpha label or objective is
more promising than adding more factors. It never promotes a model and writes
candidate reports under ``~/.stock-sage``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.analysis.qlib_engine import _time_split, daily_rank_groups, make_rank_labels
from backend.backtest.alphalens_qlib import build_validation_report
from backend.config import settings
from backend.data.database import SessionLocal
from backend.data.qlib_data import FEATURE_COLS, build_training_data
from backend.tools.m27_alpha_diagnostic import add_horizon_labels

DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m27_label_objective_eval_report.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m27_label_objective_eval_report.md"
DEFAULT_CACHE_DIR = Path.home() / ".stock-sage" / "cache"
DEFAULT_HORIZON = 20
TOP_DECILE_PCT = 0.10
DEFAULT_SEGMENT_MIN_ROWS = 250
DEFAULT_SEGMENT_MIN_SYMBOLS = 4
DEFAULT_SEGMENT_MIN_VALIDATION_ROWS = 50

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


def _cache_paths(*, active_only: bool, min_rows: int) -> tuple[Path, Path]:
    scope = "active" if active_only else "full"
    stem = f"m27_training_panel_{scope}_min{min_rows}"
    return DEFAULT_CACHE_DIR / f"{stem}.pkl", DEFAULT_CACHE_DIR / f"{stem}.meta.json"


def _feature_cols_meta() -> dict[str, Any]:
    feature_cols = list(FEATURE_COLS)
    payload = json.dumps(feature_cols, ensure_ascii=True, separators=(",", ":"))
    return {
        "feature_count": len(feature_cols),
        "feature_cols_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "feature_cols": feature_cols,
    }


def _cache_matches_current_features(meta: dict[str, Any]) -> bool:
    current = _feature_cols_meta()
    return (
        meta.get("feature_count") == current["feature_count"]
        and meta.get("feature_cols_hash") == current["feature_cols_hash"]
        and meta.get("feature_cols") == current["feature_cols"]
    )


def _panel_summary(panel: pd.DataFrame) -> dict[str, Any]:
    if panel.empty:
        return {"n_rows": 0, "n_symbols": 0, "n_dates": 0, "start": None, "end": None}
    dates = pd.to_datetime(panel["date"])
    return {
        "n_rows": int(len(panel)),
        "n_symbols": int(panel["symbol"].nunique()) if "symbol" in panel.columns else 0,
        "n_dates": int(dates.nunique()),
        "start": str(dates.min().date()),
        "end": str(dates.max().date()),
    }


def load_or_build_panel(
    db,
    *,
    active_only: bool = True,
    min_rows: int = 120,
    refresh_cache: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the expensive training panel from local cache, or rebuild it."""
    cache_path, meta_path = _cache_paths(active_only=active_only, min_rows=min_rows)
    if cache_path.exists() and meta_path.exists() and not refresh_cache:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if _cache_matches_current_features(meta):
            panel = pd.read_pickle(cache_path)
            meta["cache_hit"] = True
            return panel, meta

    panel = build_training_data(db, min_rows=min_rows, include_inactive=not active_only)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_pickle(cache_path)
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cache_hit": False,
        "active_only": active_only,
        "min_rows": min_rows,
        "path": str(cache_path),
        **_panel_summary(panel),
        **_feature_cols_meta(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return panel, meta


def neutralize_by_date(
    panel: pd.DataFrame,
    label_col: str,
    *,
    industry: bool = False,
    size: bool = False,
) -> pd.Series:
    """Return a date-local residual label after optional industry/size neutralization."""
    out = pd.to_numeric(panel[label_col], errors="coerce").copy()
    if industry and "industry" in panel.columns:
        out = out - panel.assign(_label=out).groupby(["date", "industry"])["_label"].transform("mean")
    if size and "log_market_cap" in panel.columns:
        source = panel.assign(_label=out)
        residual = pd.Series(index=panel.index, dtype="float64")
        for _, idx in source.groupby("date", sort=False).groups.items():
            residual.loc[idx] = _size_residual(source.loc[idx])
        out = residual
    return out.clip(-0.30, 0.30)


def _size_residual(group: pd.DataFrame) -> pd.Series:
    data = group[["_label", "log_market_cap"]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 5 or data["log_market_cap"].nunique() < 2:
        return group["_label"] - group["_label"].mean()
    x = data["log_market_cap"].to_numpy(dtype=float)
    y = data["_label"].to_numpy(dtype=float)
    beta, alpha = np.polyfit(x, y, 1)
    residual = group["_label"] - (alpha + beta * group["log_market_cap"])
    return residual.mask(residual.abs() < 1e-12, 0.0)


def add_objective_labels(panel: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Add raw and neutralized objective labels for one horizon."""
    out = add_horizon_labels(panel, [horizon])
    raw = f"label_{horizon}d"
    out[f"label_{horizon}d_industry_neutral"] = neutralize_by_date(out, raw, industry=True)
    out[f"label_{horizon}d_size_neutral"] = neutralize_by_date(out, raw, size=True)
    out[f"label_{horizon}d_industry_size_neutral"] = neutralize_by_date(out, raw, industry=True, size=True)
    return out


def _top_indices(values: pd.Series, *, top_pct: float) -> pd.Index:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return clean.index
    n_top = min(len(clean), max(1, int(np.ceil(len(clean) * top_pct))))
    return clean.sort_values(ascending=False, kind="mergesort").head(n_top).index


def _top_decile_labels(df: pd.DataFrame, label_col: str, top_pct: float = TOP_DECILE_PCT) -> pd.Series:
    labels = pd.Series(0, index=df.index, dtype="int64")
    for _, group in df.groupby("date", sort=False):
        labels.loc[_top_indices(group[label_col], top_pct=top_pct)] = 1
    return labels


def _validation_frame(
    val_df: pd.DataFrame,
    pred: np.ndarray,
    label_col: str,
    *,
    segment_cols: list[str] | None = None,
) -> pd.DataFrame:
    frame = pd.DataFrame({
        "date": val_df["date"].values,
        "symbol": val_df["symbol"].values,
        "pred": pred,
        "label": val_df[label_col].values,
    })
    for col in segment_cols or []:
        if col in val_df.columns:
            frame[col] = val_df[col].values
    return frame


def stride_predictions(predictions: pd.DataFrame, *, stride: int) -> pd.DataFrame:
    """Keep every Nth validation date to reduce overlapping-horizon inflation."""
    if stride <= 1 or predictions.empty:
        return predictions
    dates = pd.Series(pd.to_datetime(predictions["date"]).drop_duplicates().sort_values().values)
    keep_dates = set(dates.iloc[::stride])
    return predictions[pd.to_datetime(predictions["date"]).isin(keep_dates)].copy()


def top_decile_metrics(predictions: pd.DataFrame, *, top_pct: float = TOP_DECILE_PCT) -> dict[str, Any]:
    """Evaluate whether top predicted names overlap the realized top decile."""
    rows: list[dict[str, float]] = []
    for date, group in predictions.groupby("date", sort=True):
        data = group[["pred", "label"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < 5:
            continue
        top_pred = data.loc[_top_indices(data["pred"], top_pct=top_pct)]
        realized_cut = pd.Series(False, index=data.index)
        realized_cut.loc[_top_indices(data["label"], top_pct=top_pct)] = True
        rows.append({
            "date": date,
            "precision": float(realized_cut.loc[top_pred.index].mean()),
            "base_rate": float(realized_cut.mean()),
            "mean_forward_return": float(top_pred["label"].mean()),
            "universe_mean_forward_return": float(data["label"].mean()),
        })
    if not rows:
        return {}
    frame = pd.DataFrame(rows)
    return {
        "n_dates": int(len(frame)),
        "top_pct": _round(top_pct),
        "precision": _round(float(frame["precision"].mean())),
        "base_rate": _round(float(frame["base_rate"].mean())),
        "lift_vs_base_rate": _round(float(frame["precision"].mean() / frame["base_rate"].mean()))
        if frame["base_rate"].mean() > 0
        else None,
        "mean_forward_return": _round(float(frame["mean_forward_return"].mean())),
        "excess_forward_return": _round(
            float((frame["mean_forward_return"] - frame["universe_mean_forward_return"]).mean())
        ),
    }


def segment_breakdown(
    predictions: pd.DataFrame,
    *,
    segment_col: str,
    min_rows: int = 50,
    min_dates: int = 5,
    min_symbols: int = 3,
) -> list[dict[str, Any]]:
    """Report raw validation quality by segment without changing the objective."""
    if predictions.empty or segment_col not in predictions.columns:
        return []

    rows: list[dict[str, Any]] = []
    for segment, group in predictions.groupby(segment_col, dropna=False, sort=True):
        clean = group.dropna(subset=["pred", "label"])
        n_dates = int(pd.to_datetime(clean["date"]).nunique()) if not clean.empty else 0
        n_symbols = int(clean["symbol"].nunique()) if not clean.empty else 0
        if len(clean) < min_rows or n_dates < min_dates or n_symbols < min_symbols:
            continue
        report = build_validation_report(
            clean[["date", "symbol", "pred", "label"]],
            label=f"{segment_col}:{segment}",
            sample={
                "segment_col": segment_col,
                "segment": None if pd.isna(segment) else str(segment),
                "n_rows": int(len(clean)),
                "n_symbols": n_symbols,
                "n_dates": n_dates,
            },
        )
        metrics = report.get("metrics") or {}
        gates = report.get("gates") or {}
        rows.append({
            "segment_col": segment_col,
            "segment": None if pd.isna(segment) else str(segment),
            "n_rows": int(len(clean)),
            "n_symbols": n_symbols,
            "n_dates": n_dates,
            "ic_mean": metrics.get("ic_mean"),
            "icir": metrics.get("icir"),
            "ic_positive_rate": metrics.get("ic_positive_rate"),
            "top_bottom": metrics.get("top_bottom"),
            "gate_pass": gates.get("pass"),
        })

    return sorted(
        rows,
        key=lambda row: (
            float(row.get("icir") or 0.0),
            float(row.get("ic_mean") or 0.0),
            int(row.get("n_rows") or 0),
        ),
        reverse=True,
    )


def _segment_candidate_specs(horizon: int) -> list[dict[str, str]]:
    raw = f"label_{horizon}d"
    return [
        {
            "name": f"raw_{horizon}d_regression_segment_specific",
            "objective": "regression",
            "horizon": str(horizon),
            "target_label": raw,
        }
    ]


def evaluate_segment_specific_candidates(
    panel: pd.DataFrame,
    *,
    horizon: int,
    n_estimators: int,
    min_rows: int = DEFAULT_SEGMENT_MIN_ROWS,
    min_symbols: int = DEFAULT_SEGMENT_MIN_SYMBOLS,
    min_validation_rows: int = DEFAULT_SEGMENT_MIN_VALIDATION_ROWS,
) -> dict[str, Any]:
    """Train validation-only candidates inside sufficiently large sectors/industries."""
    segment_cols = [col for col in ("industry", "sector") if col in panel.columns]
    sample_limited = (
        min_rows < DEFAULT_SEGMENT_MIN_ROWS
        or min_symbols < DEFAULT_SEGMENT_MIN_SYMBOLS
        or min_validation_rows < DEFAULT_SEGMENT_MIN_VALIDATION_ROWS
    )
    result: dict[str, Any] = {
        "scope": "sector_industry_specific_offline_candidate",
        "non_promoting": True,
        "promotable": False,
        "run_mode": "exploratory_sample_limited" if sample_limited else "conservative_offline_validation",
        "sample_limited": sample_limited,
        "promotion_blocker": (
            "exploratory/sample-limited segment run; expand sample before any train-candidate promotion"
            if sample_limited
            else "offline validation only; sector/industry candidates require separate promotion review"
        ),
        "note": (
            "exploratory/sample-limited offline validation only; cannot promote and does not alter production "
            "model, promotion, or signal logic"
            if sample_limited
            else "offline validation only; does not alter production model, promotion, or signal logic"
        ),
        "min_rows": min_rows,
        "min_symbols": min_symbols,
        "min_validation_rows": min_validation_rows,
        "segment_cols": segment_cols,
        "candidates": [],
        "skipped": [],
        "best_by_segment_col": {},
    }
    if not segment_cols:
        return result

    for spec in _segment_candidate_specs(horizon):
        target_label = spec["target_label"]
        raw_label = f"label_{spec['horizon']}d"
        cols = list(dict.fromkeys(["date", "symbol", *segment_cols, target_label, raw_label, *FEATURE_COLS]))
        data = panel[cols].replace([np.inf, -np.inf], np.nan).dropna(subset=[target_label, raw_label, *FEATURE_COLS])
        for segment_col in segment_cols:
            for segment, segment_df in data.groupby(segment_col, dropna=False, sort=True):
                segment_name = None if pd.isna(segment) else str(segment)
                n_symbols = int(segment_df["symbol"].nunique())
                train_df, val_df = _time_split(segment_df)
                sample = {
                    "segment_col": segment_col,
                    "segment": segment_name,
                    "n_rows": int(len(segment_df)),
                    "n_symbols": n_symbols,
                    "n_dates": int(pd.to_datetime(segment_df["date"]).nunique()),
                    "train_rows": int(len(train_df)),
                    "validation_rows": int(len(val_df)),
                }
                if (
                    len(segment_df) < min_rows
                    or n_symbols < min_symbols
                    or len(val_df) < min_validation_rows
                ):
                    result["skipped"].append({
                        **spec,
                        "segment_col": segment_col,
                        "segment": segment_name,
                        "status": "insufficient_segment_sample",
                        "sample": sample,
                    })
                    continue

                pred, fit_info = _fit_predict(
                    train_df,
                    val_df,
                    objective=spec["objective"],
                    target_label_col=target_label,
                    n_estimators=n_estimators,
                )
                if pred is None:
                    result["skipped"].append({
                        **spec,
                        "segment_col": segment_col,
                        "segment": segment_name,
                        "status": fit_info.get("status", "fit_failed"),
                        "sample": sample,
                    })
                    continue

                raw_predictions = _validation_frame(val_df, pred, raw_label, segment_cols=[segment_col])
                target_predictions = _validation_frame(val_df, pred, target_label, segment_cols=[segment_col])
                raw_report = build_validation_report(
                    raw_predictions,
                    label=f"{spec['name']}:{segment_col}:{segment_name}:raw_return",
                    sample=sample,
                )
                target_report = build_validation_report(
                    target_predictions,
                    label=f"{spec['name']}:{segment_col}:{segment_name}:target",
                    sample=sample,
                )
                stride_sample = {**sample, "stride": int(spec["horizon"])}
                raw_stride = build_validation_report(
                    stride_predictions(raw_predictions, stride=int(spec["horizon"])),
                    label=f"{spec['name']}:{segment_col}:{segment_name}:raw_return_stride_{spec['horizon']}",
                    sample=stride_sample,
                )
                result["candidates"].append({
                    **spec,
                    "candidate_type": "sector_industry_specific",
                    "non_promoting": True,
                    "promotable": False,
                    "run_mode": result["run_mode"],
                    "sample_limited": result["sample_limited"],
                    "promotion_blocker": result["promotion_blocker"],
                    "segment_col": segment_col,
                    "segment": segment_name,
                    "status": "ok",
                    "fit": fit_info,
                    "sample": sample,
                    "target_validation": target_report,
                    "raw_return_validation": raw_report,
                    "raw_return_stride_validation": raw_stride,
                    "top_decile_metrics": top_decile_metrics(raw_predictions, top_pct=TOP_DECILE_PCT),
                })

    result["candidates"] = sorted(
        result["candidates"],
        key=lambda candidate: (
            float((((candidate.get("raw_return_validation") or {}).get("metrics") or {}).get("icir")) or 0.0),
            float((((candidate.get("raw_return_validation") or {}).get("metrics") or {}).get("ic_mean")) or 0.0),
            int(((candidate.get("sample") or {}).get("validation_rows")) or 0),
        ),
        reverse=True,
    )
    for segment_col in segment_cols:
        best = next(
            (candidate for candidate in result["candidates"] if candidate.get("segment_col") == segment_col),
            None,
        )
        if best:
            result["best_by_segment_col"][segment_col] = {
                "segment": best.get("segment"),
                "candidate": best.get("name"),
                "raw_ic": ((best.get("raw_return_validation") or {}).get("metrics") or {}).get("ic_mean"),
                "raw_icir": ((best.get("raw_return_validation") or {}).get("metrics") or {}).get("icir"),
                "raw_gate_pass": ((best.get("raw_return_validation") or {}).get("gates") or {}).get("pass"),
                "sample": best.get("sample"),
            }
    return result


def _fit_predict(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    objective: str,
    target_label_col: str,
    n_estimators: int,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    try:
        import lightgbm as lgb
    except ImportError:
        return None, {"status": "lightgbm_unavailable"}

    if objective == "regression":
        model = lgb.LGBMRegressor(
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
        model.fit(
            train_df[FEATURE_COLS],
            train_df[target_label_col],
            eval_set=[(val_df[FEATURE_COLS], val_df[target_label_col])],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=0)],
        )
        return model.predict(val_df[FEATURE_COLS]), {"status": "ok", "best_iteration": model.best_iteration_}

    if objective == "top_decile_classifier":
        y_train = _top_decile_labels(train_df, target_label_col)
        y_val = _top_decile_labels(val_df, target_label_col)
        if y_train.nunique() < 2 or y_val.nunique() < 2:
            return None, {"status": "single_class_label"}
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
        model.fit(
            train_df[FEATURE_COLS],
            y_train,
            eval_set=[(val_df[FEATURE_COLS], y_val)],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=0)],
        )
        return model.predict_proba(val_df[FEATURE_COLS])[:, 1], {"status": "ok", "best_iteration": model.best_iteration_}

    if objective == "ranker_lambdarank":
        train_rank = train_df.copy()
        val_rank = val_df.copy()
        train_rank["label"] = train_rank[target_label_col]
        val_rank["label"] = val_rank[target_label_col]
        y_train = make_rank_labels(train_rank)
        y_val = make_rank_labels(val_rank)
        max_label = int(max(y_train.max(), y_val.max())) if len(y_train) and len(y_val) else 0
        model = lgb.LGBMRanker(
            objective="lambdarank",
            n_estimators=n_estimators,
            learning_rate=0.05,
            label_gain=list(range(max_label + 1)),
            num_leaves=63,
            min_child_samples=50,
            subsample=0.8,
            colsample_bytree=0.7,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(
            train_rank[FEATURE_COLS],
            y_train,
            group=daily_rank_groups(train_rank),
            eval_set=[(val_rank[FEATURE_COLS], y_val)],
            eval_group=[daily_rank_groups(val_rank)],
            callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=0)],
        )
        return model.predict(val_rank[FEATURE_COLS]), {"status": "ok", "best_iteration": model.best_iteration_}

    return None, {"status": f"unknown_objective:{objective}"}


def candidate_specs(horizon: int) -> list[dict[str, str]]:
    raw = f"label_{horizon}d"
    industry = f"label_{horizon}d_industry_neutral"
    size = f"label_{horizon}d_size_neutral"
    industry_size = f"label_{horizon}d_industry_size_neutral"
    return [
        {"name": "raw_5d_regression_control", "objective": "regression", "horizon": "5", "target_label": "label_5d"},
        {"name": f"raw_{horizon}d_regression", "objective": "regression", "horizon": str(horizon), "target_label": raw},
        {
            "name": f"industry_neutral_{horizon}d_regression",
            "objective": "regression",
            "horizon": str(horizon),
            "target_label": industry,
        },
        {
            "name": f"size_neutral_{horizon}d_regression",
            "objective": "regression",
            "horizon": str(horizon),
            "target_label": size,
        },
        {
            "name": f"industry_size_neutral_{horizon}d_regression",
            "objective": "regression",
            "horizon": str(horizon),
            "target_label": industry_size,
        },
        {
            "name": f"raw_{horizon}d_top_decile_classifier",
            "objective": "top_decile_classifier",
            "horizon": str(horizon),
            "target_label": raw,
        },
        {
            "name": f"industry_size_neutral_{horizon}d_top_decile_classifier",
            "objective": "top_decile_classifier",
            "horizon": str(horizon),
            "target_label": industry_size,
        },
        {
            "name": f"raw_{horizon}d_ranker_lambdarank",
            "objective": "ranker_lambdarank",
            "horizon": str(horizon),
            "target_label": raw,
        },
        {
            "name": f"industry_size_neutral_{horizon}d_ranker_lambdarank",
            "objective": "ranker_lambdarank",
            "horizon": str(horizon),
            "target_label": industry_size,
        },
    ]


def evaluate_candidate(panel: pd.DataFrame, spec: dict[str, str], *, n_estimators: int) -> dict[str, Any]:
    target_label = spec["target_label"]
    raw_label = f"label_{spec['horizon']}d"
    segment_cols = [col for col in ("industry", "sector") if col in panel.columns]
    cols = list(dict.fromkeys(["date", "symbol", *segment_cols, target_label, raw_label, *FEATURE_COLS]))
    data = panel[cols].replace([np.inf, -np.inf], np.nan).dropna(subset=[target_label, raw_label, *FEATURE_COLS])
    train_df, val_df = _time_split(data)
    if len(train_df) < 200 or len(val_df) < 50:
        return {
            **spec,
            "status": "insufficient_data",
            "sample": {"n_rows": len(data), "train_rows": len(train_df), "validation_rows": len(val_df)},
        }

    pred, fit_info = _fit_predict(
        train_df,
        val_df,
        objective=spec["objective"],
        target_label_col=target_label,
        n_estimators=n_estimators,
    )
    if pred is None:
        return {
            **spec,
            "status": fit_info.get("status", "fit_failed"),
            "sample": {"n_rows": len(data), "train_rows": len(train_df), "validation_rows": len(val_df)},
        }

    sample = {
        "n_rows": int(len(data)),
        "train_rows": int(len(train_df)),
        "validation_rows": int(len(val_df)),
        "n_symbols": int(data["symbol"].nunique()),
        "validation_start": str(pd.to_datetime(val_df["date"]).min().date()),
        "validation_end": str(pd.to_datetime(val_df["date"]).max().date()),
    }
    target_predictions = _validation_frame(val_df, pred, target_label, segment_cols=segment_cols)
    raw_predictions = _validation_frame(val_df, pred, raw_label, segment_cols=segment_cols)
    horizon = int(spec["horizon"])
    target_report = build_validation_report(
        target_predictions,
        label=f"{spec['name']}:target",
        sample=sample,
    )
    raw_report = build_validation_report(
        raw_predictions,
        label=f"{spec['name']}:raw_return",
        sample=sample,
    )
    stride_sample = {**sample, "stride": horizon}
    raw_stride = build_validation_report(
        stride_predictions(raw_predictions, stride=horizon),
        label=f"{spec['name']}:raw_return_stride_{horizon}",
        sample=stride_sample,
    )
    return {
        **spec,
        "status": "ok",
        "fit": fit_info,
        "sample": sample,
        "target_validation": target_report,
        "raw_return_validation": raw_report,
        "raw_return_stride_validation": raw_stride,
        "top_decile_metrics": top_decile_metrics(raw_predictions, top_pct=TOP_DECILE_PCT),
        "segment_breakdown": {
            col: segment_breakdown(raw_predictions, segment_col=col)
            for col in segment_cols
        },
    }


def _gate_pass(report: dict[str, Any]) -> bool:
    return bool((report.get("gates") or {}).get("pass"))


def build_decision(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [c for c in candidates if c.get("status") == "ok"]
    if not ok:
        return {"decision": "no_valid_candidate", "recommended_next_action": "inspect_fit_failures"}
    raw_pass = [c for c in ok if _gate_pass(c.get("raw_return_validation") or {})]
    target_pass = [c for c in ok if _gate_pass(c.get("target_validation") or {})]
    best_raw = max(
        ok,
        key=lambda c: float(((c.get("raw_return_validation") or {}).get("metrics") or {}).get("icir") or 0.0),
    )
    if raw_pass:
        return {
            "decision": "candidate_ready_for_full_retrain_validation",
            "recommended_next_action": "wire_best_candidate_into_non_promoting_train_candidate",
            "best_raw_candidate": raw_pass[0]["name"],
            "target_gate_pass_count": len(target_pass),
            "raw_gate_pass_count": len(raw_pass),
        }
    best_raw_metrics = (best_raw.get("raw_return_validation") or {}).get("metrics") or {}
    best_raw_gates = (best_raw.get("raw_return_validation") or {}).get("gates") or {}
    best_top = best_raw.get("top_decile_metrics") or {}
    if (
        bool(best_raw_gates.get("pass_ic"))
        and bool(best_raw_gates.get("pass_icir"))
        and float(best_top.get("lift_vs_base_rate") or 0.0) >= 2.0
    ):
        next_action = "evaluate_top_decile_classifier_as_discrete_entry_filter"
    else:
        next_action = "try_event_conditioned_or_sector_specific_objective"
    return {
        "decision": "keep_quant_disabled",
        "recommended_next_action": next_action,
        "best_raw_candidate": best_raw["name"],
        "best_raw_ic": best_raw_metrics.get("ic_mean"),
        "best_raw_icir": best_raw_metrics.get("icir"),
        "best_raw_stride_ic": ((best_raw.get("raw_return_stride_validation") or {}).get("metrics") or {}).get("ic_mean"),
        "best_raw_stride_icir": ((best_raw.get("raw_return_stride_validation") or {}).get("metrics") or {}).get("icir"),
        "best_raw_top_decile_precision": best_top.get("precision"),
        "best_raw_top_decile_lift": best_top.get("lift_vs_base_rate"),
        "target_gate_pass_count": len(target_pass),
        "raw_gate_pass_count": 0,
    }


def build_report(
    panel: pd.DataFrame,
    *,
    panel_meta: dict[str, Any],
    horizon: int = DEFAULT_HORIZON,
    n_estimators: int = 180,
    segment_min_rows: int = DEFAULT_SEGMENT_MIN_ROWS,
    segment_min_symbols: int = DEFAULT_SEGMENT_MIN_SYMBOLS,
    segment_min_validation_rows: int = DEFAULT_SEGMENT_MIN_VALIDATION_ROWS,
) -> dict[str, Any]:
    panel = add_objective_labels(panel, 5 if horizon != 5 else horizon)
    if horizon != 5:
        panel = add_objective_labels(panel, horizon)
    candidates = [evaluate_candidate(panel, spec, n_estimators=n_estimators) for spec in candidate_specs(horizon)]
    segment_candidates = evaluate_segment_specific_candidates(
        panel,
        horizon=horizon,
        n_estimators=n_estimators,
        min_rows=segment_min_rows,
        min_symbols=segment_min_symbols,
        min_validation_rows=segment_min_validation_rows,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "purpose": "M27.1b label/objective candidate evaluation; no model promotion",
        "gate": {
            "ic_floor": settings.qlib_train_ic_floor,
            "icir_floor": settings.qlib_train_icir_floor,
            "require_monotonic": settings.qlib_train_require_monotonic,
        },
        "panel": panel_meta,
        "horizon": horizon,
        "n_estimators": n_estimators,
        "candidates": candidates,
        "sector_industry_specific_candidates": segment_candidates,
        "decision": build_decision(candidates),
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    panel = report["panel"]
    decision = report["decision"]
    lines = [
        "# M27.1b Label/Objective Evaluation",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- panel: {panel.get('n_rows')} rows / {panel.get('n_symbols')} symbols / cache_hit={panel.get('cache_hit')}",
        f"- window: {panel.get('start')} ~ {panel.get('end')}",
        f"- horizon: {report['horizon']}d",
        f"- decision: {decision.get('decision')}",
        f"- recommended_next_action: {decision.get('recommended_next_action')}",
        "",
        "## Candidates",
        "",
        "| candidate | objective | target IC | target ICIR | raw IC | raw ICIR | stride ICIR | top precision | lift | raw mono | raw gate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for candidate in report["candidates"]:
        target_metrics = ((candidate.get("target_validation") or {}).get("metrics") or {})
        raw_metrics = ((candidate.get("raw_return_validation") or {}).get("metrics") or {})
        raw_gates = ((candidate.get("raw_return_validation") or {}).get("gates") or {})
        stride_metrics = ((candidate.get("raw_return_stride_validation") or {}).get("metrics") or {})
        decile = candidate.get("top_decile_metrics") or {}
        lines.append(
            f"| {candidate.get('name')} | {candidate.get('objective')} | "
            f"{target_metrics.get('ic_mean')} | {target_metrics.get('icir')} | "
            f"{raw_metrics.get('ic_mean')} | {raw_metrics.get('icir')} | "
            f"{stride_metrics.get('icir')} | {decile.get('precision')} | {decile.get('lift_vs_base_rate')} | "
            f"{raw_gates.get('pass_monotonic')} | {raw_gates.get('pass')} |"
        )
    lines.append("")
    segment_candidates = report.get("sector_industry_specific_candidates") or {}
    if segment_candidates:
        lines.extend([
            "## Sector/Industry-Specific Offline Candidates",
            "",
            f"- non_promoting: {segment_candidates.get('non_promoting')}",
            f"- promotable: {segment_candidates.get('promotable')}",
            f"- run_mode: {segment_candidates.get('run_mode')}",
            f"- sample_limited: {segment_candidates.get('sample_limited')}",
            f"- promotion_blocker: {segment_candidates.get('promotion_blocker')}",
            f"- note: {segment_candidates.get('note')}",
            f"- minimum sample: {segment_candidates.get('min_rows')} rows / "
            f"{segment_candidates.get('min_symbols')} symbols / "
            f"{segment_candidates.get('min_validation_rows')} validation rows",
            "",
            "| segment_col | segment | rows | symbols | val rows | raw IC | raw ICIR | stride ICIR | gate |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for candidate in (segment_candidates.get("candidates") or [])[:12]:
            raw_metrics = ((candidate.get("raw_return_validation") or {}).get("metrics") or {})
            raw_gates = ((candidate.get("raw_return_validation") or {}).get("gates") or {})
            stride_metrics = ((candidate.get("raw_return_stride_validation") or {}).get("metrics") or {})
            sample = candidate.get("sample") or {}
            lines.append(
                f"| {candidate.get('segment_col')} | {candidate.get('segment')} | "
                f"{sample.get('n_rows')} | {sample.get('n_symbols')} | {sample.get('validation_rows')} | "
                f"{raw_metrics.get('ic_mean')} | {raw_metrics.get('icir')} | "
                f"{stride_metrics.get('icir')} | {raw_gates.get('pass')} |"
            )
        if not segment_candidates.get("candidates"):
            lines.append("| n/a | no segment met sample gates |  |  |  |  |  |  |  |")
        lines.append("")
    decision_best = decision.get("best_raw_candidate")
    best_candidate = next(
        (candidate for candidate in report["candidates"] if candidate.get("name") == decision_best),
        None,
    )
    if best_candidate and (best_candidate.get("segment_breakdown") or {}):
        lines.extend(["## Best Raw Candidate Segment Breakdown", ""])
        for col, rows in (best_candidate.get("segment_breakdown") or {}).items():
            if not rows:
                continue
            lines.extend([
                f"### {col}",
                "",
                "| segment | rows | symbols | dates | raw IC | raw ICIR | IC>0 | top-bottom | gate |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ])
            for row in rows[:8]:
                lines.append(
                    f"| {row.get('segment')} | {row.get('n_rows')} | {row.get('n_symbols')} | "
                    f"{row.get('n_dates')} | {row.get('ic_mean')} | {row.get('icir')} | "
                    f"{row.get('ic_positive_rate')} | {row.get('top_bottom')} | {row.get('gate_pass')} |"
                )
            lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--n-estimators", type=int, default=180)
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--segment-min-rows", type=int, default=DEFAULT_SEGMENT_MIN_ROWS)
    parser.add_argument("--segment-min-symbols", type=int, default=DEFAULT_SEGMENT_MIN_SYMBOLS)
    parser.add_argument("--segment-min-validation-rows", type=int, default=DEFAULT_SEGMENT_MIN_VALIDATION_ROWS)
    parser.add_argument("--active-only", action="store_true", default=True)
    parser.add_argument("--include-inactive", action="store_true", help="Use full expanded universe instead of active-only")
    parser.add_argument("--refresh-panel-cache", action="store_true")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> None:
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
        segment_min_rows=args.segment_min_rows,
        segment_min_symbols=args.segment_min_symbols,
        segment_min_validation_rows=args.segment_min_validation_rows,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    print(f"JSON report: {args.json_output}")
    print(f"Markdown report: {args.markdown_output}")
    print(f"Decision: {report['decision']['decision']}")


if __name__ == "__main__":
    main()
