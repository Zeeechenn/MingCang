"""
Probability of Backtest Overfitting（PBO，Bailey & López de Prado, 2014）

通过 Combinatorially Symmetric Cross-Validation (CSCV)：
  • 把 T 个时间点切成 S 个等长块
  • 取 S/2 块组合作为 IS，剩余作为 OOS
  • 对所有 C(S, S/2) 组合：找 IS 上最优策略 i*，看其在 OOS 上的相对排名
  • PBO = (OOS 相对排名 ≤ 中位数) 的频率

输入：T×N 矩阵（时间 × 策略数），每格是该策略在该时点的收益。
输出：PBO（0-1，越低越好；> 0.5 视为高度过拟合）。
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence


@dataclass
class PBOResult:
    pbo: float
    n_splits: int        # 实际评估的 IS/OOS 切分数
    n_trials: int        # 策略数 N
    n_blocks: int        # 切分块数 S
    note: str = ""

    def to_dict(self) -> dict:
        """Serialize PBO result to dictionary."""
        return {
            "pbo": round(self.pbo, 4),
            "n_splits": self.n_splits,
            "n_trials": self.n_trials,
            "n_blocks": self.n_blocks,
            "note": self.note,
        }


def _split_blocks(matrix: list[list[float]], n_blocks: int) -> list[list[list[float]]]:
    """把 T 行切成 n_blocks 个等长块，丢弃尾部余数。"""
    t = len(matrix)
    block_size = t // n_blocks
    if block_size == 0:
        return []
    blocks = []
    for i in range(n_blocks):
        start = i * block_size
        end = start + block_size
        blocks.append(matrix[start:end])
    return blocks


def _sharpe_by_strategy(block: list[list[float]]) -> list[float]:
    """单块内每个策略的 Sharpe（与年化无关，相对排名用即可）。"""
    if not block:
        return []
    n_strat = len(block[0])
    out = []
    for j in range(n_strat):
        col = [row[j] for row in block]
        n = len(col)
        if n < 2:
            out.append(0.0)
            continue
        mean = sum(col) / n
        var = sum((x - mean) ** 2 for x in col) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        out.append(mean / std if std > 0 else 0.0)
    return out


def pbo(returns_matrix: Sequence[Sequence[float]], n_blocks: int = 16) -> PBOResult:
    """
    returns_matrix: T × N（行=时间，列=策略）。N ≥ 2，T ≥ n_blocks × 2。
    """
    matrix = [list(row) for row in returns_matrix]
    t = len(matrix)
    if t == 0:
        return PBOResult(pbo=0.0, n_splits=0, n_trials=0, n_blocks=n_blocks,
                         note="空矩阵")
    n_trials = len(matrix[0])
    if n_trials < 2:
        return PBOResult(pbo=0.0, n_splits=0, n_trials=n_trials, n_blocks=n_blocks,
                         note="至少需要 2 个策略")

    # 自动收缩 n_blocks（保证块数为偶数，且每块至少 2 行）
    max_blocks = (t // 2)
    if max_blocks % 2 == 1:
        max_blocks -= 1
    n_blocks = min(n_blocks, max_blocks)
    if n_blocks < 2 or n_blocks % 2 == 1:
        return PBOResult(pbo=0.0, n_splits=0, n_trials=n_trials, n_blocks=n_blocks,
                         note=f"切分块数不足：T={t}, n_blocks={n_blocks}")

    blocks = _split_blocks(matrix, n_blocks)
    half = n_blocks // 2
    block_indices = list(range(n_blocks))

    overfit_count = 0
    total = 0
    # 限制 IS 组合数避免组合爆炸
    is_combos = list(combinations(block_indices, half))
    max_combos = 1000
    if len(is_combos) > max_combos:
        step = len(is_combos) // max_combos
        is_combos = is_combos[::step][:max_combos]

    for is_idx_tuple in is_combos:
        is_set = set(is_idx_tuple)
        is_rows: list[list[float]] = []
        oos_rows: list[list[float]] = []
        for i, blk in enumerate(blocks):
            (is_rows if i in is_set else oos_rows).extend(blk)
        is_sharpes = _sharpe_by_strategy(is_rows)
        oos_sharpes = _sharpe_by_strategy(oos_rows)
        if not is_sharpes or not oos_sharpes:
            continue
        best_in = max(range(n_trials), key=lambda j: is_sharpes[j])
        sorted_oos = sorted(oos_sharpes)
        rank = sorted_oos.index(oos_sharpes[best_in])
        relative = (rank + 1) / n_trials  # 1=最好，0=最差
        if relative <= 0.5:
            overfit_count += 1
        total += 1

    if total == 0:
        return PBOResult(pbo=0.0, n_splits=0, n_trials=n_trials, n_blocks=n_blocks,
                         note="无有效切分")
    return PBOResult(
        pbo=overfit_count / total,
        n_splits=total,
        n_trials=n_trials,
        n_blocks=n_blocks,
    )
