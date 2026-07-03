"""M58 LGBM walk-forward "closing test" for the price-alpha quant family.

Purpose (owner directive, 2026-07-03): give the LightGBM/price-alpha hypothesis
a formal, rigorous close. Prior is very low going in — M26 promotion gate
failed, M27 candidate did not promote, M43 retrospective REJECTed the
constructed-factor variant, and the model's one production stint measured
ICIR ≈ 0.07. Expected result is another falsification; the point of this tool
is to make that falsification honest and final (walk-forward re-trained, not
a single static split) rather than to search for a configuration that saves
the model.

Method:
- Universe: symbols with >=1000 trading days in ``prices`` (same threshold as
  ``m58_grid_backtest._eligible_symbols``).
- Walk-forward: rolling 250-trading-day training window, retrained every 60
  trading days, using only data whose 5-day forward label is already resolved
  as of the retrain cutoff (no lookahead — see ``build_walkforward_schedule``).
- Features: the price-only subset of ``PRODUCTION_FEATURE_COLS`` (see
  ``PRICE_ONLY_FEATURE_COLS``). ``PRODUCTION_FEATURE_COLS`` as defined in
  ``backend.data.qlib_data`` also includes fundamental/market-cap columns, but
  ``financial_metrics`` only covers 120/731 symbols and ``market_snapshots``
  only 88/731 in this database — training on those columns would silently
  shrink the eligible universe and reintroduce a coverage-gap confound. This
  tool excludes them and evaluates the pure price/technical family only.
- Label (training target): ``forward_5d_net_return`` — the exact same T+1
  entry / T+6 exit, 0.4% cost metric used for evaluation (reusing
  ``m58_grid_backtest.attach_forward_returns``), so the model is trained on
  what it is graded on.
- Evaluation: byte-for-byte reuse of ``m58_grid_backtest``'s IC/ICIR, top20%
  / bottom20% bucket, and regime (up/down/flat) logic, so this walk-forward
  result is directly comparable to the Phase 1 grid report.
- Holdout: the most recent 12 months are excluded via
  ``m58_grid_backtest.resolve_effective_end`` (same lock, same cutoff logic —
  do not touch/unlock it here).

Hard boundaries:
- Read-only against ``mingcang.db``.
- Models are never written to ``~/.mingcang/models`` or ``~/.stock-sage/models``
  (the production serving paths). This tool keeps every trained model in
  memory only, for the lifetime of one walk-forward block, then discards it.
- Single configuration, ``trial_count`` is recorded as 1. This is a closing
  test, not a parameter search — do not add a grid here to try to save the
  hypothesis.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.config import default_sqlite_path
from backend.data.qlib_data import PRODUCTION_FEATURE_COLS, _build_features
from backend.tools.m58_grid_backtest import (
    _connect_readonly,
    _eligible_symbols,
    _evaluate_slot,
    _load_prices,
    attach_forward_returns,
    regime_from_pool_equal_weight,
    resolve_effective_end,
)

OUTPUT_JSON = Path("/private/tmp/m58_lgbm_wf_report.json")
OUTPUT_MD = Path("/private/tmp/m58_lgbm_wf_report.md")

# Requested eval window start per spec. The walk-forward's actual first served
# date is later than this (see module docstring / build_walkforward_schedule):
# a 250-trading-day training window needs that much history to already exist,
# and prices only start 2021-01-04. The filter is still applied for parity
# with m58_grid_backtest's own eval-window semantics; it is a no-op here
# because the walk-forward schedule already starts after this date.
EVAL_START = "2021-05-21"

MIN_TRADING_DAYS = 1000
TRAIN_WINDOW_DAYS = 250
RETRAIN_EVERY_DAYS = 60
# forward_5d_net_return = close.shift(-1) (T+1 entry) .. close.shift(-6) (T+6
# exit): a training row dated d only has a label knowable as of cutoff C when
# d + LABEL_LOOKAHEAD <= C (in trading-day index terms).
LABEL_LOOKAHEAD_DAYS = 6

# PRODUCTION_FEATURE_COLS also carries fundamental (roe/revenue_yoy/...) and
# market-cap/margin columns. Those need backend.data.database.FinancialMetric
# / MarketSnapshot coverage that is sparse in this DB (120/731 and 88/731
# symbols respectively) — training on them would silently narrow the universe
# and confound the price-alpha question with a coverage-gap question. Exclude
# them; this closing test is scoped to the pure price/technical family.
NON_PRICE_PRODUCTION_COLS = {
    "roe",
    "revenue_yoy",
    "net_profit_yoy",
    "gross_margin",
    "asset_turnover",
    "log_market_cap",
    "margin_balance",
}
PRICE_ONLY_FEATURE_COLS = [c for c in PRODUCTION_FEATURE_COLS if c not in NON_PRICE_PRODUCTION_COLS]

# 关门判定门槛 (owner spec): IC >= 0.04 且 ICIR >= 0.40 且三桶 regime 超额不为负。
GATE_IC_FLOOR = 0.04
GATE_ICIR_FLOOR = 0.40
# "三桶" = regime_from_pool_equal_weight's three real regimes. "unknown" is a
# warm-up residual (dates too early for the 20/60-day moving averages to both
# exist) rather than a market regime, so it is reported but excluded from the
# three-bucket gate check.
GATE_REGIME_BUCKETS = ("up", "down", "flat")

MIN_TRAIN_ROWS = 200


@dataclass(frozen=True)
class WalkForwardBlock:
    cutoff_idx: int
    cutoff_date: str
    train_dates: list[str]
    serve_dates: list[str]


def build_walkforward_schedule(
    dates: list[str],
    *,
    train_window: int = TRAIN_WINDOW_DAYS,
    retrain_every: int = RETRAIN_EVERY_DAYS,
    label_lookahead: int = LABEL_LOOKAHEAD_DAYS,
) -> list[WalkForwardBlock]:
    """Slice a sorted trading-date calendar into non-overlapping walk-forward blocks.

    A block's ``cutoff_idx`` stands in for "today": training only uses dates
    whose forward-return label is already fully resolved on or before the
    cutoff (``date_idx + label_lookahead <= cutoff_idx``), and serving starts
    strictly after the cutoff. This guarantees:

    - no block ever trains on a label that requires price data from after its
      own cutoff (no lookahead within a block);
    - consecutive blocks' serve windows are contiguous and non-overlapping
      (every date is scored by exactly one block's model).
    """
    n = len(dates)
    if n == 0:
        return []
    blocks: list[WalkForwardBlock] = []
    first_cutoff = train_window + label_lookahead - 1
    cutoff = first_cutoff
    while cutoff < n - 1:
        train_end = cutoff - label_lookahead  # inclusive: last label-safe date index
        train_start = max(0, train_end - train_window + 1)
        serve_start = cutoff + 1
        serve_end = min(n - 1, cutoff + retrain_every)
        blocks.append(
            WalkForwardBlock(
                cutoff_idx=cutoff,
                cutoff_date=dates[cutoff],
                train_dates=dates[train_start : train_end + 1] if train_end >= train_start else [],
                serve_dates=dates[serve_start : serve_end + 1],
            )
        )
        cutoff += retrain_every
    return blocks


def build_feature_panel(raw_prices: pd.DataFrame) -> pd.DataFrame:
    """Compute the price-only PRODUCTION_FEATURE_COLS subset per symbol.

    Reuses ``backend.data.qlib_data._build_features`` verbatim (the production
    feature formulas) instead of reimplementing them, per spec. Fundamental
    and market columns are auto-filled to 0.0 inside ``_build_features`` when
    absent from the input frame; those columns are simply not selected into
    the output here, so this stays a pure price/technical feature panel.
    """
    parts: list[pd.DataFrame] = []
    for symbol, grp in raw_prices.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        local = grp.copy().reset_index(drop=True)
        feats = _build_features(local)
        feats["symbol"] = symbol
        parts.append(feats[["date", "symbol", "close", *PRICE_ONLY_FEATURE_COLS]])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_training_panel(raw_prices: pd.DataFrame) -> pd.DataFrame:
    feature_panel = build_feature_panel(raw_prices)
    with_forward = attach_forward_returns(raw_prices)[["date", "symbol", "forward_5d_net_return"]]
    return feature_panel.merge(with_forward, on=["date", "symbol"], how="left")


def run_walkforward(
    panel: pd.DataFrame, blocks: list[WalkForwardBlock]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Train one LGBM regressor per block (in memory only) and score its serve window."""
    try:
        import lightgbm as lgb
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("lightgbm 未安装，运行：pip3 install lightgbm") from exc

    scored_parts: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []

    for block in blocks:
        train_rows = panel[panel["date"].isin(block.train_dates)].dropna(
            subset=[*PRICE_ONLY_FEATURE_COLS, "forward_5d_net_return"]
        )
        if len(train_rows) < MIN_TRAIN_ROWS:
            diagnostics.append(
                {
                    "cutoff": block.cutoff_date,
                    "status": "skipped_insufficient_rows",
                    "train_rows": int(len(train_rows)),
                }
            )
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
        model.fit(train_rows[PRICE_ONLY_FEATURE_COLS], train_rows["forward_5d_net_return"])

        serve_rows = panel[panel["date"].isin(block.serve_dates)].dropna(subset=PRICE_ONLY_FEATURE_COLS).copy()
        if serve_rows.empty:
            diagnostics.append(
                {
                    "cutoff": block.cutoff_date,
                    "status": "no_serve_rows",
                    "train_rows": int(len(train_rows)),
                }
            )
            del model
            continue

        serve_rows["score"] = model.predict(serve_rows[PRICE_ONLY_FEATURE_COLS])
        scored_parts.append(serve_rows[["date", "symbol", "close", "score"]])
        diagnostics.append(
            {
                "cutoff": block.cutoff_date,
                "status": "trained",
                "train_rows": int(len(train_rows)),
                "train_dates_span": [block.train_dates[0], block.train_dates[-1]] if block.train_dates else None,
                "serve_dates_span": [block.serve_dates[0], block.serve_dates[-1]] if block.serve_dates else None,
            }
        )
        del model  # in-memory only; never persisted to a serving path

    scored = (
        pd.concat(scored_parts, ignore_index=True)
        if scored_parts
        else pd.DataFrame(columns=["date", "symbol", "close", "score"])
    )
    return scored, diagnostics


def build_eval_panel(scored: pd.DataFrame, panel: pd.DataFrame, *, start: str, effective_end: str) -> pd.DataFrame:
    """Attach forward returns/regime and filter to the eval window — same recipe as m58_grid_backtest.build_report."""
    forward = panel[["date", "symbol", "forward_5d_net_return"]]
    merged = scored.merge(forward, on=["date", "symbol"], how="left")
    merged = merged[(merged["date"] >= start) & (merged["date"] <= effective_end)]
    merged = merged.dropna(subset=["score", "forward_5d_net_return"]).copy()
    if merged.empty:
        return merged
    merged["pool_return"] = merged.groupby("date")["forward_5d_net_return"].transform("mean")
    regimes = regime_from_pool_equal_weight(merged[["date", "symbol", "close"]])
    return merged.merge(regimes, on="date", how="left")


def judge_gate(results: dict[str, Any]) -> dict[str, Any]:
    selection = results.get("selection") or {}
    ic = float(selection.get("ic") or 0.0)
    icir = float(selection.get("icir") or 0.0)
    regime = selection.get("regime") or {}
    regime_excess = {name: round(float((info or {}).get("mean_excess") or 0.0), 6) for name, info in regime.items()}
    three_bucket_excess = {name: val for name, val in regime_excess.items() if name in GATE_REGIME_BUCKETS}
    negative_buckets = {name: val for name, val in three_bucket_excess.items() if val < 0}

    pass_ic = ic >= GATE_IC_FLOOR
    pass_icir = icir >= GATE_ICIR_FLOOR
    pass_regime = len(three_bucket_excess) == len(GATE_REGIME_BUCKETS) and not negative_buckets
    passed = pass_ic and pass_icir and pass_regime

    return {
        "ic_floor": GATE_IC_FLOOR,
        "icir_floor": GATE_ICIR_FLOOR,
        "ic": round(ic, 6),
        "icir": round(icir, 6),
        "pass_ic": pass_ic,
        "pass_icir": pass_icir,
        "pass_regime_non_negative": pass_regime,
        "regime_mean_excess": regime_excess,
        "three_bucket_regimes": GATE_REGIME_BUCKETS,
        "three_bucket_excess": three_bucket_excess,
        "negative_buckets": negative_buckets,
        "passed": passed,
        "verdict": "过门" if passed else "不过门",
    }


def build_report(*, db_path: Path, today=None) -> dict[str, Any]:
    effective_end = resolve_effective_end(None, today=today)
    con = _connect_readonly(db_path)
    try:
        symbols = _eligible_symbols(con, min_days=MIN_TRADING_DAYS, limit_symbols=None)
        # start is a documented no-op in _load_prices (only `end` filters SQL);
        # passed for signature parity / clarity that we want full history.
        raw_prices = _load_prices(con, symbols, start="2000-01-01", end=effective_end)
    finally:
        con.close()

    if raw_prices.empty:
        raise RuntimeError("no eligible price rows found for M58 LGBM walk-forward")

    panel = build_training_panel(raw_prices)
    dates = sorted(panel["date"].dropna().unique().tolist())
    blocks = build_walkforward_schedule(dates)
    scored, diagnostics = run_walkforward(panel, blocks)
    eval_panel = build_eval_panel(scored, panel, start=EVAL_START, effective_end=effective_end)

    if eval_panel.empty:
        raise RuntimeError("walk-forward evaluation panel is empty — check schedule/date coverage")

    results = {
        "selection": _evaluate_slot(eval_panel, slot="selection"),
        "risk_avoidance": _evaluate_slot(eval_panel, slot="risk_avoidance"),
    }
    gate = judge_gate(results)
    trained_blocks = sum(1 for d in diagnostics if d.get("status") == "trained")

    return {
        "meta": {
            "spec": "M58 Phase 1 LGBM walk-forward closing test",
            "requested_eval_start": EVAL_START,
            "effective_end": effective_end,
            "holdout_locked": True,
            "feature_cols": PRICE_ONLY_FEATURE_COLS,
            "n_features": len(PRICE_ONLY_FEATURE_COLS),
            "excluded_non_price_production_cols": sorted(NON_PRICE_PRODUCTION_COLS),
            "train_window_days": TRAIN_WINDOW_DAYS,
            "retrain_every_days": RETRAIN_EVERY_DAYS,
            "label_lookahead_days": LABEL_LOOKAHEAD_DAYS,
            "training_label": "forward_5d_net_return (T+1 entry / T+6 exit, 0.4% cost — same metric as eval)",
            "eligible_symbol_count": len(symbols),
            "walkforward_blocks_total": len(blocks),
            "walkforward_blocks_trained": trained_blocks,
            "actual_served_date_range": [str(eval_panel["date"].min()), str(eval_panel["date"].max())],
            "evaluated_symbol_count": int(eval_panel["symbol"].nunique()),
            "evaluated_date_count": int(eval_panel["date"].nunique()),
            "prior": (
                "M26 promotion gate 败 / M27 候选未晋级 / M43 REJECT / 服役期 ICIR≈0.07 —— "
                "先验极低；本测试为价格 alpha 假设的关门测试（walk-forward 重训，非参数扫描）"
            ),
        },
        "trial_count": 1,
        "results": results,
        "gate": gate,
        "walkforward_diagnostics": diagnostics,
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    results = report["results"]
    gate = report["gate"]
    lines = [
        "# M58 LGBM Walk-Forward 关门测试报告",
        "",
        f"- spec: {meta['spec']}",
        f"- eval_start (requested): {meta['requested_eval_start']}",
        f"- effective_end (holdout locked, 排除最近12个月): {meta['effective_end']}",
        f"- feature_cols ({meta['n_features']}, PRODUCTION_FEATURE_COLS 纯价格子集): "
        f"{', '.join(meta['feature_cols'])}",
        f"- 排除的非价格 PRODUCTION_FEATURE_COLS（基本面/市值覆盖不足）: "
        f"{', '.join(meta['excluded_non_price_production_cols'])}",
        f"- train_window_days: {meta['train_window_days']} / retrain_every_days: {meta['retrain_every_days']} "
        f"/ label_lookahead_days: {meta['label_lookahead_days']}",
        f"- training_label: {meta['training_label']}",
        f"- eligible_symbol_count (>=1000 交易日): {meta['eligible_symbol_count']}",
        f"- walk-forward blocks: {meta['walkforward_blocks_trained']}/{meta['walkforward_blocks_total']} trained",
        f"- actual served/evaluated date range: {meta['actual_served_date_range'][0]} ~ {meta['actual_served_date_range'][1]}",
        f"- evaluated_symbol_count: {meta['evaluated_symbol_count']} / evaluated_date_count: {meta['evaluated_date_count']}",
        f"- trial_count: {report['trial_count']}（单一配置，关门测试不扫参）",
        "",
        "## 先验",
        "",
        f"- {meta['prior']}",
        "",
        "## 评估结果（与 m58_grid_backtest 完全同口径：5日净收益 T+1→T+6，0.4% 成本）",
        "",
        "| slot | observations | mean_excess | hit_rate | ic | icir |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for slot, row in results.items():
        lines.append(
            f"| {slot} | {row['observations']} | {row['mean_excess']:.6f} | {row['hit_rate']:.6f} | "
            f"{row['ic']:.6f} | {row['icir']:.6f} |"
        )
    lines += [
        "",
        "### regime 分桶（selection slot：top20% 超额）",
        "",
        "| regime | observations | mean_excess | hit_rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, info in (results["selection"].get("regime") or {}).items():
        lines.append(f"| {name} | {info['observations']} | {info['mean_excess']:.6f} | {info['hit_rate']:.6f} |")
    lines += [
        "",
        "## 关门判定",
        "",
        f"- 门槛: IC >= {gate['ic_floor']} 且 ICIR >= {gate['icir_floor']} 且三桶(regime)超额不为负",
        f"- IC = {gate['ic']} (pass={gate['pass_ic']})",
        f"- ICIR = {gate['icir']} (pass={gate['pass_icir']})",
        f"- 三桶(up/down/flat)超额: {gate['three_bucket_excess']}（负桶: {gate['negative_buckets']}, pass={gate['pass_regime_non_negative']}）",
        f"- 全部 regime 超额（含 unknown 早期预热残余桶，不计入三桶判定）: {gate['regime_mean_excess']}",
        f"- **判定: {gate['verdict']}**",
        "",
        "## walk-forward 训练诊断（每个 retrain block）",
        "",
        "| cutoff | status | train_rows | train_span | serve_span |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for d in report["walkforward_diagnostics"]:
        lines.append(
            f"| {d.get('cutoff')} | {d.get('status')} | {d.get('train_rows', '-')} | "
            f"{d.get('train_dates_span', '-')} | {d.get('serve_dates_span', '-')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=default_sqlite_path())
    parser.add_argument("--json-output", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=OUTPUT_MD)
    args = parser.parse_args(argv)

    report = build_report(db_path=args.db_path)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.markdown_output.write_text(report_to_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "json": str(args.json_output),
                "md": str(args.markdown_output),
                "trial_count": report["trial_count"],
                "gate": report["gate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
