"""
分析师团 — 把原本散在 aggregator 里的"打分逻辑"包装成可解释的结构化报告。
每个分析师输出 (score, confidence, key_findings, raw)，让 Trader 能引用。
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import pandas as pd


@dataclass
class AnalystReport:
    role: str
    score: float            # -100 ~ +100
    confidence: float       # 0 ~ 1
    key_findings: list[str] # 给 LLM/用户看的关键发现，≤3 条
    raw: dict               # 原始数据（debug 用）

    def to_dict(self) -> dict:
        """Serialize report to dictionary."""
        return asdict(self)


def technical_analyst(tech_result: dict) -> AnalystReport:
    """包装 technical_score 输出"""
    score = tech_result.get("score", 0.0)
    raw_score = tech_result.get("raw_score", score)
    adx_factor = tech_result.get("adx_factor", 1.0)
    latest = tech_result.get("latest", {}) or {}
    findings = []
    rsi = latest.get("rsi14")
    if rsi is not None:
        if rsi > 70:
            findings.append(f"RSI={rsi:.1f} 超买")
        elif rsi < 30:
            findings.append(f"RSI={rsi:.1f} 超卖")
    adx = latest.get("adx14")
    if adx is not None and adx < 20:
        findings.append(f"ADX={adx:.1f} 震荡市（信号衰减50%）")
    if abs(raw_score - score) > 1:
        findings.append(f"ADX 过滤后 {raw_score:.0f}→{score:.0f}")
    limit = tech_result.get("limit", {}) or {}
    if limit.get("limit_up"):
        findings.append("今日涨停，买入难成交")
    if limit.get("limit_down"):
        findings.append("今日跌停，止损不可执行")

    confidence = min(1.0, abs(score) / 60)
    return AnalystReport(
        role="technical",
        score=round(score, 1),
        confidence=round(confidence, 2),
        key_findings=findings[:3],
        raw={"raw_score": raw_score, "adx_factor": adx_factor, "latest": latest},
    )


def quant_analyst(qlib_result: dict) -> AnalystReport:
    """包装 qlib_score 输出（模型未训练时 fallback 为动量）"""
    score = qlib_result.get("score", 0.0)
    model = qlib_result.get("model", "?")
    findings = [f"模型={model}"]
    raw_pred = qlib_result.get("raw_pred")
    if raw_pred is not None:
        findings.append(f"原始预测{raw_pred:+.2%} 未来5日")
    confidence = 0.6 if "lgbm" in str(model) else 0.3   # placeholder 模型置信度低
    return AnalystReport(
        role="quant",
        score=round(score, 1),
        confidence=confidence,
        key_findings=findings,
        raw=qlib_result,
    )


def sentiment_analyst(sentiment_result: dict) -> AnalystReport:
    """包装新闻情感"""
    raw_sentiment = sentiment_result.get("sentiment", 0.0)  # -1 ~ +1
    score = raw_sentiment * 100
    impact = sentiment_result.get("impact", "short")
    summary = sentiment_result.get("summary", "")
    findings = []
    if summary:
        findings.append(summary[:40])
    findings.append(f"影响周期: {impact}")
    confidence = min(1.0, abs(raw_sentiment) * 1.2)
    return AnalystReport(
        role="sentiment",
        score=round(score, 1),
        confidence=round(confidence, 2),
        key_findings=findings[:3],
        raw=sentiment_result,
    )


def news_analyst(sentiment_result: dict) -> AnalystReport:
    """从情感结果中提取 key_events，专注事件影响"""
    events = sentiment_result.get("key_events", []) or []
    score = 0.0
    pos_kw = ("利好", "上调", "增长", "突破", "签约", "中标", "回购")
    neg_kw = ("利空", "下调", "暴跌", "亏损", "处罚", "退市", "减持")
    for e in events:
        if any(k in e for k in pos_kw):
            score += 20
        if any(k in e for k in neg_kw):
            score -= 20
    score = max(-100, min(100, score))
    return AnalystReport(
        role="news",
        score=round(score, 1),
        confidence=0.5 if events else 0.1,
        key_findings=events[:3] or ["无关键事件"],
        raw={"events": events},
    )
