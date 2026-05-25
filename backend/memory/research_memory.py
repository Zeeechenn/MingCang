"""Helpers for storing deep-research artifacts in AI memory."""
from __future__ import annotations

import json
from datetime import datetime

from backend.memory.ai_memory import remember

_RISK_HINTS = ("风险", "不确定", "估值", "拥挤", "压力", "回撤")
_EVENT_HINTS = ("事件", "公告", "政策", "订单", "业绩", "涨价", "新品")


def _summary_clip(summary: str, limit: int = 220) -> str:
    text = summary.strip()
    return text if len(text) <= limit else text[:limit] + "..."


def remember_deep_research(
    db,
    *,
    topic: str,
    summary: str,
    symbols: list[str],
    report_path: str,
) -> None:
    """Store a structured pointer to a deep-research report."""
    from backend.memory.stock_memory import create_stock_memory

    clipped_summary = _summary_clip(summary)
    payload = {
        "topic": topic,
        "summary": clipped_summary,
        "symbols": symbols,
        "report_path": report_path,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    remember(
        db,
        f"deep_research:{topic}",
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        category="deep_research",
        scope="research",
    )
    for symbol in symbols:
        pointer_summary = f"{symbol} 研究索引：{clipped_summary}"
        base_evidence = {
            "topic": topic,
            "symbol": symbol,
            "symbols": symbols,
            "report_path": report_path,
            "dossier_role": "deep_research",
        }
        create_stock_memory(
            db,
            symbol=symbol,
            memory_type="research_pointer",
            summary=pointer_summary,
            evidence={**base_evidence, "constraint_type": "research_pointer"},
            source_type="deep_research",
            source_ref=f"{report_path}#research:{symbol}",
            importance=3,
            confidence=0.7,
        )
        create_stock_memory(
            db,
            symbol=symbol,
            memory_type="thesis",
            summary=f"{symbol} {topic} 深度研究候选结论：{clipped_summary}",
            evidence={**base_evidence, "constraint_type": "thesis"},
            source_type="deep_research_candidate",
            source_ref=f"{report_path}#thesis:{symbol}",
            importance=3,
            confidence=0.6,
            status="watching",
        )
        if any(hint in clipped_summary for hint in _RISK_HINTS):
            create_stock_memory(
                db,
                symbol=symbol,
                memory_type="risk",
                summary=f"{symbol} {topic} 深度研究候选风险：{clipped_summary}",
                evidence={**base_evidence, "constraint_type": "risk"},
                source_type="deep_research_candidate",
                source_ref=f"{report_path}#risk:{symbol}",
                importance=3,
                confidence=0.6,
                status="watching",
            )
        if any(hint in clipped_summary for hint in _EVENT_HINTS):
            create_stock_memory(
                db,
                symbol=symbol,
                memory_type="event",
                summary=f"{symbol} {topic} 深度研究候选事件：{clipped_summary}",
                evidence={**base_evidence, "constraint_type": "event"},
                source_type="deep_research_candidate",
                source_ref=f"{report_path}#event:{symbol}",
                importance=2,
                confidence=0.5,
                status="watching",
            )
