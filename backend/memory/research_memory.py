"""Helpers for storing deep-research artifacts in AI memory.

M15.3 候选记忆质量订正：以往按关键词命中把同一段 clipped_summary 重复写入
thesis / risk / event 三类条目，导致 N×4 近重复行且"风险"条目并不含真实风险点。
现在每个 symbol 只写一行 research_pointer 作为索引；真正的 thesis / risk /
event 需 LLM 结构化输出独立字段后再写，本模块不再生成 candidate 噪声。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.memory.ai_memory import remember


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
        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
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
