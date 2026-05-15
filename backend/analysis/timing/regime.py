"""
市场环境聚合层 — 把 RSRS + 扩散指标的结论合成一个 regime 标签。
被 aggregator 在算综合分之前调用，对"逆风信号"做衰减。
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd

from backend.analysis.timing.rsrs import latest_rsrs_z
from backend.analysis.timing.diffusion import sector_diffusion
from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RegimeReport:
    """市场环境快照（注入到 aggregator + LLM prompt）"""
    rsrs_z: float | None
    diffusion: float | None
    market_bullish: bool
    market_bearish: bool
    sector_strong: bool
    sector_weak: bool
    dampen_score: bool        # 是否衰减综合分
    reason: str

    def to_dict(self) -> dict:
        """Serialize regime report to dictionary."""
        return {
            "rsrs_z": round(self.rsrs_z, 3) if self.rsrs_z is not None else None,
            "diffusion": round(self.diffusion, 3) if self.diffusion is not None else None,
            "market_bullish": self.market_bullish,
            "market_bearish": self.market_bearish,
            "sector_strong": self.sector_strong,
            "sector_weak": self.sector_weak,
            "dampen_score": self.dampen_score,
            "reason": self.reason,
        }


def market_regime(
    index_df: pd.DataFrame | None,
    sector_price_dfs: dict[str, pd.DataFrame] | None = None,
) -> RegimeReport:
    """
    计算当前市场+板块环境。
    index_df: 沪深300 OHLC（至少含 high/low/close）
    sector_price_dfs: 板块成分股 {symbol: df}（可选；缺失视为中性）
    """
    rsrs_z = None
    if index_df is not None and len(index_df) >= settings.rsrs_window + 20:
        rsrs_z = latest_rsrs_z(index_df, window=settings.rsrs_window,
                               zscore_lookback=settings.rsrs_lookback)

    diff = sector_diffusion(sector_price_dfs) if sector_price_dfs else None

    market_bullish = rsrs_z is not None and rsrs_z > 0.7
    market_bearish = rsrs_z is not None and rsrs_z < settings.rsrs_bearish_z
    sector_strong = diff is not None and diff > 0.6
    sector_weak = diff is not None and diff < settings.diffusion_threshold

    dampen = market_bearish or sector_weak
    reasons = []
    if market_bearish:
        reasons.append(f"RSRS看空(z={rsrs_z:.2f})")
    if sector_weak:
        reasons.append(f"板块扩散弱({diff:.2f})")
    if not reasons:
        if market_bullish:
            reasons.append("大盘强势")
        if sector_strong:
            reasons.append("板块扩散强")
        if not reasons:
            reasons.append("中性")

    return RegimeReport(
        rsrs_z=rsrs_z,
        diffusion=diff,
        market_bullish=market_bullish,
        market_bearish=market_bearish,
        sector_strong=sector_strong,
        sector_weak=sector_weak,
        dampen_score=dampen,
        reason=" + ".join(reasons),
    )


def apply_regime_filter(composite_score: float, regime: RegimeReport) -> tuple[float, bool]:
    """
    根据 regime 衰减综合分。返回 (新分, 是否触发衰减)。
    """
    if not settings.regime_filter_enabled:
        return composite_score, False
    if regime.dampen_score and composite_score > 0:
        return round(composite_score * settings.regime_dampen_factor, 1), True
    return composite_score, False
