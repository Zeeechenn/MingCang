"""Lightweight research constraints shared by daily and dossier flows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.config import settings
from backend.decision.signal_policy import ENTRY_RECS, LEGACY_ENTRY_RECS, score_to_recommendation

ENTRY_SET = ENTRY_RECS | LEGACY_ENTRY_RECS


@dataclass
class ResearchConstraintResult:
    recommendation: str
    composite_score: float
    position_pct: float
    risk_notes: list[str] = field(default_factory=list)
    constraints: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    final_action: dict = field(default_factory=dict)


def _label_value(long_term_label: Any) -> str | None:
    if long_term_label is None:
        return None
    if isinstance(long_term_label, dict):
        return long_term_label.get("label")
    return getattr(long_term_label, "label", None)


def _label_finding(long_term_label: Any) -> str:
    if long_term_label is None:
        return ""
    findings = long_term_label.get("key_findings") if isinstance(long_term_label, dict) \
        else getattr(long_term_label, "key_findings", None)
    return str((findings or [""])[0])


def _memory_lines(memory_context: dict | None) -> list[str]:
    text_value = (memory_context or {}).get("text") or ""
    return [line.strip("- ").strip() for line in text_value.splitlines() if line.strip().startswith("- [")]


def memory_constraints(memory_context: dict | None, *, limit: int = 4) -> list[dict]:
    """Extract prompt-ready memory rows into structured, displayable constraints."""
    constraints: list[dict] = []
    for line in _memory_lines(memory_context):
        kind = "memory"
        if line.startswith("[risk|"):
            kind = "risk"
        elif line.startswith("[thesis|"):
            kind = "thesis"
        elif line.startswith("[event|"):
            kind = "event"
        elif line.startswith("[research_pointer|"):
            kind = "research_pointer"
        elif line.startswith("[lesson|"):
            kind = "lesson"
        constraints.append({
            "type": kind,
            "source": "stock_memory",
            "summary": line,
        })
        if len(constraints) >= limit:
            break
    return constraints


def apply_research_constraints(
    *,
    recommendation: str,
    composite_score: float,
    position_pct: float,
    long_term_label=None,
    memory_context: dict | None = None,
    long_term_checked: bool = True,
) -> ResearchConstraintResult:
    """Apply V1 long-term and memory constraints without changing the base score model."""
    final_rec = recommendation
    final_score = composite_score
    final_pos = position_pct
    notes: list[str] = []
    constraints: list[dict] = []
    conflicts: list[dict] = []

    label = _label_value(long_term_label)
    finding = _label_finding(long_term_label)
    is_entry = final_rec in ENTRY_SET

    if settings.long_term_team_enabled and long_term_checked and label is None and is_entry:
        final_rec = "可关注"
        final_pos = 0.0
        notes.append("长期标签缺失，禁可小仓试错，降级为可关注")
        constraints.append({
            "type": "long_term_missing",
            "source": "long_term",
            "summary": "长期标签缺失，强入场降级为观察",
        })

    if settings.long_term_team_enabled and label:
        constraints.append({
            "type": "long_term_label",
            "source": "long_term",
            "label": label,
            "summary": finding or f"长期标签：{label}",
        })
        if label == "规避" and is_entry and settings.long_term_avoid_blocks_buy:
            final_rec = "观望"
            final_pos = 0.0
            notes.append(f"长期团'规避'阻断入场: {finding}")
            conflicts.append({
                "type": "short_long_conflict",
                "severity": "high",
                "summary": "短线入场信号与长期规避标签冲突，官方动作改为观望",
            })
        elif label == "估值偏高" and is_entry:
            factor = settings.long_term_overvalued_position_factor
            final_pos = round(final_pos * factor, 4)
            notes.append(f"长期团'估值偏高'，仓位 ×{factor}")
            conflicts.append({
                "type": "valuation_constraint",
                "severity": "medium",
                "summary": "短线信号偏强，但长期估值标签要求降低动作强度",
            })
        elif label == "观望":
            cap = settings.long_term_watch_score_cap
            if final_score > cap:
                final_score = cap
                final_rec = score_to_recommendation(cap)
                if final_rec not in ENTRY_SET:
                    final_pos = 0.0
            notes.append(f"长期团'观望'限制短线强度: {finding}")

    mem_constraints = memory_constraints(memory_context)
    if mem_constraints:
        constraints.extend(mem_constraints)
        risk_rows = [c for c in mem_constraints if c["type"] in {"risk", "lesson"}]
        pointer_rows = [c for c in mem_constraints if c["type"] == "research_pointer"]
        if risk_rows:
            notes.append("股票记忆含风险/复盘教训，需复核后执行")
            if final_rec in ENTRY_SET:
                conflicts.append({
                    "type": "memory_risk",
                    "severity": "medium",
                    "summary": risk_rows[0]["summary"],
                })
        if pointer_rows:
            notes.append("存在深度研究索引，执行前应查看专题证据")

    final_action = {
        "recommendation": final_rec,
        "position_pct": round(final_pos, 4),
        "constraint_count": len(constraints),
        "conflict_count": len(conflicts),
        "is_constrained": bool(notes or conflicts),
    }
    return ResearchConstraintResult(
        recommendation=final_rec,
        composite_score=round(final_score, 1),
        position_pct=round(final_pos, 4),
        risk_notes=notes,
        constraints=constraints,
        conflicts=conflicts,
        final_action=final_action,
    )
