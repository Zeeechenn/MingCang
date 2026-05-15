"""
退出逻辑实验：用同一信号池比较 5 种退出方式。

执行：
  PYTHONPATH=. python -m backend.backtest.exit_logic_experiment
"""
from __future__ import annotations

from collections import Counter
import math
import statistics

from backend.data.database import SessionLocal, Signal, Price
from backend.data.point_in_time import pit_session
from backend.decision.signal_policy import entry_recommendations


LONG_RECS = set(entry_recommendations(include_legacy=True))


def _prices(db, symbol: str, as_of_end: str | None = None) -> list[Price]:
    """Fetch price rows for a symbol, optionally capped at as_of_end."""
    q = db.query(Price).filter(Price.symbol == symbol)
    if as_of_end:
        q = q.filter(Price.date <= as_of_end)
    return q.order_by(Price.date.asc()).all()


def _price_index(rows: list[Price]) -> dict[str, int]:
    """Build a date-to-index lookup map from a price row list."""
    return {row.date: i for i, row in enumerate(rows)}


def _exit_fixed(rows, start_idx: int, hold_days: int) -> tuple[int, str]:
    """Exit after a fixed number of hold days."""
    idx = min(start_idx + hold_days, len(rows) - 1)
    return idx, f"fixed_{hold_days}d"


def _exit_atr_bracket(rows, start_idx: int, stop_mult: float, take_mult: float) -> tuple[int, str]:
    """Exit when price hits ATR-based stop or take-profit bracket."""
    entry = rows[start_idx].close
    atr = rows[start_idx].atr14 or entry * 0.03
    stop = entry - atr * stop_mult
    take = entry + atr * take_mult
    for idx in range(start_idx + 1, len(rows)):
        if rows[idx].low <= stop:
            return idx, "atr_stop"
        if rows[idx].high >= take:
            return idx, "atr_take"
    return len(rows) - 1, "end"


def _exit_trailing(rows, start_idx: int, atr_mult: float) -> tuple[int, str]:
    """Exit using a dynamic trailing stop based on ATR."""
    entry = rows[start_idx].close
    atr = rows[start_idx].atr14 or entry * 0.03
    trailing = entry - atr * atr_mult
    for idx in range(start_idx + 1, len(rows)):
        trailing = max(trailing, rows[idx].close - atr * atr_mult)
        if rows[idx].low <= trailing:
            return idx, "trailing_stop"
    return len(rows) - 1, "end"


def _exit_signal_reverse(rows, start_idx: int, signal_by_date: dict[str, Signal]) -> tuple[int, str]:
    """Exit when a subsequent signal indicates a composite score below -15."""
    for idx in range(start_idx + 1, len(rows)):
        sig = signal_by_date.get(rows[idx].date)
        if sig and sig.composite_score < -15:
            return idx, "signal_reverse"
    return len(rows) - 1, "end"


def _metrics(returns: list[float], reasons: list[str]) -> dict:
    """Compute trade performance metrics from a list of returns."""
    if not returns:
        return {"trades": 0}
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    sharpe = mean / stdev * math.sqrt(252) if stdev else 0.0
    profit_loss = (
        statistics.mean(wins) / abs(statistics.mean(losses))
        if wins and losses and statistics.mean(losses) != 0
        else None
    )
    return {
        "trades": len(returns),
        "sharpe": round(sharpe, 2),
        "win_rate": round(len(wins) / len(returns) * 100, 1),
        "profit_loss": round(profit_loss, 2) if profit_loss is not None else None,
        "avg_return": round(mean * 100, 2),
        "exit_reasons": dict(Counter(reasons)),
        "_returns": returns,   # 保留给 DSR 二次统计
    }


def annotate_with_dsr(metrics_by_strategy: dict[str, dict]) -> dict[str, dict]:
    """
    给 run() 输出的每个方案补 DSR / p-value。

    SR_0 按本次扫描的方案数 N（multiple testing）算，
    每个方案用自己的收益序列重新走 DSR 公式。
    """
    from backend.backtest.statistics import deflated_sharpe

    sharpes = [m["sharpe"] for m in metrics_by_strategy.values()
               if m.get("trades", 0) > 0]
    n_trials = len(sharpes)
    out = {}
    for name, m in metrics_by_strategy.items():
        if m.get("trades", 0) == 0 or "_returns" not in m:
            out[name] = m
            continue
        res = deflated_sharpe(
            returns=m["_returns"],
            trial_sharpes=sharpes,
            sharpe_observed=m["sharpe"],
            n_trials=n_trials,
            periods_per_year=252,
        )
        annotated = {k: v for k, v in m.items() if k != "_returns"}
        annotated["dsr"] = round(res.dsr, 4)
        annotated["dsr_p_value"] = round(res.p_value, 4)
        annotated["dsr_threshold"] = round(res.sharpe_threshold, 4)
        annotated["dsr_significant"] = res.is_significant()
        annotated["n_trials_in_scan"] = n_trials
        out[name] = annotated
    return out


def _run_scan(
    db,
    as_of_start: str | None = None,
    as_of_end: str | None = None,
) -> dict[str, dict]:
    """Scan all signals across all exit strategies and return per-strategy metrics."""
    symbols = [r[0] for r in db.query(Signal.symbol).distinct().all()]
    experiments = {
        "fixed_5d": lambda rows, idx, sigs: _exit_fixed(rows, idx, 5),
        "fixed_10d": lambda rows, idx, sigs: _exit_fixed(rows, idx, 10),
        "atr_2x_4x": lambda rows, idx, sigs: _exit_atr_bracket(rows, idx, 2.0, 4.0),
        "trailing_atr_2_5x": lambda rows, idx, sigs: _exit_trailing(rows, idx, 2.5),
        "signal_reverse": _exit_signal_reverse,
    }
    results = {name: {"returns": [], "reasons": []} for name in experiments}

    for symbol in symbols:
        rows = _prices(db, symbol, as_of_end=as_of_end)
        idx_by_date = _price_index(rows)
        sig_q = db.query(Signal).filter(Signal.symbol == symbol)
        if as_of_start:
            sig_q = sig_q.filter(Signal.date >= as_of_start)
        if as_of_end:
            sig_q = sig_q.filter(Signal.date <= as_of_end)
        signals = sig_q.order_by(Signal.date.asc()).all()
        sig_by_date = {s.date: s for s in signals}
        for sig in signals:
            if sig.recommendation not in LONG_RECS or sig.date not in idx_by_date:
                continue
            entry_idx = idx_by_date[sig.date]
            if entry_idx >= len(rows) - 1:
                continue
            entry = rows[entry_idx].close
            for name, fn in experiments.items():
                exit_idx, reason = fn(rows, entry_idx, sig_by_date)
                ret = (rows[exit_idx].close - entry) / entry
                results[name]["returns"].append(ret)
                results[name]["reasons"].append(reason)

    return {
        name: _metrics(payload["returns"], payload["reasons"])
        for name, payload in results.items()
    }


def run(
    as_of_start: str | None = None,
    as_of_end: str | None = None,
    db=None,
) -> dict[str, dict]:
    """
    扫描退出逻辑实验。

    as_of_start / as_of_end — 限定信号入场日期窗口（YYYY-MM-DD，闭区间）。
    持仓退出可能延伸到 as_of_end 之后，但只截到价格 ≤ as_of_end 的数据为止
    （这是 walk-forward / holdout 的标准约定：训练只能用 ≤ as_of_end 的数据）。
    db — 注入 session，否则自建。
    """
    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    try:
        if as_of_end:
            with pit_session(db, as_of_end) as pit_db:
                return _run_scan(pit_db, as_of_start=as_of_start, as_of_end=as_of_end)
        return _run_scan(db, as_of_start=as_of_start, as_of_end=as_of_end)
    finally:
        if owns_db:
            db.close()


def walk_forward_eval(
    start: str,
    end: str,
    train_days: int = 365,
    test_days: int = 60,
    step_days: int = 60,
    db=None,
) -> dict:
    """
    在 [start, end] 之间生成滚动窗口，每窗口在 train 段做扫描 → 选最佳方案 →
    在 test 段记录该方案 metrics。聚合跨窗口结果 + DSR 横切。

    返回 walk_forward.run_walk_forward 标准输出。
    """
    from backend.backtest.walk_forward import generate_windows, run_walk_forward

    windows = generate_windows(start, end, train_days, test_days, step_days)

    def evaluator(window) -> dict:
        """Select best strategy in train window and evaluate it on test window."""
        train_res = run(as_of_start=window.train_start,
                        as_of_end=window.train_end, db=db)
        valid = {n: m for n, m in train_res.items() if m.get("trades", 0) > 0}
        if not valid:
            return {"sharpe": 0.0, "selected": None, "reason": "train 无样本"}
        best_name = max(valid, key=lambda n: valid[n]["sharpe"])
        test_res = run(as_of_start=window.test_start,
                       as_of_end=window.test_end, db=db)
        test_metrics = test_res.get(best_name, {})
        return {
            "selected": best_name,
            "sharpe": test_metrics.get("sharpe", 0.0),
            "win_rate": test_metrics.get("win_rate", 0.0),
            "trades": test_metrics.get("trades", 0),
            "avg_return": test_metrics.get("avg_return", 0.0),
            "train_best_sharpe": valid[best_name]["sharpe"],
        }

    return run_walk_forward(windows, evaluator, metric_key="sharpe")


def holdout_eval(
    holdout_start: str | None = None,
    holdout_end: str | None = None,
    chosen_strategy: str = "fixed_10d",
    db=None,
) -> dict:
    """
    holdout 一次性裁判。chosen_strategy 必须是在 holdout 之前已经选定的方案。
    返回该方案在 holdout 时间窗内的 metrics + DSR 标签。
    """
    from backend.backtest.walk_forward import HOLDOUT_START

    start = holdout_start or HOLDOUT_START
    res = run(as_of_start=start, as_of_end=holdout_end, db=db)
    annotated = annotate_with_dsr(res)
    return {
        "holdout_window": {"start": start, "end": holdout_end},
        "chosen_strategy": chosen_strategy,
        "result": annotated.get(chosen_strategy, {}),
        "all_strategies": annotated,
    }


if __name__ == "__main__":
    import json
    raw = run()
    print(json.dumps(annotate_with_dsr(raw), ensure_ascii=False, indent=2))
