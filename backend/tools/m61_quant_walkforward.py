"""M61 §7.5 enriched-feature LightGBM walk-forward plumbing check.

This is a new hypothesis in a new feature space. It must not be read as
overturning the old price-only LGBM 关门 verdict; that verdict remains valid for
the old feature set.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import default_sqlite_path
from backend.data.database import Price
from backend.tools.m29_hypothesis_registry import (
    DEFAULT_JSON_OUTPUT,
    DEFAULT_MARKDOWN_OUTPUT,
    _base_hypothesis,
    build_registry,
    report_to_markdown,
    validate_registry,
)
from backend.tools.m58_grid_backtest import attach_forward_returns, regime_from_pool_equal_weight
from backend.tools.m58_lgbm_walkforward import (
    GATE_IC_FLOOR,
    GATE_ICIR_FLOOR,
    GATE_REGIME_BUCKETS,
    LABEL_LOOKAHEAD_DAYS,
    MIN_TRAIN_ROWS,
    RETRAIN_EVERY_DAYS,
    TRAIN_WINDOW_DAYS,
    WalkForwardBlock,
    build_walkforward_schedule,
)
from backend.tools.m61_quant_features import M61_FEATURE_COLS, build_feature_matrix_v2

HYPOTHESIS_ID = "m61_quant_v2_enriched_features"
HYPOTHESIS_STATEMENT = "富特征(事件/龙虎榜/研报修正/财务/资金流)下 LGBM 5日横截面 IC>=0.04 且 ICIR>=0.40"
OLD_VERDICT = {"feature_set": "old_price_alpha_space", "ic": 0.022, "icir": 0.188, "verdict": "关门仍有效"}


def _load_universe(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    stocks = payload.get("stocks") if isinstance(payload, dict) else payload
    if not isinstance(stocks, list):
        raise ValueError("universe must be a list or an object with stocks")
    symbols: list[str] = []
    for item in stocks:
        symbol = item.get("symbol") if isinstance(item, dict) else item
        if symbol:
            symbols.append(str(symbol))
    if not symbols:
        raise ValueError("universe contains no symbols")
    return symbols


def _make_hypothesis() -> dict[str, Any]:
    return _base_hypothesis(
        hypothesis_id=HYPOTHESIS_ID,
        motivation=HYPOTHESIS_STATEMENT,
        source_m27_clues=["M61_DATA_FOUNDATION_PLAN §7.5", "M58 price-only LGBM old feature-space verdict"],
        candidate_family="m61_quant_v2_enriched_lgbm",
        features=M61_FEATURE_COLS,
        sample_scope={
            "universe": "paper_trading/biaodi1_universe.json_or_cli_universe",
            "min_symbols": 4,
            "min_validation_rows": 50,
            "min_filtered_trades": 50,
            "known_limitations": ["fund_flow block may be sparse until M61 drip data lands"],
        },
        horizons=[5],
        split_override={
            "walkforward_train_window_days": TRAIN_WINDOW_DAYS,
            "walkforward_retrain_every_days": RETRAIN_EVERY_DAYS,
            "label_lookahead_days": LABEL_LOOKAHEAD_DAYS,
            "requires_fresh_oos_forward": True,
        },
        stop_conditions=[
            "stop if the old price-only LGBM verdict is described as overturned rather than scoped to the old feature space",
            "stop if fund_flow missing values are filled with zero",
            "stop if any enriched feature uses rows not knowable at the evaluation date",
            "stop if IC < 0.04 or ICIR < 0.40",
        ],
        forbidden_interpretation_suffix=(
            "new enriched-feature hypothesis only; old LGBM 关门 verdict remains valid in the old feature space"
        ),
        extra_fields={
            "statement": HYPOTHESIS_STATEMENT,
            "allowed_next_action": "run read-only in-memory walk-forward validation and write JSON artifact",
            "forbidden_actions": [
                "write_db",
                "call_llm_or_api",
                "change_weight_quant",
                "change_signal_profile",
                "attach_checkpoint",
                "save_model",
                "write_sentiment_cache",
            ],
            "trial_count_ledger": {
                "declared_at_registration": 1,
                "note": "single M61 v2 enriched-feature LGBM trial before any result is computed",
            },
        },
    )


def ensure_hypothesis_registered(
    *,
    registry_path: Path = DEFAULT_JSON_OUTPUT,
    markdown_path: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    """Append the M61 hypothesis before computing any result and validate it."""
    registry_path = registry_path.expanduser()
    markdown_path = markdown_path.expanduser()
    if registry_path.exists():
        report = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        report = build_registry(as_of_date=datetime.now(UTC).date().isoformat())

    hypotheses = report.setdefault("hypotheses", [])
    existing = [item for item in hypotheses if item.get("hypothesis_id") == HYPOTHESIS_ID]
    if not existing:
        hypotheses.append(_make_hypothesis())

    report["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    errors = validate_registry(report, strict=True)
    report["validation"] = {"passed": not errors, "errors": errors}
    if errors:
        raise RuntimeError("M29 hypothesis registry validation failed: " + "; ".join(errors))

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(report_to_markdown(report), encoding="utf-8")
    return {
        "path": str(registry_path),
        "hypothesis_id": HYPOTHESIS_ID,
        "status": "already_registered" if existing else "registered",
        "registered_at": report["generated_at"],
    }


def _load_price_panel(symbols: list[str], end: str, db) -> pd.DataFrame:
    rows = (
        db.query(Price)
        .filter(Price.symbol.in_(symbols), Price.date <= end)
        .order_by(Price.symbol, Price.date)
        .all()
    )
    panel = pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "date": row.date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in rows
        ]
    )
    if panel.empty:
        return panel
    for col in ("open", "high", "low", "close", "volume"):
        panel[col] = pd.to_numeric(panel[col], errors="coerce")
    return panel


def _build_training_panel(symbols: list[str], start: str, end: str, horizon: int, db) -> pd.DataFrame:
    if horizon != 5:
        raise NotImplementedError("M61 §7.5 currently mirrors the 5-day M58 label only")
    features = build_feature_matrix_v2(symbols, "1900-01-01", end, db).reset_index()
    prices = _load_price_panel(symbols, end, db)
    if prices.empty or features.empty:
        return pd.DataFrame()
    labels = attach_forward_returns(prices)[["date", "symbol", "close", "forward_5d_net_return"]]
    panel = features.merge(labels, on=["symbol", "date"], how="left")
    return panel.sort_values(["date", "symbol"]).reset_index(drop=True)


def _daily_ic(rows: pd.DataFrame) -> float:
    if len(rows) < 3:
        return 0.0
    corr = rows["score"].corr(rows["forward_5d_net_return"], method="spearman")
    return 0.0 if pd.isna(corr) else float(corr)


def _ic_series(scored: pd.DataFrame) -> pd.Series:
    if scored.empty:
        return pd.Series(dtype=float)
    return scored.groupby("date").apply(_daily_ic, include_groups=False)


def _three_bucket(scored: pd.DataFrame) -> dict[str, Any]:
    if scored.empty:
        return {}
    rows = scored.dropna(subset=["score", "forward_5d_net_return", "pool_return"]).copy()
    rows["rank_pct"] = rows.groupby("date")["score"].rank(method="average", pct=True)
    picked = rows[rows["rank_pct"] >= 0.8].copy()
    picked["edge"] = picked["forward_5d_net_return"] - picked["pool_return"]
    out: dict[str, Any] = {}
    for name, grp in picked.groupby("regime"):
        out[str(name)] = {
            "observations": int(len(grp)),
            "mean_excess": round(float(grp["edge"].mean()) if len(grp) else 0.0, 6),
        }
    return out


def _train_and_score(panel: pd.DataFrame, blocks: list[WalkForwardBlock]) -> tuple[pd.DataFrame, list[dict[str, Any]], Counter[str]]:
    try:
        import lightgbm as lgb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("lightgbm is required for m61_quant_walkforward") from exc

    scored_parts: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    importances: Counter[str] = Counter()

    for block in blocks:
        train_rows = panel[panel["date"].isin(block.train_dates)].dropna(subset=["forward_5d_net_return"]).copy()
        if len(train_rows) < MIN_TRAIN_ROWS:
            diagnostics.append({"cutoff": block.cutoff_date, "status": "skipped_insufficient_rows", "train_rows": int(len(train_rows))})
            continue
        serve_rows = panel[panel["date"].isin(block.serve_dates)].copy()
        if serve_rows.empty:
            diagnostics.append({"cutoff": block.cutoff_date, "status": "no_serve_rows", "train_rows": int(len(train_rows))})
            continue

        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbosity=-1,
        )
        model.fit(train_rows[M61_FEATURE_COLS], train_rows["forward_5d_net_return"])
        serve_rows["score"] = model.predict(serve_rows[M61_FEATURE_COLS])
        scored_parts.append(serve_rows[["date", "symbol", "close", "score", "forward_5d_net_return"]])
        importances.update({col: int(value) for col, value in zip(M61_FEATURE_COLS, model.feature_importances_, strict=True)})
        diagnostics.append(
            {
                "cutoff": block.cutoff_date,
                "status": "trained",
                "train_rows": int(len(train_rows)),
                "train_dates_span": [block.train_dates[0], block.train_dates[-1]] if block.train_dates else None,
                "serve_dates_span": [block.serve_dates[0], block.serve_dates[-1]] if block.serve_dates else None,
            }
        )
        del model
    scored = pd.concat(scored_parts, ignore_index=True) if scored_parts else pd.DataFrame()
    return scored, diagnostics, importances


def build_report(*, universe: Path, start: str, end: str, horizon: int, db_path: Path) -> dict[str, Any]:
    registration = ensure_hypothesis_registered()
    symbols = _load_universe(universe)
    engine = create_engine(f"sqlite:///{db_path.expanduser().resolve()}")
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        panel = _build_training_panel(symbols, start, end, horizon, db)
    finally:
        db.close()
        engine.dispose()
    if panel.empty:
        raise RuntimeError("empty M61 v2 panel")

    dates = sorted(panel["date"].dropna().unique().tolist())
    blocks = build_walkforward_schedule(dates)
    scored, diagnostics, importances = _train_and_score(panel, blocks)
    if scored.empty:
        raise RuntimeError("walk-forward produced no scores")

    eval_panel = scored[(scored["date"] >= start) & (scored["date"] <= end)].dropna(
        subset=["score", "forward_5d_net_return"]
    ).copy()
    if eval_panel.empty:
        raise RuntimeError("walk-forward evaluation panel is empty in requested window")
    eval_panel["pool_return"] = eval_panel.groupby("date")["forward_5d_net_return"].transform("mean")
    regimes = regime_from_pool_equal_weight(eval_panel[["date", "symbol", "close"]])
    eval_panel = eval_panel.merge(regimes, on="date", how="left")

    ic_by_date = _ic_series(eval_panel)
    ic_values = [float(value) for value in ic_by_date if pd.notna(value)]
    ic_mean = mean(ic_values) if ic_values else 0.0
    ic_std = pstdev(ic_values) if len(ic_values) > 1 else 0.0
    icir = ic_mean / ic_std if ic_std > 0 else 0.0
    regime = _three_bucket(eval_panel)
    three_bucket_excess = {
        name: float((regime.get(name) or {}).get("mean_excess", 0.0)) for name in GATE_REGIME_BUCKETS
    }
    pass_regime = all(name in regime and value >= 0 for name, value in three_bucket_excess.items())
    per_window = []
    for item in diagnostics:
        if item.get("status") != "trained" or not item.get("serve_dates_span"):
            continue
        lo, hi = item["serve_dates_span"]
        rows = eval_panel[(eval_panel["date"] >= lo) & (eval_panel["date"] <= hi)]
        values = [float(value) for value in _ic_series(rows) if pd.notna(value)]
        per_window.append(
            {
                "cutoff": item["cutoff"],
                "serve_dates_span": item["serve_dates_span"],
                "ic": round(mean(values), 6) if values else None,
                "ic_days": len(values),
            }
        )

    top_features = [
        {"feature": name, "importance": int(value)}
        for name, value in importances.most_common(15)
    ]
    gates = {
        "ic_floor": GATE_IC_FLOOR,
        "icir_floor": GATE_ICIR_FLOOR,
        "pass_ic": ic_mean >= GATE_IC_FLOOR,
        "pass_icir": icir >= GATE_ICIR_FLOOR,
        "pass_three_bucket": pass_regime,
        "passed": bool(ic_mean >= GATE_IC_FLOOR and icir >= GATE_ICIR_FLOOR and pass_regime),
    }
    return {
        "meta": {
            "feature_set": "m61_v2",
            "hypothesis_id": HYPOTHESIS_ID,
            "hypothesis_status": "preregistered",
            "status": "preliminary_plumbing_check",
            "warning": "plumbing check only; fund_flow block may be empty and financials are thin before May; not a verdict",
            "old_verdict_comparison": OLD_VERDICT,
            "start": start,
            "end": end,
            "horizon": horizon,
            "universe": str(universe),
            "n_symbols": len(symbols),
            "n_features": len(M61_FEATURE_COLS),
            "feature_cols": M61_FEATURE_COLS,
            "train_window_days": TRAIN_WINDOW_DAYS,
            "retrain_every_days": RETRAIN_EVERY_DAYS,
            "label_lookahead_days": LABEL_LOOKAHEAD_DAYS,
            "m29_registration": registration,
        },
        "metrics": {
            "ic": round(float(ic_mean), 6),
            "ic_std": round(float(ic_std), 6),
            "icir": round(float(icir), 6),
            "ic_days": len(ic_values),
            "evaluated_rows": int(len(eval_panel)),
            "evaluated_dates": int(eval_panel["date"].nunique()),
            "evaluated_symbols": int(eval_panel["symbol"].nunique()),
        },
        "gates": gates,
        "per_window_ic": per_window,
        "three_bucket": regime,
        "feature_importances_top15": top_features,
        "walkforward_diagnostics": diagnostics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=Path("paper_trading/biaodi1_universe.json"))
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("paper_trading/m61_out/quant_v2_walkforward.json"))
    parser.add_argument("--db-path", type=Path, default=default_sqlite_path())
    args = parser.parse_args(argv)

    report = build_report(
        universe=args.universe,
        start=args.start,
        end=args.end,
        horizon=args.horizon,
        db_path=args.db_path,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "feature_set": report["meta"]["feature_set"],
        "hypothesis_id": report["meta"]["hypothesis_id"],
        "status": report["meta"]["status"],
        "ic": report["metrics"]["ic"],
        "icir": report["metrics"]["icir"],
        "gates": report["gates"],
    }, ensure_ascii=False, indent=2, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
