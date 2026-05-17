"""Helpers for storing deep-research artifacts in AI memory."""
from __future__ import annotations

import json
from datetime import datetime

from backend.memory.ai_memory import remember


def remember_deep_research(
    db,
    *,
    topic: str,
    summary: str,
    symbols: list[str],
    report_path: str,
) -> None:
    """Store a structured pointer to a deep-research report."""
    payload = {
        "topic": topic,
        "summary": summary,
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
