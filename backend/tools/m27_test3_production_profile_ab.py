"""M27.1c offline test3 production-profile entry-filter A/B.

This diagnostic applies the M27.1b top-decile classifier as an entry
eligibility filter on top of the current production ``new_framework`` profile.
It is deliberately read-only: no signal rows, model artifacts, DB writes, or
LLM/API calls are produced.
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.backtest.backfill_signals import backfill_window
from backend.backtest.compare_paths import SignalInput
from backend.backtest.costs import annualized_sharpe, net_return
from backend.config import active_signal_weights
from backend.data.database import SessionLocal
from backend.decision.aggregator import aggregate
from backend.tools.m27_alpha_diagnostic import _load_universe_symbols
from backend.tools.m27_label_objective_eval import (
    DEFAULT_HORIZON,
    TOP_DECILE_PCT,
    load_or_build_panel,
)
from backend.tools.m27_top_decile_filter_ab import (
    _top_decile_predictions,
    filter_top_decile_candidates,
)

DEFAULT_UNIVERSE_PATH = Path("paper_trading/test3_universe.json")
DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m27_test3_production_profile_ab_report.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m27_test3_production_profile_ab_report.md"
DEFAULT_START = "2025-11-01"
DEFAULT_END = "2026-05-14"


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    if not np.isfinite(value):
        return None
    return round(float(value), 6)


def _key(date: str, symbol: str) -> tuple[str, str]:
    return date[:10], symbol


def _allowed_filter_keys(
    panel: pd.DataFrame,
    *,
    horizon: int,
    n_estimators: int,
    top_pct: float,
    universe_symbols: set[str],
) -> tuple[set[tuple[str, str]], dict[str, Any]]:
    scoped_panel = panel[panel["symbol"].isin(universe_symbols)].copy()
    predictions, info = _top_decile_predictions(scoped_panel, horizon=horizon, n_estimators=n_estimators)
    if predictions is None:
        return set(), {"status": "classifier_unavailable", "classifier": info}
    filtered = filter_top_decile_candidates(predictions, top_pct=top_pct)
    allowed = {
        _key(str(row.date), str(row.symbol))
        for row in filtered.itertuples(index=False)
    }
    return allowed, {
        "status": "ok",
        "classifier": info,
        "validation_rows": int(len(predictions)),
        "allowed_filter_keys": int(len(allowed)),
        "validation_start": str(pd.to_datetime(predictions["date"]).min().date()),
        "validation_end": str(pd.to_datetime(predictions["date"]).max().date()),
    }


def _score_input(inp: SignalInput) -> dict[str, Any]:
    sentiment = float(inp.sentiment_result.get("sentiment") or 0.0)
    return aggregate(
        quant_score=float(inp.qlib_result.get("score") or 0.0),
        technical_result=inp.technical_result,
        sentiment_score=sentiment,
        sentiment_result=inp.sentiment_result,
        close=inp.close,
        atr=inp.atr,
    )


def _trade_metrics(rows: list[dict[str, Any]], *, exit_days: int) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in rows]
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
            "avg_composite_score": None,
        }
    wins = [ret for ret in returns if ret > 0]
    total = 1.0
    for ret in returns:
        total *= 1 + ret
    return {
        "trades": len(returns),
        "wins": len(wins),
        "losses": len(returns) - len(wins),
        "win_rate": _round(len(wins) / len(returns)),
        "avg_net_return": _round(statistics.mean(returns)),
        "median_net_return": _round(statistics.median(returns)),
        "total_compounded_return": _round(total - 1),
        "sharpe": _round(annualized_sharpe(returns, avg_hold_days=exit_days)),
        "avg_composite_score": _round(statistics.mean(float(row["composite_score"]) for row in rows)),
    }


def _delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("trades", "win_rate", "avg_net_return", "median_net_return", "total_compounded_return", "sharpe"):
        lval = left.get(key)
        rval = right.get(key)
        out[key] = _round(float(lval) - float(rval)) if lval is not None and rval is not None else None
    return out


def build_profile_ab(
    inputs: list[SignalInput],
    *,
    allowed_filter_keys: set[tuple[str, str]],
    exit_days: int,
    entry_threshold: float,
) -> dict[str, Any]:
    baseline_rows: list[dict[str, Any]] = []
    filtered_rows: list[dict[str, Any]] = []
    scored = 0
    missing_forward_return = 0
    for inp in inputs:
        decision = _score_input(inp)
        scored += 1
        score = float(decision.get("composite_score") or 0.0)
        gross = inp.forward_return_at(exit_days)
        if gross is None:
            missing_forward_return += 1
            continue
        if score <= entry_threshold:
            continue
        row = {
            "date": inp.date[:10],
            "symbol": inp.symbol,
            "composite_score": score,
            "recommendation": decision.get("recommendation"),
            "gross_return": _round(gross),
            "net_return": _round(net_return(gross)),
        }
        baseline_rows.append(row)
        if _key(inp.date, inp.symbol) in allowed_filter_keys:
            filtered_rows.append(row)

    baseline = _trade_metrics(baseline_rows, exit_days=exit_days)
    filtered = _trade_metrics(filtered_rows, exit_days=exit_days)
    return {
        "profile": "new_framework",
        "profile_definition": "quant=0.0, technical=0.6, sentiment=0.4, entry_threshold=25 by current production default",
        "exit_logic": f"fixed_{exit_days}d_close_to_close_with_project_round_trip_cost",
        "entry_threshold": entry_threshold,
        "scored_inputs": scored,
        "missing_forward_return": missing_forward_return,
        "baseline_arm": {
            "definition": "current production profile entries without top-decile eligibility filter",
            "metrics": baseline,
            "sample": baseline_rows[:20],
        },
        "filtered_arm": {
            "definition": "same production profile entries, additionally requiring daily M27.1b top-decile classifier membership",
            "metrics": filtered,
            "sample": filtered_rows[:20],
        },
        "delta_filtered_minus_baseline": _delta(filtered, baseline),
    }


def build_report(
    panel: pd.DataFrame,
    *,
    panel_meta: dict[str, Any],
    inputs: list[SignalInput],
    universe_symbols: set[str],
    horizon: int = DEFAULT_HORIZON,
    n_estimators: int = 120,
    top_pct: float = TOP_DECILE_PCT,
    exit_days: int = 5,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
) -> dict[str, Any]:
    allowed, filter_info = _allowed_filter_keys(
        panel,
        horizon=horizon,
        n_estimators=n_estimators,
        top_pct=top_pct,
        universe_symbols=universe_symbols,
    )
    weights = active_signal_weights()
    profile_ab = build_profile_ab(
        inputs,
        allowed_filter_keys=allowed,
        exit_days=exit_days,
        entry_threshold=weights.entry_threshold,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.1c",
        "purpose": "read-only test3 production-profile trading-level A/B for top-decile entry filter",
        "run_mode": "offline_read_only_validation",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "model_promotion": "disabled",
        "signal_profile_unchanged": True,
        "universe_symbols": len(universe_symbols),
        "start": start,
        "end": end,
        "horizon": horizon,
        "exit_days": exit_days,
        "top_pct": _round(top_pct),
        "panel": panel_meta,
        "filter": filter_info,
        "profile_ab": profile_ab,
        "decision": {
            "decision": "production_unchanged",
            "recommended_next_action": "use_as_non_promoting_evidence_only_until_M27_gate_and_forward_tests_pass",
        },
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    ab = report["profile_ab"]
    baseline = ab["baseline_arm"]["metrics"]
    filtered = ab["filtered_arm"]["metrics"]
    delta = ab["delta_filtered_minus_baseline"]
    lines = [
        "# M27.1c Test3 Production-Profile A/B",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- run_mode: {report['run_mode']}",
        f"- non_promoting: {report['non_promoting']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- saves_model: {report['saves_model']}",
        f"- universe_symbols: {report['universe_symbols']}",
        f"- window: {report['start']} ~ {report['end']}",
        f"- filter_status: {report['filter']['status']}",
        f"- allowed_filter_keys: {report['filter'].get('allowed_filter_keys')}",
        "",
        "## Profile A/B",
        "",
        f"- profile: {ab['profile']}",
        f"- entry_threshold: {ab['entry_threshold']}",
        f"- exit_logic: {ab['exit_logic']}",
        f"- scored_inputs: {ab['scored_inputs']}",
        "",
        "| arm | trades | win rate | avg net return | median net return | compounded return | sharpe |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| baseline | {baseline['trades']} | {baseline['win_rate']} | {baseline['avg_net_return']} | "
        f"{baseline['median_net_return']} | {baseline['total_compounded_return']} | {baseline['sharpe']} |",
        f"| filtered | {filtered['trades']} | {filtered['win_rate']} | {filtered['avg_net_return']} | "
        f"{filtered['median_net_return']} | {filtered['total_compounded_return']} | {filtered['sharpe']} |",
        f"| delta | {delta['trades']} | {delta['win_rate']} | {delta['avg_net_return']} | "
        f"{delta['median_net_return']} | {delta['total_compounded_return']} | {delta['sharpe']} |",
        "",
        "## Decision",
        "",
        f"- decision: {report['decision']['decision']}",
        f"- recommended_next_action: {report['decision']['recommended_next_action']}",
        "",
    ]
    return "\n".join(lines)


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
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
        horizon=args.horizon,
        n_estimators=args.n_estimators,
        top_pct=args.top_pct,
        exit_days=args.exit_days,
        start=args.start,
        end=args.end,
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
