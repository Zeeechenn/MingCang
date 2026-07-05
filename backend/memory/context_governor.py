"""M57 deterministic context packing governor."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.memory.evolution_trace import (
    NAMESPACE_PERSONAL_PREFERENCE,
    NAMESPACE_RESEARCH_THESIS,
    NAMESPACE_SYSTEM_OPERATIONS,
    NAMESPACE_TRADING_DISCIPLINE,
    record_trace,
)
from backend.memory.task_capsule import list_task_capsules


@dataclass(frozen=True)
class ContextBudget:
    total: int = 1200
    resident: int = 450
    retrieval: int = 750


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 1) // 2)


def _clip(text: str, token_budget: int) -> str:
    if estimate_tokens(text) <= token_budget:
        return text
    max_chars = max(20, token_budget * 2 - 10)
    return text[:max_chars].rstrip() + "...[truncated]"


def _candidate_key(item: dict[str, Any]) -> tuple[str, str]:
    symbols = item.get("symbols") or []
    themes = item.get("themes") or []
    symbol = str((symbols[0] if symbols else item.get("symbol") or "") or "")
    theme = str((themes[0] if themes else item.get("theme") or item.get("namespace") or "") or "")
    return theme, symbol


def _line_from_memory(row: dict[str, Any]) -> str:
    namespace = row.get("namespace") or row.get("memory_type") or row.get("category") or "memory"
    subject = row.get("subject") or row.get("symbol") or row.get("key") or ""
    summary = row.get("summary") or row.get("value") or row.get("content") or ""
    prefix = f"[{namespace}]"
    if subject:
        prefix += f"[{subject}]"
    return f"- {prefix} {summary}"


def _resident_candidates(db, *, symbol: str | None, query: str | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {
            "id": "root:trading-boundary",
            "namespace": NAMESPACE_TRADING_DISCIPLINE,
            "subject": "MingCang",
            "summary": "系统只做研究和决策支持,不得执行真实交易,不得把记忆直接提升为 official signal。",
            "symbols": [],
            "themes": ["纪律规则"],
        }
    ]
    try:
        from backend.memory.ai_memory import list_active

        for row in list_active(db, category="rule")[:3]:
            items.append({
                "id": f"ai:{row['id']}",
                "namespace": NAMESPACE_TRADING_DISCIPLINE,
                "subject": row.get("key"),
                "summary": row.get("value"),
                "symbols": [symbol] if symbol else [],
                "themes": ["纪律规则"],
            })
        for row in list_active(db, category="preference")[:3]:
            items.append({
                "id": f"ai:{row['id']}",
                "namespace": NAMESPACE_PERSONAL_PREFERENCE,
                "subject": row.get("key"),
                "summary": row.get("value"),
                "symbols": [symbol] if symbol else [],
                "themes": ["用户偏好"],
            })
    except Exception:
        pass
    if query:
        items.append({
            "id": "query:current",
            "namespace": NAMESPACE_RESEARCH_THESIS,
            "subject": symbol,
            "summary": f"当前任务论点摘要:{query[:160]}",
            "symbols": [symbol] if symbol else [],
            "themes": ["当前论点摘要"],
        })
    return items


def _retrieval_candidates(db, *, symbol: str | None, query: str | None, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for capsule in list_task_capsules(db, limit=3):
        items.append({
            "id": f"capsule:{capsule['capsule_id']}",
            "namespace": NAMESPACE_SYSTEM_OPERATIONS,
            "subject": capsule["capsule_id"],
            "summary": (
                f"{capsule['goal']}；下一步:{' / '.join(capsule.get('next_actions') or [])}; "
                f"未完成:{' / '.join(capsule.get('open_loops') or [])}"
            ),
            "symbols": capsule.get("symbols_json") or [],
            "themes": capsule.get("themes_json") or [],
        })
    try:
        from backend.memory.stock_memory import list_stock_memories

        for row in list_stock_memories(db, symbol=symbol, limit=max(limit, 8)):
            items.append({
                "id": f"stock:{row['id']}",
                "namespace": NAMESPACE_RESEARCH_THESIS,
                "subject": row.get("symbol"),
                "summary": row.get("summary"),
                "symbols": [row["symbol"]] if row.get("symbol") else [],
                "themes": [row.get("memory_type") or ""],
            })
    except Exception:
        pass
    return items


def _pack_layer(candidates: list[dict[str, Any]], *, token_budget: int) -> tuple[list[str], list[str], list[str], int]:
    lines: list[str] = []
    used: list[str] = []
    omitted: list[str] = []
    seen: set[tuple[str, str]] = set()
    spent = 0
    for item in candidates:
        key = _candidate_key(item)
        ref = str(item.get("id") or "")
        if key in seen:
            omitted.append(ref)
            continue
        seen.add(key)
        line = _line_from_memory(item)
        line_tokens = estimate_tokens(line)
        if spent + line_tokens > token_budget:
            remaining = token_budget - spent
            if remaining >= 30:
                clipped = _clip(line, remaining)
                lines.append(clipped)
                used.append(ref)
                spent += estimate_tokens(clipped)
            else:
                omitted.append(ref)
            continue
        lines.append(line)
        used.append(ref)
        spent += line_tokens
    return lines, used, omitted, spent


def build_agent_context(
    db,
    *,
    task_type: str,
    query: str | None = None,
    symbol: str | None = None,
    user_id: str = "owner",
    budget: ContextBudget | None = None,
    retrieval_limit: int = 8,
) -> dict[str, Any]:
    del user_id
    budget = budget or ContextBudget()
    resident_lines, resident_refs, resident_omitted, resident_tokens = _pack_layer(
        _resident_candidates(db, symbol=symbol, query=query),
        token_budget=budget.resident,
    )
    retrieval_lines, retrieval_refs, retrieval_omitted, retrieval_tokens = _pack_layer(
        _retrieval_candidates(db, symbol=symbol, query=query, limit=retrieval_limit),
        token_budget=min(budget.retrieval, max(0, budget.total - resident_tokens)),
    )
    parts: list[str] = []
    if resident_lines:
        parts.append("【常驻记忆块】\n" + "\n".join(resident_lines))
    if retrieval_lines:
        parts.append("【检索记忆块】\n" + "\n".join(retrieval_lines))
    text_value = "\n\n".join(parts)
    omitted = [*resident_omitted, *retrieval_omitted]
    provenance = [*resident_refs, *retrieval_refs]
    token_estimate = estimate_tokens(text_value)
    trace = record_trace(
        db,
        trace_type="context_governor.pack",
        namespace=NAMESPACE_SYSTEM_OPERATIONS,
        subject=symbol,
        content=f"ContextGovernor packed task={task_type} refs={len(provenance)} omitted={len(omitted)}",
        symbols=[symbol] if symbol else [],
        themes=[task_type],
        payload={
            "task_type": task_type,
            "provenance": provenance,
            "omitted": omitted,
            "token_estimate": token_estimate,
            "budget": {
                "total": budget.total,
                "resident": budget.resident,
                "retrieval": budget.retrieval,
            },
        },
        source_type="context_governor",
        source_ref=f"{task_type}:{symbol or 'global'}",
    )
    return {
        "text": text_value,
        "resident_text": "\n".join(resident_lines),
        "retrieval_text": "\n".join(retrieval_lines),
        "provenance": provenance,
        "omitted": omitted,
        "drilldown_available": omitted,
        "token_estimate": token_estimate,
        "trace_id": trace["id"],
    }
