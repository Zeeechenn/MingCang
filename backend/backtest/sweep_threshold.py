"""
M4.8 entry_threshold 扫描器。

输入：已生成的 SignalInput 列表（或通过 backfill_signals.iter_window 流式生成）。
逻辑：对每个 input 跑一次 path A 得到 composite_score → 对多个候选阈值各自统计 entry+forward returns。

为什么只跑 path A：
  • M4.6 实测 path B 在 LLM 禁用时与 path A 等价（差异 <3 分）
  • 跑一次 path A 即可，避免 2× 计算

输出：每档阈值的 trades/win_rate/Sharpe/max_drawdown/total_return 表 + 推荐档位。
"""
from __future__ import annotations
import json
import logging
import math
import statistics
from dataclasses import dataclass, asdict
from typing import Sequence

from backend.backtest.compare_paths import SignalInput, _no_llm_settings, _path_a, _max_drawdown

logger = logging.getLogger(__name__)


@dataclass
class ThresholdMetrics:
    threshold: float
    trades: int
    wins: int
    losses: int
    win_rate: float          # %
    avg_return: float        # %
    sharpe: float
    profit_loss: float | None
    total_return: float      # %（独立笔复利）
    max_drawdown: float      # %
    expectancy: float        # 平均每笔收益 × 1 笔（即 avg_return）

    def to_dict(self) -> dict:
        return asdict(self)


def _metrics(threshold: float, returns: list[float]) -> ThresholdMetrics:
    if not returns:
        return ThresholdMetrics(
            threshold=threshold, trades=0, wins=0, losses=0,
            win_rate=0.0, avg_return=0.0, sharpe=0.0,
            profit_loss=None, total_return=0.0, max_drawdown=0.0,
            expectancy=0.0,
        )
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    sharpe = mean / stdev * math.sqrt(252 / 5) if stdev > 0 else 0.0
    pl = (
        statistics.mean(wins) / abs(statistics.mean(losses))
        if wins and losses and statistics.mean(losses) != 0
        else None
    )
    total = 1.0
    for r in returns:
        total *= 1 + r
    return ThresholdMetrics(
        threshold=threshold,
        trades=len(returns),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(returns) * 100, 1),
        avg_return=round(mean * 100, 2),
        sharpe=round(sharpe, 2),
        profit_loss=round(pl, 2) if pl is not None else None,
        total_return=round((total - 1) * 100, 2),
        max_drawdown=_max_drawdown(returns),
        expectancy=round(mean * 100, 2),
    )


def sweep(
    inputs: Sequence[SignalInput],
    thresholds: Sequence[float] = (10, 15, 20, 25, 30, 35, 40),
    *,
    exit_days: int = 5,
) -> dict:
    """
    对 inputs 在每个 threshold 上统计 entry+forward returns。

    Returns:
        {
            "thresholds": [ThresholdMetrics dict, ...],
            "recommended": {"threshold": float, "reason": str},
            "n_inputs": int,
            "exit_days": int,
        }
    """
    # 一次扫描算 composite_score
    with _no_llm_settings():
        scored: list[tuple[SignalInput, float]] = []
        for inp in inputs:
            try:
                result = _path_a(inp)
            except Exception as e:
                logger.debug("path_a failed for %s %s: %s", inp.symbol, inp.date, e)
                continue
            scored.append((inp, result.get("composite_score", 0.0)))

    out_rows: list[ThresholdMetrics] = []
    for t in thresholds:
        returns = []
        for inp, s in scored:
            if s > t:
                if len(inp.forward_returns) >= exit_days:
                    returns.append(inp.forward_returns[exit_days - 1])
                elif inp.forward_returns:
                    returns.append(inp.forward_returns[-1])
        out_rows.append(_metrics(t, returns))

    recommended = _recommend(out_rows)
    return {
        "n_inputs": len(scored),
        "exit_days": exit_days,
        "thresholds": [m.to_dict() for m in out_rows],
        "recommended": recommended,
    }


def _recommend(rows: list[ThresholdMetrics]) -> dict:
    """
    选最优阈值的规则：
      1. 排除 trades < 5（样本太小）
      2. 在剩余里按 Sharpe 降序选 top-3
      3. 再按 max_drawdown 升序（即回撤更小）打破平局
      4. 输出 winner + 理由
    """
    valid = [r for r in rows if r.trades >= 5]
    if not valid:
        return {"threshold": None, "reason": "所有档位 trades < 5，样本不足"}

    # sharpe 越高越好；drawdown 越接近 0 越好（drawdown 是负数）
    # sort key 都取负值 → ascending 后高 sharpe + 小 drawdown（接近 0）排前面
    valid.sort(key=lambda r: (-r.sharpe, -r.max_drawdown))

    # 排序后 sharpe 越高越靠前，drawdown 平 sharpe 时较小（更接近 0）越靠前
    winner = valid[0]
    runner_up = valid[1] if len(valid) > 1 else None

    reason_parts = [
        f"threshold={winner.threshold} 是 trades>=5 中 Sharpe 最高的档位（{winner.sharpe}）",
        f"win_rate={winner.win_rate}% / drawdown={winner.max_drawdown}%",
        f"trades={winner.trades}",
    ]
    if runner_up:
        reason_parts.append(
            f"次优 threshold={runner_up.threshold}（Sharpe {runner_up.sharpe}, "
            f"trades {runner_up.trades}, drawdown {runner_up.max_drawdown}%）"
        )
    return {"threshold": winner.threshold, "reason": "; ".join(reason_parts)}


def main(argv: list[str] | None = None) -> int:
    """CLI: 跑回填 → 扫阈值 → 打印 markdown 表 + JSON"""
    import argparse
    from backend.backtest.backfill_signals import iter_window

    ap = argparse.ArgumentParser(description="M4.8 entry_threshold 扫描")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-05-08")
    ap.add_argument("--every-n-days", type=int, default=1)
    ap.add_argument("--exit-days", type=int, default=5)
    ap.add_argument(
        "--thresholds", default="10,15,20,25,30,35,40",
        help="逗号分隔阈值（默认 10,15,20,25,30,35,40）",
    )
    ap.add_argument("--use-llm-news", action="store_true",
                    help="news_cache miss 时调 OpenAI 回填")
    args = ap.parse_args(argv)

    thresholds = tuple(float(x) for x in args.thresholds.split(","))

    print(f"# 回填 {args.start} ~ {args.end} every_n_days={args.every_n_days}", flush=True)
    inputs = list(iter_window(
        args.start, args.end,
        use_llm_news=args.use_llm_news,
        every_n_days=args.every_n_days,
    ))
    print(f"# 生成 {len(inputs)} 个 SignalInput", flush=True)
    print(f"# 扫描阈值 {thresholds}", flush=True)

    if not inputs:
        print(json.dumps({"error": "no_inputs"}))
        return 1

    report = sweep(inputs, thresholds=thresholds, exit_days=args.exit_days)

    # 打印 markdown 表
    print()
    print("| threshold | trades | wins | win_rate | avg_ret | sharpe | profit_loss | total_ret | max_dd |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in report["thresholds"]:
        print(f"| {row['threshold']:>4} | {row['trades']:>4} | {row['wins']:>4} | "
              f"{row['win_rate']:>5.1f}% | {row['avg_return']:>+6.2f}% | "
              f"{row['sharpe']:>+5.2f} | {row['profit_loss']} | "
              f"{row['total_return']:>+7.2f}% | {row['max_drawdown']:>+6.2f}% |")

    print(f"\n## 推荐档位\n{report['recommended']}\n")
    print("---JSON---")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
