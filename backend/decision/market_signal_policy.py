"""Market-specific gray signal calibration and execution isolation."""

from __future__ import annotations

from dataclasses import dataclass

from backend.analysis.factors import calc_stop_take
from backend.data.market_profiles import normalize_market


@dataclass(frozen=True)
class GraySignalPolicy:
    market: str
    quant_weight: float
    technical_weight: float
    sentiment_weight: float
    entry_threshold: float
    watch_threshold: float
    avoid_threshold: float
    atr_multiplier: float
    risk_reward_ratio: float
    version: str


_GRAY_POLICIES = {
    "HK": GraySignalPolicy(
        market="HK",
        quant_weight=0.0,
        technical_weight=0.65,
        sentiment_weight=0.35,
        entry_threshold=32.0,
        watch_threshold=6.0,
        avoid_threshold=-24.0,
        atr_multiplier=2.5,
        risk_reward_ratio=1.8,
        version="hk-m67-gray-v2",
    ),
    "US": GraySignalPolicy(
        market="US",
        quant_weight=0.0,
        technical_weight=0.75,
        sentiment_weight=0.25,
        entry_threshold=36.0,
        watch_threshold=8.0,
        avoid_threshold=-28.0,
        atr_multiplier=2.75,
        risk_reward_ratio=2.0,
        version="us-m67-gray-v2",
    ),
}


def gray_signal_policy(market: str) -> GraySignalPolicy:
    normalized = normalize_market(market)
    if normalized not in _GRAY_POLICIES:
        raise ValueError(f"{normalized} uses the existing production signal policy")
    return _GRAY_POLICIES[normalized]


def _recommendation(score: float, policy: GraySignalPolicy) -> str:
    if score > policy.entry_threshold:
        return "可小仓试错"
    if score > policy.watch_threshold:
        return "可关注"
    if score > policy.avoid_threshold:
        return "观望"
    return "规避"


def _confidence(score: float) -> str:
    magnitude = abs(score)
    if magnitude >= 60:
        return "高"
    if magnitude >= 30:
        return "中"
    return "低"


def apply_market_signal_policy(
    result: dict,
    *,
    market: str,
    close: float,
    atr: float,
) -> dict:
    """Apply market calibration and force HK/US gray outputs to shadow-only."""
    normalized = normalize_market(market)
    if normalized == "CN":
        result["execution_mode"] = "production_research"
        result["market_rule_version"] = "cn-current"
        return result

    policy = gray_signal_policy(normalized)
    breakdown = result.get("breakdown", {})
    score = (
        float(breakdown.get("quant") or 0.0) * policy.quant_weight
        + float(breakdown.get("technical") or 0.0) * policy.technical_weight
        + float(breakdown.get("sentiment") or 0.0) * policy.sentiment_weight
    )
    score = round(max(-100.0, min(100.0, score)), 1)
    stop_loss, take_profit = calc_stop_take(
        close,
        atr,
        atr_mult=policy.atr_multiplier,
        rr=policy.risk_reward_ratio,
    )
    model_position_pct = float(result.get("position_pct") or 0.0)
    result.update({
        "composite_score": score,
        "recommendation": _recommendation(score, policy),
        "confidence": _confidence(score),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "model_position_pct": model_position_pct,
        "position_pct": 0.0,
        "execution_mode": "gray_shadow_only",
        "market_rule_version": policy.version,
        "rule_version": f"{result.get('rule_version', 'aggregate')}:{policy.version}",
        "market_policy": {
            "weights": {
                "quant": policy.quant_weight,
                "technical": policy.technical_weight,
                "sentiment": policy.sentiment_weight,
            },
            "entry_threshold": policy.entry_threshold,
            "atr_multiplier": policy.atr_multiplier,
            "risk_reward_ratio": policy.risk_reward_ratio,
            "execution_mode": "gray_shadow_only",
        },
    })
    return result
