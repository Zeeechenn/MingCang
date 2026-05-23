"""
技术分析信号生成，输出 -100 ~ +100 的得分
阶段B 升级：MA → ICU EMA；ADX 震荡市过滤；可选项通过 settings 切换。
"""
import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.config import settings

_MAIN_BOARD_LIMIT_THRESHOLD = 9.5  # 主板涨跌停实际触发阈值（名义10%，实际约9.5%）


def _limit_threshold(symbol: str | None = None) -> float:
    """Return A-share limit threshold by board prefix."""
    if not symbol:
        return _MAIN_BOARD_LIMIT_THRESHOLD
    code = str(symbol).strip()
    if code.startswith(("300", "301", "688", "689")):
        return 19.5
    if code.startswith(("8", "4")):
        return 29.5
    return _MAIN_BOARD_LIMIT_THRESHOLD


def score_trend(df: pd.DataFrame) -> float:
    """
    趋势信号：阶段B 切换到 ICU EMA（13/26）。
    ICU 比 MA20/60 对趋势启动更敏感，对震荡市靠 ADX 单独过滤。
    """
    last = df.iloc[-1]
    fast = last.get("icu_fast", last.get("ma20"))
    slow = last.get("icu_slow", last.get("ma60"))
    close = last["close"]
    if pd.isna(fast) or pd.isna(slow):
        return 0.0
    if fast > slow and close > fast:
        return 1.0
    if fast < slow and close < fast:
        return -1.0
    return 0.0


def adx_filter_factor(df: pd.DataFrame) -> float:
    """
    ADX 过滤系数：震荡市（ADX < threshold）时返回 0.5，强趋势返回 1.0。
    被 technical_score 最终乘上去。
    """
    if not settings.adx_filter_enabled:
        return 1.0
    if "adx14" not in df.columns:
        return 1.0
    last_adx = df["adx14"].iloc[-1]
    if pd.isna(last_adx):
        return 1.0
    if last_adx < settings.adx_threshold:
        return 0.5
    if last_adx > 40:
        return 1.0
    return 0.75 + (last_adx - settings.adx_threshold) / (40 - settings.adx_threshold) * 0.25


def score_rsi(df: pd.DataFrame) -> float:
    """RSI 超买超卖：RSI<30 视为反弹信号；RSI>70 只提示风险，不直接给卖出分。"""
    rsi = df["rsi14"].iloc[-1]
    if rsi < 30:
        return 1.0
    if rsi > 70:
        return 0.0
    # 中性区间线性插值
    return (50 - rsi) / 20.0


def score_macd(df: pd.DataFrame) -> float:
    """MACD 金叉/死叉"""
    hist = df["macd_hist"]
    if len(hist) < 2:
        return 0.0
    if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
        return 1.0   # 金叉
    if hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
        return -1.0  # 死叉
    return 0.3 if hist.iloc[-1] > 0 else -0.3


def score_volume(df: pd.DataFrame) -> float:
    """成交量确认：近5日均量对比20日均量"""
    vol5 = df["volume"].iloc[-5:].mean()
    vol20 = df["volume"].iloc[-20:].mean()
    ratio = vol5 / vol20 if vol20 > 0 else 1.0
    trend_score = score_trend(df)
    # 放量上涨/缩量下跌为正，放量下跌/缩量上涨为负
    if ratio > 1.2:
        return trend_score * 0.5
    return 0.0


def check_limit_status(df: pd.DataFrame, market: str = "CN", symbol: str | None = None) -> dict:
    """
    检测A股涨跌停状态。
    limit_down 时止损信号不可当日执行（T+1 + 跌停无买盘）。
    """
    if market != "CN" or len(df) < 2:
        return {"status": "normal", "limit_up": False, "limit_down": False,
                "change_pct": 0.0, "stop_loss_executable": True}

    prev_close = df.iloc[-2]["close"]
    curr_close = df.iloc[-1]["close"]
    if prev_close == 0:
        return {"status": "normal", "limit_up": False, "limit_down": False,
                "change_pct": 0.0, "stop_loss_executable": True}

    change_pct = (curr_close - prev_close) / prev_close * 100
    threshold = _limit_threshold(symbol)
    limit_up = bool(change_pct >= threshold)
    limit_down = bool(change_pct <= -threshold)

    return {
        "status": "limit_up" if limit_up else ("limit_down" if limit_down else "normal"),
        "limit_up": limit_up,
        "limit_down": limit_down,
        "change_pct": round(change_pct, 2),
        "stop_loss_executable": not limit_down,  # 跌停时无法止损
    }


def technical_score(df_raw: pd.DataFrame, market: str = "CN", symbol: str | None = None) -> dict:
    """
    输入原始 OHLCV DataFrame，返回技术分析结果。
    阶段B 升级：综合分乘以 ADX 过滤系数（震荡市衰减 50%）。
    """
    df = add_all_factors(df_raw)
    scores = {
        "trend": score_trend(df),
        "rsi": score_rsi(df),
        "macd": score_macd(df),
        "volume": score_volume(df),
    }
    weights = {"trend": 0.4, "rsi": 0.25, "macd": 0.25, "volume": 0.1}
    raw_composite = sum(scores[k] * weights[k] for k in scores) * 100

    adx_factor = adx_filter_factor(df)
    composite = raw_composite * adx_factor

    last = df.iloc[-1]
    limit = check_limit_status(df, market, symbol=symbol)
    return {
        "score": round(composite, 1),
        "raw_score": round(raw_composite, 1),
        "adx_factor": round(adx_factor, 2),
        "components": scores,
        "limit": limit,
        "latest": {
            "close": last["close"],
            "rsi14": round(last["rsi14"], 1) if not pd.isna(last["rsi14"]) else None,
            "ma20": round(last["ma20"], 3) if not pd.isna(last["ma20"]) else None,
            "ma60": round(last["ma60"], 3) if not pd.isna(last["ma60"]) else None,
            "atr14": round(last["atr14"], 3) if not pd.isna(last["atr14"]) else None,
            "adx14": round(last["adx14"], 1) if "adx14" in df.columns and not pd.isna(last["adx14"]) else None,
        },
    }
