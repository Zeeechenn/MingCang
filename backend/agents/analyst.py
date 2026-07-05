"""[M63 现役] [active] 消费者: backend/agents/director.py, backend/agents/pipeline.py, backend/agents/researcher.py, backend/agents/trader.py, backend/decision/aggregator.py.
分析师团 — 把原本散在 aggregator 里的"打分逻辑"包装成可解释的结构化报告。
每个分析师输出 (score, confidence, key_findings, raw)，让 Trader 能引用。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


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
    raw_sentiment = sentiment_result.get("event_score", sentiment_result.get("sentiment", 0.0))  # -1 ~ +1
    score = raw_sentiment * 100
    impact = sentiment_result.get("impact", "short")
    summary = sentiment_result.get("summary", "")
    findings = []
    if summary:
        findings.append(summary[:40])
    mode = sentiment_result.get("event_score_mode")
    if mode == "event_override":
        findings.append("事件化情感: 已覆盖极性分")
    findings.append(f"影响周期: {impact}")
    confidence = min(1.0, abs(raw_sentiment) * 1.2)
    return AnalystReport(
        role="sentiment",
        score=round(score, 1),
        confidence=round(confidence, 2),
        key_findings=findings[:3],
        raw=sentiment_result,
    )


_NEWS_POS_KW = (
    "利好", "上调", "增长", "突破", "签约", "中标", "回购",
    "新高", "上涨", "看好", "净流入", "增持", "扩产",
    "订单", "超预期", "强势", "受益", "买入评级", "涨",
)
_NEWS_NEG_KW = (
    "利空", "下调", "暴跌", "亏损", "处罚", "退市", "减持",
    "新低", "下跌", "看空", "净流出", "套现", "立案", "踩雷",
    "违约", "暴雷", "差于预期", "弱于", "跌",
)


def news_analyst(sentiment_result: dict) -> AnalystReport:
    """
    事件驱动分析师（M4.7 修复）。

    设计：
      • 无 key_events → score=0, confidence=0.1（不能给方向）
      • 有 events → 用 LLM sentiment (-1~+1) × 80 作基线
                   + 关键词命中每条 ±10 作微调
                   → 总分截到 ±100
      • 关键词列表大幅扩充，覆盖 A 股常见新闻语料（新高/新低、净流入/出、订单等）

    与 sentiment_analyst 的区别：
      • sentiment_analyst = 纯 sentiment × 100（连续，方向）
      • news_analyst    = events-gated（事件触发） + 关键词强化（事件强度）
      • 无事件时 news_analyst 归零，避免重复加权 sentiment 信号
    """
    events = sentiment_result.get("key_events", []) or []
    if not events:
        return AnalystReport(
            role="news",
            score=0.0,
            confidence=0.1,
            key_findings=["无关键事件"],
            raw={"events": []},
        )

    overall_sent = sentiment_result.get("event_score", sentiment_result.get("sentiment", 0.0)) or 0.0
    base = overall_sent * 80      # ±80 留 ±20 给关键词

    bonus = 0
    for e in events:
        if any(k in e for k in _NEWS_POS_KW):
            bonus += 10
        if any(k in e for k in _NEWS_NEG_KW):
            bonus -= 10

    score = max(-100.0, min(100.0, base + bonus))
    confidence = min(1.0, abs(score) / 60)

    return AnalystReport(
        role="news",
        score=round(score, 1),
        confidence=round(confidence, 2),
        key_findings=events[:3],
        raw={
            "events": events,
            "event_types": sentiment_result.get("event_types", []),
            "event_score_mode": sentiment_result.get("event_score_mode"),
            "base_from_sentiment": round(base, 1),
            "keyword_bonus": bonus,
        },
    )
