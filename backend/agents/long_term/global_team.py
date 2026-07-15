"""Deterministic HK/US long-term gray labels using PIT-safe local evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.agents.long_term.base import LongTermLabel, VoteLabel
from backend.data.market_profiles import (
    instrument_key,
    normalize_market,
    normalize_symbol,
)


@dataclass(frozen=True)
class GlobalLongTermRule:
    quality_weight: float
    trend_weight: float
    version: str


_RULES = {
    "HK": GlobalLongTermRule(0.65, 0.35, "hk-long-m67-gray-v1"),
    "US": GlobalLongTermRule(0.50, 0.50, "us-long-m67-gray-v1"),
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _vote(score: float) -> VoteLabel:
    if score >= 45:
        return "值得持有"
    if score >= 25:
        return "估值偏高"
    if score >= -20:
        return "观望"
    return "规避"


def run_global_long_term(stock, db) -> LongTermLabel:
    """Build a non-constraining gray label from disclosed financials and closes."""
    from backend.data.database import FinancialMetric, Price

    market = normalize_market(stock.market)
    if market not in _RULES:
        raise ValueError("global long-term team supports HK/US only")
    symbol = normalize_symbol(stock.symbol, market)
    key = instrument_key(market, symbol)
    metrics = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.asset_key == key)
        .order_by(FinancialMetric.report_date.desc())
        .limit(8)
        .all()
    )
    prices = (
        db.query(Price.close)
        .filter(Price.asset_key == key)
        .order_by(Price.date.desc())
        .limit(130)
        .all()
    )

    quality_score = 0.0
    quality_findings: list[str] = []
    if metrics:
        latest = metrics[0]
        if latest.net_profit is not None:
            quality_score += 18 if latest.net_profit > 0 else -24
            quality_findings.append(f"最新披露净利润{'为正' if latest.net_profit > 0 else '为负'}")
        if latest.operating_cf is not None:
            quality_score += 14 if latest.operating_cf > 0 else -18
            quality_findings.append(f"经营现金流{'为正' if latest.operating_cf > 0 else '为负'}")
        if latest.revenue_yoy is not None:
            contribution = _clamp(float(latest.revenue_yoy), -30, 30) * 0.6
            quality_score += contribution
            quality_findings.append(f"披露口径收入同比 {latest.revenue_yoy:.1f}%")
        if latest.roe is not None:
            quality_score += _clamp(float(latest.roe), -15, 25) * 0.5
    else:
        quality_findings.append("缺少可验证披露日的财务数据")

    trend_score = 0.0
    trend_findings: list[str] = []
    closes = [float(row[0]) for row in prices if row[0]]
    for bars, weight in ((60, 0.55), (120, 0.45)):
        if len(closes) > bars and closes[bars] > 0:
            move = (closes[0] / closes[bars] - 1) * 100
            trend_score += _clamp(move, -40, 40) * weight
            trend_findings.append(f"近 {bars} 个交易日收盘收益 {move:.1f}%")
    if not trend_findings:
        trend_findings.append("价格历史不足 60 个交易日")

    rule = _RULES[market]
    score = round(
        _clamp(quality_score, -100, 100) * rule.quality_weight
        + _clamp(trend_score, -100, 100) * rule.trend_weight,
        1,
    )
    label = _vote(score)
    sufficient = len(metrics) >= 2 and len(closes) >= 121
    today = datetime.now(UTC).date()
    return LongTermLabel(
        symbol=symbol,
        market=market,
        date=today.isoformat(),
        label=label,
        score=score,
        votes={"disclosed_quality": _vote(quality_score), "market_trend": _vote(trend_score)},
        key_findings=(quality_findings[:2] + trend_findings[:2])[:4],
        expires_at=(today + timedelta(days=7)).isoformat(),
        quality="degraded" if not sufficient else "trusted",
        constraint_eligible=False,
        quality_notes=[
            "港美股灰度标签仅展示，不约束资金动作",
            f"rule_version={rule.version}",
            "财务数据仅使用已观测披露日的本地记录",
        ],
        prompt_version=rule.version,
    )
