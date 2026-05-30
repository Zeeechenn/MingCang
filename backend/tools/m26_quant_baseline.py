"""M26 quant baseline report.

This tool is local-only by default: it reads the production SQLite database,
evaluates the current LightGBM quant model with the existing validation-report
口径, runs a historical quant-on/quant-off profile comparison, and writes a
human-readable report under ``~/.stock-sage``.
"""
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.backtest.costs import annualized_sharpe, net_return
from backend.config import BASE_DIR, settings
from backend.data.database import Price, SessionLocal

DEFAULT_M26_UNIVERSE_PATH = BASE_DIR / "paper_trading" / "test2_universe.json"
M27_TEST3_UNIVERSE_PATH = BASE_DIR / "paper_trading" / "test3_universe.json"
DEFAULT_UNIVERSE_PATH = DEFAULT_M26_UNIVERSE_PATH
DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m26_quant_baseline_report.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m26_quant_baseline_report.md"
M26_DIAGNOSTIC_IC_FLOOR = 0.02
M26_DIAGNOSTIC_ICIR_FLOOR = 0.15
M26_DIAGNOSTIC_REQUIRE_MONOTONIC = False


@dataclass(frozen=True)
class WeightProfile:
    name: str
    label: str
    quant: float
    technical: float
    sentiment: float
    entry_threshold: float


QUANT_OFF_PROFILE = WeightProfile("quant_off", "B组 quant_off", 0.0, 0.60, 0.40, 25.0)
QUANT_ON_PROFILE = WeightProfile("quant_on", "A组 quant_on", 0.45, 0.40, 0.15, 20.0)
# 单变量对照：只改权重，固定阈值=25，隔离 quant 因子贡献
QUANT_ON_FIXED_THRESHOLD_PROFILE = WeightProfile("quant_on_fixed_threshold", "A组(固定阈值=25)", 0.45, 0.40, 0.15, 25.0)

# 每笔仓位占组合比例（与 test2_ab_runner 保持一致）
POSITION_PCT = 0.15


def load_test2_symbols(path: Path = DEFAULT_UNIVERSE_PATH) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    symbols: list[str] = []
    for row in rows:
        symbol = row.get("symbol") if isinstance(row, dict) else row
        if symbol:
            symbols.append(str(symbol))
    return symbols


def _model_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def build_current_model_validation(db) -> dict[str, Any]:
    """Validate the current production model on the latest time split."""
    from backend.analysis.qlib_engine import (
        MODEL_PATH,
        _feature_cols_for_model,
        _load_model_unchecked,
        _time_split,
        _validation_predictions,
    )
    from backend.backtest.alphalens_qlib import build_validation_report
    from backend.data.qlib_data import FEATURE_COLS, PRODUCTION_FEATURE_COLS, build_training_data

    model, load_error = _load_model_unchecked()
    model_info = {
        "path": str(MODEL_PATH),
        "exists": MODEL_PATH.exists(),
        "mtime_utc": _model_mtime(MODEL_PATH),
        "n_features_current_candidate": len(FEATURE_COLS),
        "n_features_production": len(PRODUCTION_FEATURE_COLS),
        "n_features_model": None,
    }
    if model is None:
        return {
            "status": "model_unavailable",
            "model": {**model_info, "load_error": load_error},
            "recommendation": "keep_quant_disabled",
        }
    feature_cols, dim_info = _feature_cols_for_model(model)
    model_info.update(dim_info)
    if feature_cols is None:
        return {
            "status": "feature_dim_mismatch",
            "model": model_info,
            "recommendation": "keep_quant_disabled",
        }

    panel = build_training_data(
        db,
        include_inactive=True,
        feature_cols=feature_cols,
    )  # M26.1：扩盘后用全量验证
    if panel.empty:
        return {
            "status": "no_training_panel",
            "model": model_info,
            "recommendation": "keep_quant_disabled",
        }

    panel = panel.sort_values(["date", "symbol"] if "symbol" in panel.columns else ["date"])
    train_df, val_df = _time_split(panel)
    if val_df.empty:
        return {
            "status": "no_validation_split",
            "model": model_info,
            "sample": {"n_rows": len(panel), "train_rows": len(train_df), "validation_rows": 0},
            "recommendation": "keep_quant_disabled",
        }

    validation = build_validation_report(
        _validation_predictions(model, val_df, feature_cols=feature_cols),
        label="M26 current production lgbm_alpha.pkl",
        sample={
            "n_rows": len(panel),
            "train_rows": len(train_df),
            "validation_rows": len(val_df),
            "n_stocks": int(panel["symbol"].nunique()) if "symbol" in panel.columns else 1,
            "n_features_validation": len(feature_cols),
            "panel_start": str(pd.to_datetime(panel["date"]).min().date()),
            "panel_end": str(pd.to_datetime(panel["date"]).max().date()),
            "validation_start": str(pd.to_datetime(val_df["date"]).min().date()),
            "validation_end": str(pd.to_datetime(val_df["date"]).max().date()),
        },
    )
    metrics = validation.get("metrics") or {}
    ic = float(metrics.get("ic_mean") or 0.0)
    icir = float(metrics.get("icir") or 0.0)
    gates = validation.get("gates") or {}
    pass_diagnostic_gate = (
        ic >= M26_DIAGNOSTIC_IC_FLOOR
        and icir >= M26_DIAGNOSTIC_ICIR_FLOOR
        and (bool(gates.get("pass_monotonic")) or not M26_DIAGNOSTIC_REQUIRE_MONOTONIC)
    )
    validation.update(
        {
            "status": "ok",
            "model": model_info,
            "promotion_gate_settings": {
                "ic_floor": settings.qlib_train_ic_floor,
                "icir_floor": settings.qlib_train_icir_floor,
                "require_monotonic": settings.qlib_train_require_monotonic,
                "pass": bool(gates.get("pass")),
            },
            "diagnostic_gate_settings": {
                "ic_floor": M26_DIAGNOSTIC_IC_FLOOR,
                "icir_floor": M26_DIAGNOSTIC_ICIR_FLOOR,
                "require_monotonic": M26_DIAGNOSTIC_REQUIRE_MONOTONIC,
                "pass": pass_diagnostic_gate,
            },
        }
    )
    return validation


@contextmanager
def _temporary_settings(**overrides) -> Iterator[None]:
    saved = {key: getattr(settings, key) for key in overrides}
    try:
        for key, value in overrides.items():
            object.__setattr__(settings, key, value)
        yield
    finally:
        for key, value in saved.items():
            object.__setattr__(settings, key, value)


def _max_drawdown_pct(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for ret in returns:
        equity *= 1 + ret
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
    return round(max_dd * 100, 2)


def _profile_metrics(name: str, portfolio_returns: list[float], entry_count: int) -> dict[str, Any]:
    """portfolio_returns: 每笔交易已按 POSITION_PCT 缩放后的组合级别收益率。"""
    wins = [r for r in portfolio_returns if r > 0]
    losses = [r for r in portfolio_returns if r <= 0]
    total = 1.0
    for r in portfolio_returns:
        total *= 1 + r
    # avg_win_loss_ratio = 平均盈利 / 平均亏损绝对值（≠ 标准 profit factor）
    avg_win_loss_ratio = (
        round(sum(wins) / len(wins) / abs(sum(losses) / len(losses)), 2)
        if wins and losses and not math.isclose(sum(losses), 0.0)
        else None
    )
    return {
        "profile": name,
        "entry_signal_count": entry_count,
        "trades": len(portfolio_returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(portfolio_returns) * 100, 2) if portfolio_returns else 0.0,
        "avg_portfolio_return_pct": round(sum(portfolio_returns) / len(portfolio_returns) * 100, 4) if portfolio_returns else 0.0,
        "sharpe": round(annualized_sharpe(portfolio_returns, avg_hold_days=5), 2) if portfolio_returns else 0.0,
        "avg_win_loss_ratio": avg_win_loss_ratio,
        "total_return_pct": round((total - 1) * 100, 2),
        "max_drawdown_pct": _max_drawdown_pct(portfolio_returns),
        "note": f"portfolio_returns = stock_return × position_pct({POSITION_PCT}); sequential approximation",
    }


def simulate_weight_profile(inputs, profile: WeightProfile) -> dict[str, Any]:
    from backend.decision.aggregator import aggregate
    from backend.decision.signal_policy import is_entry_signal

    returns: list[float] = []
    entry_count = 0
    with _temporary_settings(
        paper_trading_profile="new_framework",
        weight_quant=profile.quant,
        weight_technical=profile.technical,
        weight_sentiment=profile.sentiment,
        new_framework_entry_threshold=profile.entry_threshold,
        multi_agent_enabled=False,
        multi_round_debate_enabled=False,
        long_term_constraints_enabled=False,
    ):
        for inp in inputs:
            result = aggregate(
                quant_score=inp.qlib_result.get("score", 0.0),
                technical_result=inp.technical_result,
                sentiment_score=inp.sentiment_result.get("sentiment", 0.0),
                close=inp.close,
                atr=inp.atr,
                sentiment_result=inp.sentiment_result,
            )
            if is_entry_signal(result.get("recommendation", ""), include_legacy=True):
                entry_count += 1
                # 缩放到组合级别：stock-level return × position_pct
                stock_ret = net_return(inp.forward_return_at(5) or 0.0)
                returns.append(stock_ret * POSITION_PCT)
    out = _profile_metrics(profile.name, returns, entry_count)
    out["weights"] = asdict(profile)
    return out


def _price_return(db, symbol: str, start: str, end: str) -> float | None:
    rows = (
        db.query(Price.date, Price.close)
        .filter(Price.symbol == symbol, Price.date >= start, Price.date <= end)
        .order_by(Price.date.asc())
        .all()
    )
    valid = [(date, float(close)) for date, close in rows if close and close > 0]
    if len(valid) < 2:
        return None
    return valid[-1][1] / valid[0][1] - 1


def benchmark_returns(db, symbols: list[str], start: str, end: str) -> dict[str, Any]:
    stock_returns = [ret for symbol in symbols if (ret := _price_return(db, symbol, start, end)) is not None]
    benchmarks: dict[str, Any] = {
        "equal_weight_test2": {
            "n_symbols": len(stock_returns),
            "total_return_pct": round(sum(stock_returns) / len(stock_returns) * 100, 2)
            if stock_returns
            else None,
        }
    }
    for label, candidates in {
        "hs300": ["000300.SH", "000300", "399300"],
        "csi500": ["000905.SH", "000905", "399905"],
    }.items():
        found = None
        for candidate in candidates:
            ret = _price_return(db, candidate, start, end)
            if ret is not None:
                found = {"symbol": candidate, "total_return_pct": round(ret * 100, 2)}
                break
        benchmarks[label] = found or {
            "status": "unavailable_in_local_price_table",
            "tried_symbols": candidates,
        }
    return benchmarks


def _delta(on: dict[str, Any], off: dict[str, Any]) -> dict[str, Any]:
    keys = ["trades", "win_rate_pct", "avg_portfolio_return_pct", "sharpe", "total_return_pct", "max_drawdown_pct"]
    return {
        key: round((on.get(key) or 0) - (off.get(key) or 0), 2)
        for key in keys
    }


def decide_quant_weight(validation: dict[str, Any], backtest: dict[str, Any]) -> dict[str, str]:
    gate = validation.get("promotion_gate_settings") or {}
    gate_pass = bool(gate.get("pass"))
    metrics = validation.get("metrics") or {}
    quantiles = validation.get("quantiles") or []
    gates_detail = validation.get("gates") or {}
    monotonic = bool(gates_detail.get("pass_monotonic"))

    # 单调因子证据：最高桶 vs 最低桶净收益是否单调递增且价差显著
    monotonic_spread = 0.0
    if len(quantiles) >= 2:
        top_ret = float((quantiles[-1] or {}).get("net_mean_return") or 0)
        bot_ret = float((quantiles[0] or {}).get("net_mean_return") or 0)
        monotonic_spread = top_ret - bot_ret
    has_useful_monotonic_signal = monotonic and monotonic_spread > 0.002  # >0.2%/期 价差

    delta = backtest.get("delta_quant_on_fixed_threshold_minus_off") or {}
    trades_fixed = int((backtest.get("quant_on_fixed_threshold") or {}).get("trades") or 0)
    trades_off = int((backtest.get("quant_off") or {}).get("trades") or 0)
    enough_trades = trades_fixed >= 10 or trades_off >= 10
    positive_fixed_backtest = (
        (delta.get("total_return_pct") or 0) > 0
        and (delta.get("sharpe") or 0) >= 0
        and (delta.get("max_drawdown_pct") or 0) <= 0
    )

    if gate_pass and enough_trades and positive_fixed_backtest:
        return {
            "decision": "eligible_for_weight_review",
            "weight_action": "do_not_change_production_yet",
            "rationale": (
                "Model passes IC/ICIR/monotonic gates and fixed-threshold quant_on backtest is not worse. "
                "Run through promotion gate with a small candidate weight (e.g. 0.15)."
            ),
        }
    if has_useful_monotonic_signal and not gate_pass:
        spread_pct = round(monotonic_spread * 100, 3)
        return {
            "decision": "consider_small_weight_experiment",
            "weight_action": "keep weight_quant=0.0 in production; plan test with weight=0.15",
            "rationale": (
                f"IC={metrics.get('ic_mean'):.4f} below gate floor but quantile spread={spread_pct}%/period "
                f"with monotonic=True — factor has real alpha structure. "
                "Recommend: improve model breadth (more stocks in training) or try Kronos, "
                "then re-evaluate. Do NOT add weight based on this model alone until IC improves."
            ),
        }
    return {
        "decision": "keep_quant_disabled",
        "weight_action": "keep weight_quant=0.0",
        "rationale": (
            "IC gate failed and quantile structure is insufficient to justify even a small weight. "
            "Investigate training data breadth or replace model before reconsidering."
        ),
    }


def build_report(
    db,
    *,
    start: str,
    end: str,
    symbols: list[str],
    every_n_days: int,
) -> dict[str, Any]:
    from backend.backtest.backfill_signals import backfill_window

    validation = build_current_model_validation(db)
    inputs = backfill_window(
        start,
        end,
        symbols=symbols,
        use_llm_news=False,
        every_n_days=every_n_days,
        allow_lookahead_quant=True,
    )
    quant_off = simulate_weight_profile(inputs, QUANT_OFF_PROFILE)
    quant_on = simulate_weight_profile(inputs, QUANT_ON_PROFILE)
    quant_on_fixed = simulate_weight_profile(inputs, QUANT_ON_FIXED_THRESHOLD_PROFILE)
    backtest = {
        "start": start,
        "end": end,
        "every_n_days": every_n_days,
        "signal_inputs": len(inputs),
        "position_pct": POSITION_PCT,
        "note": (
            "returns are portfolio-level (stock_return × position_pct=0.15). "
            "Sequential approximation: trades counted as non-overlapping. "
            "Historical backfill uses the current production quant model for attribution only — "
            "not a deployable walk-forward proof."
        ),
        "quant_off": quant_off,
        "quant_on": quant_on,
        "quant_on_fixed_threshold": quant_on_fixed,
        # A/B 设计原版对比（threshold 不同，非单变量）
        "delta_quant_on_minus_off": _delta(quant_on, quant_off),
        # 单变量对照：固定 threshold=25，只改权重（推荐用这个评判量化贡献）
        "delta_quant_on_fixed_threshold_minus_off": _delta(quant_on_fixed, quant_off),
        "benchmarks": benchmark_returns(db, symbols, start, end),
    }
    decision = decide_quant_weight(validation, backtest)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M26",
        "scope": "current quant model baseline + test2 quant_on/off profile comparison",
        "symbols": symbols,
        "current_model_validation": validation,
        "historical_profile_backtest": backtest,
        "kronos_feasibility": {
            "decision": "defer_production_integration",
            "rationale": (
                "Kronos should only be connected as an optional quant factor candidate, "
                "then scored through this same IC/ICIR and profile-backtest report before any production weight change."
            ),
            "minimum_interface": {
                "input": "PIT OHLCV(+amount if available) price window from local prices table",
                "output": "quant score normalized to -100..100 plus metadata",
                "integration_point": "backend.decision.aggregator._blend_quant / aggregate_v2 quant_result",
            },
        },
        "decision": decision,
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    val = report["current_model_validation"]
    metrics = val.get("metrics") or {}
    gate = val.get("promotion_gate_settings") or {}
    diagnostic_gate = val.get("diagnostic_gate_settings") or {}
    bt = report["historical_profile_backtest"]
    off = bt["quant_off"]
    on = bt["quant_on"]
    on_fixed = bt.get("quant_on_fixed_threshold") or {}
    delta_orig = bt["delta_quant_on_minus_off"]
    delta_fixed = bt.get("delta_quant_on_fixed_threshold_minus_off") or {}
    decision = report["decision"]
    quantiles = val.get("quantiles") or []
    lines = [
        "# M26 量化基线报告",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- symbols: {len(report['symbols'])}",
        f"- window: {bt['start']} ~ {bt['end']} / every_n_days={bt['every_n_days']}",
        f"- signal_inputs: {bt['signal_inputs']}",
        f"- position_pct: {bt.get('position_pct', 0.15)} (returns = stock_return × position_pct)",
        "",
        "## 当前 LightGBM 模型验证",
        "",
        f"- status: {val.get('status')}",
        f"- model: {val.get('model', {}).get('path')} / mtime={val.get('model', {}).get('mtime_utc')}",
        f"- feature_dim: status={val.get('model', {}).get('model_dim_status')} / model={val.get('model', {}).get('n_features_model')} / validation={val.get('model', {}).get('n_features_validation')} / current_candidate={val.get('model', {}).get('n_features_current_candidate')}",
        f"- IC: {metrics.get('ic_mean')} / ICIR: {metrics.get('icir')} / IC>0占比: {metrics.get('ic_positive_rate')} / monotonic: {(val.get('gates') or {}).get('pass_monotonic')}",
        f"- production gate pass: {gate.get('pass')} (ic_floor={gate.get('ic_floor')}, icir_floor={gate.get('icir_floor')}, require_monotonic={gate.get('require_monotonic')})",
        f"- M26 diagnostic gate pass: {diagnostic_gate.get('pass')} (ic_floor={diagnostic_gate.get('ic_floor')}, icir_floor={diagnostic_gate.get('icir_floor')}, require_monotonic={diagnostic_gate.get('require_monotonic')})",
        "",
        "### 分位收益（最高分桶 vs 最低分桶单调性）",
        "",
        "| 分位桶 | 净均值收益/期 |",
        "| ---: | ---: |",
    ]
    for q in quantiles:
        lines.append(f"| 桶{q.get('bucket')} | {round((q.get('net_mean_return') or 0)*100, 3)}% |")
    lines += [
        "",
        "## 回测对照（returns 已按 position_pct=0.15 缩放）",
        "",
        "### A. 单变量对照（仅改权重，固定 threshold=25）⭐ 推荐用这组判断量化贡献",
        "",
        "| profile | trades | win_rate | total_return | sharpe | max_drawdown |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| quant_off (Q=0, T=0.6, S=0.4, thr=25) | {off['trades']} | {off['win_rate_pct']}% | {off['total_return_pct']}% | {off['sharpe']} | {off['max_drawdown_pct']}% |",
        f"| quant_on_fixed (Q=0.45, T=0.4, S=0.15, thr=25) | {on_fixed.get('trades')} | {on_fixed.get('win_rate_pct')}% | {on_fixed.get('total_return_pct')}% | {on_fixed.get('sharpe')} | {on_fixed.get('max_drawdown_pct')}% |",
        f"| delta(fixed-off) | {delta_fixed.get('trades')} | {delta_fixed.get('win_rate_pct')}pp | {delta_fixed.get('total_return_pct')}pp | {delta_fixed.get('sharpe')} | {delta_fixed.get('max_drawdown_pct')}pp |",
        "",
        "### B. 原版 A/B 对照（threshold 不同，供参考，非单变量）",
        "",
        "| profile | trades | win_rate | total_return | sharpe | max_drawdown |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| quant_off (thr=25) | {off['trades']} | {off['win_rate_pct']}% | {off['total_return_pct']}% | {off['sharpe']} | {off['max_drawdown_pct']}% |",
        f"| quant_on (thr=20) | {on['trades']} | {on['win_rate_pct']}% | {on['total_return_pct']}% | {on['sharpe']} | {on['max_drawdown_pct']}% |",
        f"| delta(on-off) | {delta_orig.get('trades')} | {delta_orig.get('win_rate_pct')}pp | {delta_orig.get('total_return_pct')}pp | {delta_orig.get('sharpe')} | {delta_orig.get('max_drawdown_pct')}pp |",
        "",
        "## 基准",
        "",
    ]
    for name, payload in bt["benchmarks"].items():
        if payload is None:
            lines.append(f"- {name}: unavailable")
        elif "total_return_pct" in payload:
            lines.append(f"- {name}: {payload['total_return_pct']}%")
        else:
            lines.append(f"- {name}: {payload.get('status')}")
    lines.extend(
        [
            "",
            "## Kronos 可行性结论",
            "",
            f"- decision: {report['kronos_feasibility']['decision']}",
            f"- integration_point: {report['kronos_feasibility']['minimum_interface']['integration_point']}",
            "",
            "## 决策",
            "",
            f"- decision: {decision['decision']}",
            f"- action: {decision['weight_action']}",
            f"- rationale: {decision['rationale']}",
            "",
            "> ⚠ 回测注意事项：(1) position_pct=0.15 已应用，最大回撤和总收益为组合级别指标。"
            " (2) 交易视为顺序执行（非并发），是近似值。"
            f" (3) {bt.get('note', '')}",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end", default="2026-05-14")
    parser.add_argument("--every-n-days", type=int, default=5)
    parser.add_argument("--symbols", nargs="*", help="Defaults to paper_trading/test2_universe.json")
    parser.add_argument(
        "--universe-path",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
        help=f"Defaults to M26 test2. Pass {M27_TEST3_UNIVERSE_PATH} explicitly for M27/test3 diagnostics.",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true", help="Print markdown report to stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = args.symbols or load_test2_symbols(args.universe_path)
    db = SessionLocal()
    try:
        report = build_report(
            db,
            start=args.start,
            end=args.end,
            symbols=symbols,
            every_n_days=args.every_n_days,
        )
    finally:
        db.close()

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    else:
        print(f"wrote {args.markdown_output}")
        print(f"wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
