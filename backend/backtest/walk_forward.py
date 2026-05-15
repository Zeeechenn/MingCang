"""
Walk-Forward 评估器（Tier 2）

为什么需要：
  • 阶段A 的 8 方案扫描是 in-sample 全期评估，参数选择和评估在同一段时间上，
    属于"自我证明"。学术 SOTA（Bailey & López de Prado, mbrenndoerfer 等）
    要求 rolling-window walk-forward + 独立 holdout。
  • 本模块提供通用 harness：切窗口 → 在每个窗口上调用 evaluator → 跨窗口聚合 + DSR。

不绑死任何具体回测：evaluator 是回调函数，输入 WalkWindow，输出 metrics dict。
现有的 exit_logic_experiment / backtrader_eval 都可以被包装进来。

Holdout 约定：
  • HOLDOUT_START = "2026-01-01"，2026-01 之后视为独立 holdout，
    所有参数决策只能在此之前做出，holdout 仅做一次裁判。
"""
from __future__ import annotations
import logging
import statistics
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

HOLDOUT_START = "2026-01-01"


@dataclass
class WalkWindow:
    train_start: str   # "YYYY-MM-DD"
    train_end: str
    test_start: str
    test_end: str
    label: str = ""

    def to_dict(self) -> dict:
        """Serialize walk window to dictionary."""
        return asdict(self)


def _parse(d: str) -> date:
    """Parse an ISO date string to a date object."""
    return datetime.strptime(d, "%Y-%m-%d").date()


def _fmt(d: date) -> str:
    """Format a date object as an ISO date string."""
    return d.strftime("%Y-%m-%d")


def generate_windows(
    start: str,
    end: str,
    train_days: int = 365,
    test_days: int = 60,
    step_days: int = 60,
    holdout_start: str | None = HOLDOUT_START,
) -> list[WalkWindow]:
    """
    生成滚动窗口。train + test 段不重叠；train 的右端 = test 的左端 - 1 天。
    所有窗口的 test_end 严格小于 holdout_start，确保 holdout 不被训练污染。

    Returns 按 test_start 升序。
    """
    s = _parse(start)
    e = _parse(end)
    if holdout_start:
        ho = _parse(holdout_start)
        if e >= ho:
            e = ho - timedelta(days=1)

    windows: list[WalkWindow] = []
    train_start = s
    while True:
        train_end = train_start + timedelta(days=train_days - 1)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=test_days - 1)
        if test_end > e:
            break
        windows.append(WalkWindow(
            train_start=_fmt(train_start),
            train_end=_fmt(train_end),
            test_start=_fmt(test_start),
            test_end=_fmt(test_end),
            label=f"{_fmt(test_start)}~{_fmt(test_end)}",
        ))
        train_start = train_start + timedelta(days=step_days)
    return windows


def run_walk_forward(
    windows: Sequence[WalkWindow],
    evaluator: Callable[[WalkWindow], dict],
    metric_key: str = "sharpe",
) -> dict:
    """
    在每个窗口上调用 evaluator(window)，输出 dict 至少含 metric_key。
    跨窗口聚合：均值、标准差、最差窗口、最佳窗口。

    若所有窗口的 metric 都是数值，附加 DSR 评估（trial 序列 = 窗口 metric 序列）。
    """
    per_window: list[dict] = []
    metric_values: list[float] = []

    for w in windows:
        try:
            res = evaluator(w)
            res = dict(res)
            res["window"] = w.to_dict()
            per_window.append(res)
            v = res.get(metric_key)
            if isinstance(v, (int, float)):
                metric_values.append(float(v))
        except Exception as e:
            logger.error("evaluator 失败 %s: %s", w.label, e)
            per_window.append({"window": w.to_dict(), "error": str(e)})

    summary: dict = {
        "n_windows": len(windows),
        "n_evaluated": len(metric_values),
        "metric_key": metric_key,
    }
    if metric_values:
        mean = statistics.mean(metric_values)
        stdev = statistics.pstdev(metric_values) if len(metric_values) > 1 else 0.0
        summary["mean"] = round(mean, 4)
        summary["stdev"] = round(stdev, 4)
        summary["min"] = round(min(metric_values), 4)
        summary["max"] = round(max(metric_values), 4)
        # 跨窗口 t-stat
        if stdev > 0 and len(metric_values) > 1:
            t = mean / (stdev / (len(metric_values) ** 0.5))
            summary["t_stat_across_windows"] = round(t, 3)
        # 用 DSR 估 SR_0
        try:
            from backend.backtest.statistics import expected_max_sharpe
            sr0 = expected_max_sharpe(metric_values, n_trials=len(metric_values))
            summary["multi_window_sr_threshold"] = round(sr0, 4)
            summary["passes_multi_window_threshold"] = mean > sr0
        except Exception as e:
            summary["dsr_error"] = str(e)

    return {"per_window": per_window, "summary": summary}


def holdout_window(start: str = HOLDOUT_START,
                   end: str | None = None) -> WalkWindow:
    """
    返回 holdout 评估窗口。train_* 字段设为 None 语义占位，
    使用者必须在 holdout 之前完成所有参数固化。
    """
    end_str = end or _fmt(date.today())
    return WalkWindow(
        train_start="",
        train_end="",
        test_start=start,
        test_end=end_str,
        label=f"HOLDOUT {start}~{end_str}",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for walk-forward or holdout evaluation modes."""
    import argparse
    import json

    ap = argparse.ArgumentParser(description="StockSage walk-forward / holdout runner")
    ap.add_argument("--mode", choices=("walk-forward", "holdout", "windows"),
                    default="walk-forward")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--train-days", type=int, default=365)
    ap.add_argument("--test-days", type=int, default=60)
    ap.add_argument("--step-days", type=int, default=60)
    ap.add_argument("--strategy", default="fixed_10d",
                    help="holdout 模式下使用的已固化策略名")
    args = ap.parse_args(argv)

    end = args.end or _fmt(date.today())
    if args.mode == "windows":
        data = [
            w.to_dict()
            for w in generate_windows(
                args.start, end, args.train_days, args.test_days, args.step_days
            )
        ]
    elif args.mode == "holdout":
        from backend.backtest.exit_logic_experiment import holdout_eval

        data = holdout_eval(
            holdout_start=args.start,
            holdout_end=end,
            chosen_strategy=args.strategy,
        )
    else:
        from backend.backtest.exit_logic_experiment import walk_forward_eval

        data = walk_forward_eval(
            start=args.start,
            end=end,
            train_days=args.train_days,
            test_days=args.test_days,
            step_days=args.step_days,
        )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
