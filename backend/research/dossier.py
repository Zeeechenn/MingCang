"""Per-symbol research dossier aggregation."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.agents.long_term.storage import get_active_label
from backend.api.routes._shared import latest_signal, signal_to_schema
from backend.config import settings
from backend.data.database import Stock
from backend.decision.harness import (
    get_decision_evidence,
    get_official_decision_evidence,
    get_research_state,
)
from backend.decision.signal_policy import is_entry_signal
from backend.memory.stock_memory import list_stock_memories
from backend.research.case import build_case


def _parse(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _label_to_dict(label) -> dict | None:
    if label is None:
        return None
    return {
        "symbol": label.symbol,
        "date": label.date,
        "label": label.label,
        "score": label.score,
        "votes": label.votes,
        "key_findings": label.key_findings,
        "expires_at": label.expires_at,
        "quality": label.quality,
        "constraint_eligible": label.constraint_eligible,
        "quality_notes": label.quality_notes,
    }


def _stock_to_dict(stock: Stock | None) -> dict | None:
    if stock is None:
        return None
    return {
        "symbol": stock.symbol,
        "name": stock.name,
        "market": stock.market,
        "industry": stock.industry,
        "active": stock.active,
    }


def _memory_rows(db: Session, symbol: str) -> list[dict]:
    try:
        rows = list_stock_memories(db, symbol=symbol, limit=16)
    except OperationalError:
        return []
    for row in rows:
        row["evidence"] = _parse(row.get("evidence_json"), None)
    return rows


def _deep_research(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("memory_type") == "research_pointer"]


def _pending_questions(research_state: dict) -> list[str]:
    """Return copilot validation questions that should seed follow-up research."""
    copilot = research_state.get("copilot") or {}
    questions = copilot.get("validation_questions") if isinstance(copilot, dict) else []
    if not isinstance(questions, list):
        return []
    return [str(item).strip() for item in questions if str(item).strip()]


def _latest_official_action(signal, evidence: list[dict]) -> dict:
    if evidence:
        final_action = evidence[0].get("final_action") or {}
        official = final_action.get("official_action") or {}
        return {
            "recommendation": official.get("recommendation") or evidence[0].get("recommendation"),
            "position_pct": final_action.get("position_pct"),
            "trader_position_pct": final_action.get("trader_position_pct"),
            "stop_loss": final_action.get("stop_loss"),
            "take_profit": final_action.get("take_profit"),
            "is_constrained": official.get("is_constrained", False),
            "constraint_count": official.get("constraint_count", 0),
            "conflict_count": official.get("conflict_count", 0),
            "source": "decision_run",
        }
    if signal is None:
        return {"recommendation": None, "position_pct": None, "source": "none"}
    return {
        "recommendation": signal.recommendation,
        "position_pct": None,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "is_constrained": False,
        "constraint_count": 0,
        "conflict_count": 0,
        "source": "signal",
    }


def _conflicts(signal, label: dict | None, memory_rows: list[dict], evidence: list[dict]) -> list[dict]:
    out: list[dict[str, Any]] = []
    if evidence:
        out.extend(evidence[0].get("agent_outputs", {}).get("research_conflicts") or [])
    if signal is not None and label and label.get("label") == "规避" \
            and label.get("constraint_eligible") \
            and is_entry_signal(signal.recommendation, include_legacy=True):
        out.append({
            "type": "short_long_conflict",
            "severity": "high",
            "summary": "短线信号入场，但长期标签为规避",
        })
    risk_rows = [r for r in memory_rows if r.get("memory_type") in {"risk", "lesson"}]
    if signal is not None and is_entry_signal(signal.recommendation, include_legacy=True) and risk_rows:
        out.append({
            "type": "memory_risk",
            "severity": "medium",
            "summary": risk_rows[0].get("summary", ""),
        })
    return out


def build_research_dossier(db: Session, symbol: str) -> dict:
    """Aggregate the per-symbol research state without mutating local state."""
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    signal = latest_signal(symbol, db)
    label = get_active_label(symbol, db)
    research_state = get_research_state(db, symbol)
    evidence = get_decision_evidence(db, symbol, limit=5)
    official_evidence = get_official_decision_evidence(db, symbol, limit=5)
    memory_rows = _memory_rows(db, symbol)
    label_dict = _label_to_dict(label)
    pending_questions = _pending_questions(research_state)
    missing = []
    if signal is None:
        missing.append("latest_signal")
    if label is None:
        missing.append("long_term_label")
    if not _deep_research(memory_rows):
        missing.append("deep_research")
    if not research_state.get("copilot"):
        missing.append("copilot")
    if pending_questions:
        missing.append("pending_questions")
    out = {
        "symbol": symbol,
        "stock": _stock_to_dict(stock),
        "latest_signal": signal_to_schema(signal).model_dump() if signal else None,
        "long_term_label": label_dict,
        "research_state": research_state,
        "evidence": evidence,
        "stock_memory": memory_rows,
        "deep_research": _deep_research(memory_rows),
        "pending_questions": pending_questions,
        "conflicts": _conflicts(signal, label_dict, memory_rows, official_evidence),
        "official_action": _latest_official_action(signal, official_evidence),
        "missing": missing,
    }
    out["case"] = build_case(out) if settings.atlas_enabled else None
    return out
