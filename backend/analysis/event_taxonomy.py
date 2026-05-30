"""M27 A-share event taxonomy and event-aware sentiment scoring."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventType:
    code: str
    label: str
    polarity: int
    keywords: tuple[str, ...]


EVENT_TYPES: tuple[EventType, ...] = (
    EventType("major_contract", "大合同/中标订单", 1, ("中标", "签约", "大单", "订单", "合同")),
    EventType("regulatory_approval", "监管批文/产品获批", 1, ("获批", "批文", "注册证", "许可", "通过审评")),
    EventType("management_buyback", "增持/回购", 1, ("增持", "回购", "员工持股")),
    EventType("equity_incentive", "股权激励", 1, ("股权激励", "限制性股票", "期权激励")),
    EventType("index_inclusion", "指数纳入/调入", 1, ("纳入", "调入", "指数样本", "沪股通", "深股通")),
    EventType("earnings_beat", "业绩预增/超预期", 1, ("预增", "增长", "超预期", "扭亏", "盈利")),
    EventType("controller_reduction", "实控人/大股东减持", -1, ("减持", "套现", "被动减持")),
    EventType("regulatory_penalty", "监管处罚/立案调查", -1, ("处罚", "立案", "问询函", "警示函", "调查")),
    EventType("earnings_warning", "业绩预警/亏损", -1, ("预亏", "亏损", "下滑", "不及预期", "计提")),
    EventType("liquidity_stress", "流动性/债务压力", -1, ("违约", "债务", "冻结", "质押", "流动性")),
)
EVENT_TAXONOMY = EVENT_TYPES


def classify_events(events: list[str] | tuple[str, ...]) -> list[dict]:
    """Classify event strings into the local A-share taxonomy."""
    classified: list[dict] = []
    for event in events:
        text = str(event)
        for event_type in EVENT_TYPES:
            if any(keyword in text for keyword in event_type.keywords):
                classified.append({
                    "event": text,
                    "code": event_type.code,
                    "label": event_type.label,
                    "polarity": event_type.polarity,
                })
                break
    return classified


def classify_title_rules(title: str) -> list[dict[str, Any]]:
    """Classify one title with deterministic taxonomy rules."""
    return classify_events([title])


def classify_titles_rules(titles: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """Classify titles and deduplicate by event code."""
    by_code: dict[str, dict[str, Any]] = {}
    for item in classify_events(titles):
        by_code.setdefault(item["code"], item)
    return list(by_code.values())


def build_event_extraction_prompt(symbol: str | None, titles: list[str]) -> str:
    """Prompt helper for future LLM event extraction using this fixed taxonomy."""
    labels = "、".join(f"{event.code}={event.label}" for event in EVENT_TYPES)
    context = f"股票代码：{symbol}\n" if symbol else ""
    return (
        f"{context}请从以下A股新闻标题中抽取事件类型。可选事件：{labels}。\n"
        "返回 JSON：events=[{code,label,score,evidence}]，score 范围 -1 到 1。\n"
        + "\n".join(f"- {title}" for title in titles[:15])
    )


def event_score(sentiment: float, events: list[str] | tuple[str, ...]) -> dict:
    """Return an event-aware score in [-1, 1], falling back to sentiment when no event matches."""
    clipped_sentiment = max(-1.0, min(1.0, float(sentiment or 0.0)))
    classified = classify_events(events)
    if not classified:
        return {
            "event_score": clipped_sentiment,
            "event_score_mode": "sentiment_fallback",
            "event_types": [],
        }

    polarity_avg = sum(item["polarity"] for item in classified) / len(classified)
    score = 0.65 * polarity_avg + 0.35 * clipped_sentiment
    return {
        "event_score": round(max(-1.0, min(1.0, score)), 4),
        "event_score_mode": "event_override",
        "event_types": classified,
    }


def apply_event_score(sentiment_result: dict[str, Any], titles: list[str] | None = None) -> dict[str, Any]:
    """Add event-aware scoring to an analyze_news-style result."""
    out = dict(sentiment_result)
    event_texts: list[str] = []
    if titles:
        event_texts.extend(titles)
    event_texts.extend(str(item) for item in out.get("key_events", []) or [])
    out.update(event_score(float(out.get("sentiment") or 0.0), event_texts))
    return out
