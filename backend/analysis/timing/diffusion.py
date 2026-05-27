"""
扩散指标 — 简化版板块/股票池择时
参考：东北证券 20190924 研报。

原版基于板块成分股，本实现简化为"自选股池中价格在 MA20 上方的占比"。

M20.2 阈值说明（可通过 settings 调整）：
  • 强势阈值：diffusion > settings.diffusion_strong_threshold（默认 0.6）
  • 弱势阈值：diffusion < settings.diffusion_threshold（默认 0.3）
  • 此处 sector_diffusion() 只做计算；阈值判断在 regime.py 的 market_regime() 中完成。
"""
from __future__ import annotations

import pandas as pd


def sector_diffusion(price_dfs: dict[str, pd.DataFrame], ma_window: int = 20) -> float | None:
    """
    输入 {symbol: 含 close 列的 DataFrame}，输出 [0, 1] 的扩散值。
    扩散值 = (收盘价 > MA{ma_window} 的股票数) / 总数。
    任一股票数据不足返回 None。
    """
    if not price_dfs:
        return None

    above = 0
    total = 0
    for _, df in price_dfs.items():
        if len(df) < ma_window:
            continue
        ma = df["close"].rolling(ma_window).mean().iloc[-1]
        last_close = df["close"].iloc[-1]
        if pd.isna(ma):
            continue
        total += 1
        if last_close > ma:
            above += 1

    if total == 0:
        return None
    return above / total
