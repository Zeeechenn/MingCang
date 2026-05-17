"""
M4.9 exit 逻辑实验。

在 M4.8 选定的 entry_threshold=25 下：
  1. 用 backfill_signals.iter_window 产 SignalInput
  2. 跑 path_a 拿 composite_score → 过滤出 entries
  3. 对每个 entry 拉未来 N 天 OHLC（从 Price 表）
  4. 对每个 exit 策略各跑一遍 → 算 trades / win_rate / sharpe / drawdown

策略：
  • fixed_3d / fixed_5d / fixed_10d        — 固定持仓
  • atr_2x_4x / atr_2x_3x / atr_1_5x_3x    — ATR 止损/止盈
  • trailing_atr_2x / trailing_atr_2_5x    — ATR 移动止损

复用 backend/backtest/exit_logic_experiment 里的退出函数。
"""
from __future__ import annotations
import json
import logging
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Sequence

from backend.backtest.compare_paths import (
    SignalInput, _no_llm_settings, _path_a, _max_drawdown,
)
from backend.backtest.exit_logic_experiment import (
    _exit_fixed, _exit_atr_bracket, _exit_trailing,
)

logger = logging.getLogger(__name__)


@dataclass
class _PriceRow:
    """复用 exit_logic_experiment 的 row 接口（需 close/high/low/atr14/date）"""
    date: str
    close: float
    high: float
    low: float
    atr14: float | None = None


@dataclass
class ExitStrategyMetrics:
    name: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_return: float           # %
    sharpe: float               # 年化（按平均持仓天数）
    profit_loss: float | None
    total_return: float         # %（独立笔复利）
    max_drawdown: float         # %
    avg_hold_days: float
    exit_reasons: dict
    notes: list[str] = field(default_factory=list)


def _fetch_forward_rows(db, symbol: str, entry_date: str, n_days: int = 20) -> list[_PriceRow]:
    """拉 entry_date 后 n_days 个交易日的 OHLC（不含 entry 当天）"""
    from backend.data.database import Price

    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date > entry_date)
        .order_by(Price.date.asc())
        .limit(n_days)
        .all()
    )
    return [
        _PriceRow(date=r.date, close=r.close, high=r.high, low=r.low, atr14=r.atr14)
        for r in rows
    ]


def _build_strategy_runners() -> dict[str, Callable]:
    """生成 (策略名 → exit fn) 映射；每个 fn 签名 = (rows_with_entry, entry_idx=0) → (exit_idx, reason)"""
    return {
        "fixed_3d":         lambda rows: _exit_fixed(rows, 0, 3),
        "fixed_5d":         lambda rows: _exit_fixed(rows, 0, 5),
        "fixed_10d":        lambda rows: _exit_fixed(rows, 0, 10),
        "atr_2x_4x":        lambda rows: _exit_atr_bracket(rows, 0, 2.0, 4.0),
        "atr_2x_3x":        lambda rows: _exit_atr_bracket(rows, 0, 2.0, 3.0),
        "atr_1_5x_3x":      lambda rows: _exit_atr_bracket(rows, 0, 1.5, 3.0),
        "trailing_atr_2x":  lambda rows: _exit_trailing(rows, 0, 2.0),
        "trailing_atr_2_5x":lambda rows: _exit_trailing(rows, 0, 2.5),
    }


def _metrics(name: str, trades: list[tuple[float, str, int]]) -> ExitStrategyMetrics:
    """trades = [(return, reason, hold_days), ...]"""
    if not trades:
        return ExitStrategyMetrics(
            name=name, trades=0, wins=0, losses=0,
            win_rate=0.0, avg_return=0.0, sharpe=0.0,
            profit_loss=None, total_return=0.0, max_drawdown=0.0,
            avg_hold_days=0.0, exit_reasons={},
        )
    returns = [t[0] for t in trades]
    reasons = [t[1] for t in trades]
    hold_days = [t[2] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    avg_hold = statistics.mean(hold_days)
    # 年化 sharpe：以平均持仓天数标定
    sharpe = mean / stdev * math.sqrt(252 / max(avg_hold, 1)) if stdev > 0 else 0.0
    pl = (
        statistics.mean(wins) / abs(statistics.mean(losses))
        if wins and losses and statistics.mean(losses) != 0
        else None
    )
    total = 1.0
    for r in returns:
        total *= 1 + r
    return ExitStrategyMetrics(
        name=name,
        trades=len(returns),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(returns) * 100, 1),
        avg_return=round(mean * 100, 2),
        sharpe=round(sharpe, 2),
        profit_loss=round(pl, 2) if pl is not None else None,
        total_return=round((total - 1) * 100, 2),
        max_drawdown=_max_drawdown(returns),
        avg_hold_days=round(avg_hold, 2),
        exit_reasons=dict(Counter(reasons)),
    )


def run_exit_sweep(
    inputs: Sequence[SignalInput],
    *,
    threshold: float = 25.0,
    forward_days: int = 20,
) -> dict:
    """
    1. 对每个 input 跑 path_a → composite_score
    2. score > threshold 视为 entry
    3. 对每个 entry 拉未来 forward_days 个 OHLC
    4. 对每个 exit 策略各跑一遍

    Returns:
        {
            "n_entries": int,
            "threshold": float,
            "strategies": [ExitStrategyMetrics dict, ...],
            "recommended": {"name": str, "reason": str},
        }
    """
    from backend.data.database import SessionLocal

    # 一次 path_a 算 composite_score
    with _no_llm_settings():
        entries: list[SignalInput] = []
        for inp in inputs:
            try:
                a = _path_a(inp)
            except Exception:
                continue
            if a.get("composite_score", 0) > threshold:
                entries.append(inp)

    if not entries:
        return {
            "n_entries": 0,
            "threshold": threshold,
            "strategies": [],
            "recommended": {"name": None, "reason": "无 entries 信号"},
        }

    # 拉 OHLC 并跑各策略
    db = SessionLocal()
    strategies = _build_strategy_runners()
    results: dict[str, list[tuple[float, str, int]]] = {n: [] for n in strategies}
    skipped = 0

    try:
        for inp in entries:
            fwd_rows = _fetch_forward_rows(db, inp.symbol, inp.date, n_days=forward_days)
            if not fwd_rows:
                skipped += 1
                continue
            # 复用 exit fn 期待 rows[0]=entry，rows[1:]=forward → 构造时把 entry 放第一行
            entry_row = _PriceRow(
                date=inp.date, close=inp.close,
                high=inp.close, low=inp.close,    # entry 当天的 high/low 不需要（exit 从 idx+1 起）
                atr14=inp.atr,
            )
            all_rows = [entry_row] + fwd_rows
            for name, exit_fn in strategies.items():
                try:
                    exit_idx, reason = exit_fn(all_rows)
                except Exception as e:
                    logger.debug("exit_fn %s failed for %s %s: %s",
                                 name, inp.symbol, inp.date, e)
                    continue
                if exit_idx <= 0:
                    continue
                exit_close = all_rows[exit_idx].close
                ret = (exit_close - inp.close) / inp.close
                hold_days = exit_idx   # entry @ 0
                results[name].append((ret, reason, hold_days))
    finally:
        db.close()

    rows = [_metrics(n, trades) for n, trades in results.items()]
    if skipped:
        for r in rows:
            r.notes.append(f"{skipped} entries 因 forward OHLC 不足跳过")

    recommended = _recommend(rows)
    return {
        "n_entries": len(entries),
        "threshold": threshold,
        "skipped_no_ohlc": skipped,
        "strategies": [m.__dict__ for m in rows],
        "recommended": recommended,
    }


def _recommend(rows: list[ExitStrategyMetrics]) -> dict:
    """挑 trades >= 5 中 Sharpe 最高的；并列时取 drawdown 更小的（更接近 0）"""
    valid = [r for r in rows if r.trades >= 5]
    if not valid:
        return {"name": None, "reason": "所有策略 trades < 5，样本不足"}
    valid.sort(key=lambda r: (-r.sharpe, -r.max_drawdown))
    winner = valid[0]
    runner_up = valid[1] if len(valid) > 1 else None
    parts = [
        f"{winner.name} Sharpe {winner.sharpe}, win {winner.win_rate}%, dd {winner.max_drawdown}%",
        f"trades {winner.trades}, avg_hold {winner.avg_hold_days}d",
    ]
    if runner_up:
        parts.append(
            f"次优 {runner_up.name}（Sharpe {runner_up.sharpe}, "
            f"win {runner_up.win_rate}%, dd {runner_up.max_drawdown}%）"
        )
    return {"name": winner.name, "reason": "; ".join(parts)}


def main(argv: list[str] | None = None) -> int:
    """CLI：回填 → entries 过滤 → 多策略 exit → 输出对比表 + 推荐"""
    import argparse
    from backend.backtest.backfill_signals import iter_window

    ap = argparse.ArgumentParser(description="M4.9 exit 逻辑实验")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-05-08")
    ap.add_argument("--every-n-days", type=int, default=1)
    ap.add_argument("--threshold", type=float, default=25.0)
    ap.add_argument("--forward-days", type=int, default=20)
    args = ap.parse_args(argv)

    print(f"# 回填 {args.start} ~ {args.end} every_n_days={args.every_n_days}", flush=True)
    inputs = list(iter_window(args.start, args.end, every_n_days=args.every_n_days))
    print(f"# 生成 {len(inputs)} 个 SignalInput", flush=True)

    report = run_exit_sweep(inputs, threshold=args.threshold, forward_days=args.forward_days)
    print(f"# entries @ threshold={args.threshold}: {report['n_entries']}", flush=True)
    print(f"# 跳过（OHLC 不足）: {report['skipped_no_ohlc']}", flush=True)

    print()
    print("| strategy | trades | wins | win_rate | avg_ret | sharpe | profit_loss | total | max_dd | hold |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s in report["strategies"]:
        print(f"| {s['name']:<18} | {s['trades']:>3} | {s['wins']:>3} | "
              f"{s['win_rate']:>5.1f}% | {s['avg_return']:>+6.2f}% | "
              f"{s['sharpe']:>+5.2f} | {s['profit_loss']} | "
              f"{s['total_return']:>+8.2f}% | {s['max_drawdown']:>+6.2f}% | "
              f"{s['avg_hold_days']:>4.1f}d |")

    print(f"\n## 推荐\n{report['recommended']}")
    print("\n---JSON---")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
