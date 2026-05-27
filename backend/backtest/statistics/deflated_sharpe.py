"""
Deflated Sharpe Ratio（Bailey & López de Prado, 2014）

闭式公式参考 SSRN 2460551 第 3 节：

  DSR = Φ( (SR - SR_0) · √(T-1) / √(1 - γ3·SR + ((γ4-1)/4)·SR²) )

其中：
  SR    — 样本 Sharpe（与回测同年化）
  SR_0  — 期望最大 Sharpe（考虑试验次数 N 的"侥幸基线"）
  γ3    — 收益序列偏度
  γ4    — 收益序列峰度
  T     — 样本数（笔数 / 日数）
  Φ     — 标准正态 CDF

SR_0 的近似（Bailey & López de Prado, 2014 eq.5）：
  SR_0 ≈ √V · ((1 - γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)))

其中 γ ≈ 0.5772（Euler-Mascheroni），V 是各试验 Sharpe 序列的方差。
N 是试验次数（multiple testing 的 N）。

DSR 输出可解读为：
  • DSR ≥ 0.95 → 样本 Sharpe 极可能反映真实 alpha（5% 显著）
  • DSR ≥ 0.90 → 10% 显著
  • DSR < 0.50 → 几乎可断定为侥幸
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

EULER_MASCHERONI = 0.5772156649


@dataclass
class DSRResult:
    sharpe: float            # 原始样本 Sharpe（年化）
    sharpe_threshold: float  # 期望最大 Sharpe（SR_0）
    dsr: float               # 0~1 概率
    p_value: float           # 单尾 p-value = 1 - dsr
    n_trials: int            # 试验次数
    n_samples: int           # 样本数 T
    skew: float
    kurt: float              # 注意：传入的是峰度（不是超额峰度）
    note: str = ""

    def is_significant(self, alpha: float = 0.05) -> bool:
        """Return True if p_value is below the given significance threshold."""
        return self.p_value < alpha

    def to_dict(self) -> dict:
        """Serialize DSR result to dictionary."""
        return {
            "sharpe": round(self.sharpe, 4),
            "sharpe_threshold": round(self.sharpe_threshold, 4),
            "dsr": round(self.dsr, 4),
            "p_value": round(self.p_value, 4),
            "n_trials": self.n_trials,
            "n_samples": self.n_samples,
            "skew": round(self.skew, 4),
            "kurt": round(self.kurt, 4),
            "note": self.note,
        }


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_ppf(p: float) -> float:
    """标准正态分位数函数（逆 CDF）的有理逼近 — Beasley & Springer 1977."""
    if not (0.0 < p < 1.0):
        raise ValueError("p 必须在 (0,1) 开区间")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
           (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)


def _moments(returns: Sequence[float]) -> tuple[float, float, float, float]:
    """
    返回 (mean, std, skew, kurt) — kurt 是非超额峰度（正态=3）。

    M18.2 修复：使用样本标准差（除以 n-1）而非总体标准差（除以 n），
    与 DSR 论文假设一致（样本估计）。
    """
    n = len(returns)
    if n < 2:
        return 0.0, 0.0, 0.0, 3.0
    mean = sum(returns) / n
    diffs = [r - mean for r in returns]
    # 样本方差（无偏估计，除以 n-1）
    m2_sample = sum(d * d for d in diffs) / (n - 1)
    # 矩计算仍用总体公式（DSR 论文惯例）
    m2_pop = sum(d * d for d in diffs) / n
    if m2_pop <= 0:
        return mean, 0.0, 0.0, 3.0
    m3 = sum(d ** 3 for d in diffs) / n
    m4 = sum(d ** 4 for d in diffs) / n
    std = math.sqrt(m2_sample)   # 报告用样本 std
    std_pop = math.sqrt(m2_pop)  # 高阶矩归一化用总体 std（惯例）
    skew = m3 / (std_pop ** 3)
    kurt = m4 / (m2_pop * m2_pop)
    return mean, std, skew, kurt


def expected_max_sharpe(trial_sharpes: Sequence[float],
                        n_trials: int | None = None) -> float:
    """
    根据多次试验的 Sharpe 序列估计 SR_0（期望最大 Sharpe）。

    Bailey & López de Prado (2014) eq.5：
      SR_0 ≈ √V · [(1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))]

    其中 V 是 trial_sharpes 的方差（无偏估计），N 是试验次数。
    """
    n = n_trials if n_trials is not None else len(trial_sharpes)
    if n <= 1 or len(trial_sharpes) < 2:
        return 0.0
    mean = sum(trial_sharpes) / len(trial_sharpes)
    var = sum((s - mean) ** 2 for s in trial_sharpes) / (len(trial_sharpes) - 1)
    if var <= 0:
        return 0.0
    g = EULER_MASCHERONI
    term1 = _norm_ppf(1 - 1.0 / n)
    term2 = _norm_ppf(1 - 1.0 / (n * math.e))
    return math.sqrt(var) * ((1 - g) * term1 + g * term2)


def deflated_sharpe(
    returns: Sequence[float],
    trial_sharpes: Sequence[float],
    sharpe_observed: float | None = None,
    n_trials: int | None = None,
    periods_per_year: int = 252,
) -> DSRResult:
    """
    主入口：给一段收益序列 + 试验池里所有 Sharpe，返回 DSR + p-value。

    returns        — 入选策略的收益序列（每笔/每日）
    trial_sharpes  — 参数扫描中所有方案的 Sharpe（含入选）
    sharpe_observed — 不传则自动从 returns 算（年化）
    n_trials       — 默认 len(trial_sharpes)，可显式覆盖（如总扫描数>序列数）
    """
    n_t = n_trials if n_trials is not None else len(trial_sharpes)
    n_obs = len(returns)
    mean, std, skew, kurt = _moments(returns)

    if sharpe_observed is None:
        sharpe_observed = (mean / std * math.sqrt(periods_per_year)) if std > 0 else 0.0

    sr0 = expected_max_sharpe(trial_sharpes, n_trials=n_t)

    if n_obs < 2:
        return DSRResult(
            sharpe=sharpe_observed, sharpe_threshold=sr0, dsr=0.0, p_value=1.0,
            n_trials=n_t, n_samples=n_obs, skew=skew, kurt=kurt,
            note="样本量不足",
        )
    # M18.1：强制 ≥30 笔最小样本门槛，样本不足时 DSR 无统计意义
    if n_obs < 30:
        return DSRResult(
            sharpe=sharpe_observed, sharpe_threshold=sr0, dsr=0.0, p_value=1.0,
            n_trials=n_t, n_samples=n_obs, skew=skew, kurt=kurt,
            note=f"样本量 {n_obs} < 30，DSR 不可靠，建议收集更多交易",
        )

    # 把 sr0（多试验下年化 Sharpe）转回 returns 同尺度做对比
    sr_obs_period = sharpe_observed / math.sqrt(periods_per_year)
    sr0_period = sr0 / math.sqrt(periods_per_year)

    denom = 1 - skew * sr_obs_period + ((kurt - 1) / 4) * (sr_obs_period ** 2)
    if denom <= 0:
        return DSRResult(
            sharpe=sharpe_observed, sharpe_threshold=sr0, dsr=0.0, p_value=1.0,
            n_trials=n_t, n_samples=n_obs, skew=skew, kurt=kurt,
            note="DSR 分母非正，偏度/峰度组合极端",
        )

    z = (sr_obs_period - sr0_period) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    dsr = _norm_cdf(z)
    return DSRResult(
        sharpe=sharpe_observed,
        sharpe_threshold=sr0,
        dsr=dsr,
        p_value=1 - dsr,
        n_trials=n_t,
        n_samples=n_obs,
        skew=skew,
        kurt=kurt,
    )
