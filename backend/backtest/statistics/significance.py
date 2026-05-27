"""
IC 显著性 / t-stat / 标准误（替代裸 IC 阈值判定）

阶段A 当时的判定："IC=0.0228 < 阈值 0.03 → Qlib 不合格" 缺统计严肃性。
按 N 修正后，IC 标准误 ≈ 1/√N，t 值 = IC × √N。

例如 N=12797 时：
  • IC=0.0228 的 t ≈ 2.58 → 双尾 p ≈ 0.01（显著）
  • 简单阈值 0.03 没有统计意义
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ICSignificance:
    ic: float
    n: int
    std_err: float
    t_stat: float
    p_value_two_sided: float

    def is_significant(self, alpha: float = 0.05) -> bool:
        """Return True if the two-sided p-value is below alpha."""
        return self.p_value_two_sided < alpha

    def verdict(self) -> str:
        """Return a human-readable significance verdict string."""
        if self.p_value_two_sided < 0.01:
            return "极显著"
        if self.p_value_two_sided < 0.05:
            return "显著"
        if self.p_value_two_sided < 0.10:
            return "边际显著"
        return "不显著"

    def to_dict(self) -> dict:
        """Serialize IC significance result to dictionary."""
        return {
            "ic": round(self.ic, 4),
            "n": self.n,
            "std_err": round(self.std_err, 4),
            "t_stat": round(self.t_stat, 4),
            "p_value_two_sided": round(self.p_value_two_sided, 6),
            "verdict": self.verdict(),
        }


def _norm_sf(x: float) -> float:
    """Standard normal survival function (1 - CDF)."""
    return 0.5 * math.erfc(x / math.sqrt(2))


def ic_significance(ic: float, n: int) -> ICSignificance:
    """
    给定样本 IC 与样本数 N，返回标准误 + t 统计量 + 双尾 p。

    在大样本下 (N>30) 用正态近似：t ≈ IC × √N，std_err = 1/√N。

    【M18.1 局限性说明】
    标准误公式 1/√N 假设每个 IC 观测独立同分布（IID）。
    若 IC 基于滚动窗口收益（相邻期重叠），则样本存在序列相关，
    实际有效样本数 < N，t-stat 会被高估。
    严格场景请使用 Newey-West 修正标准误或 Hansen-Hodrick 调整。
    """
    if n < 2:
        return ICSignificance(ic=ic, n=n, std_err=float("inf"),
                              t_stat=0.0, p_value_two_sided=1.0)
    std_err = 1.0 / math.sqrt(n)
    t_stat = ic / std_err
    p_two = 2 * _norm_sf(abs(t_stat))
    return ICSignificance(
        ic=ic, n=n, std_err=std_err, t_stat=t_stat,
        p_value_two_sided=min(1.0, p_two),
    )
