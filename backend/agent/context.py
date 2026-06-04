"""Project context and memory snapshots for local coding agents."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.agent.security import agent_mode
from backend.data.database import LongTermLabel, Position, ResearchState, Signal, Stock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_DIR = Path.home() / ".stock-sage" / "memory"
_COUNT_TABLES = {
    "ai_memory",
    "stock_memory_items",
    "memory_atoms",
    "memory_scenarios",
    "memory_profiles",
    "decision_memory_layered",
    "audit_log_fts",
    "chat_sessions",
    "chat_messages",
    "research_states",
}


def _count(db: Session, table: str) -> int:
    if table not in _COUNT_TABLES:
        raise ValueError(f"table not allowed: {table}")
    try:
        sql = f"SELECT count(*) FROM {table}"  # noqa: S608 - table name is allowlisted above.
        return int(db.execute(text(sql)).scalar() or 0)
    except OperationalError:
        return 0


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    try:
        return [dict(row._mapping) for row in db.execute(text(sql), params or {}).all()]
    except OperationalError:
        return []


def _short(value: Any, limit: int = 180) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    return text_value if len(text_value) <= limit else text_value[:limit] + "..."


def _memory_files(memory_dir: Path) -> dict:
    markdown = sorted(memory_dir.glob("*.md")) if memory_dir.exists() else []
    medium = [path for path in markdown if path.name.startswith("medium_")]
    plain = [path for path in markdown if not path.name.startswith("medium_")]
    backup_dir = memory_dir / "backups"
    backups = sorted(path.name for path in backup_dir.glob("ai_memory_*.json")) if backup_dir.exists() else []
    return {
        "path": str(memory_dir),
        "markdown_total": len(markdown),
        "medium_markdown": len(medium),
        "plain_symbol_markdown": len(plain),
        "backup_files": backups,
    }


def stock_sage_memory_snapshot(
    db: Session,
    *,
    memory_dir: Path | str = DEFAULT_MEMORY_DIR,
    limit: int = 12,
) -> dict:
    """Return a compact snapshot of StockSage's project-owned memory."""
    memory_path = Path(memory_dir)
    ai_rows = _rows(
        db,
        """
        SELECT id, key, scope, category, ttl_days, created_at, updated_at, value
        FROM ai_memory
        ORDER BY updated_at DESC, id DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    layered_rows = _rows(
        db,
        """
        SELECT id, symbol, layer, length(content) AS size, updated_at, content
        FROM decision_memory_layered
        ORDER BY updated_at DESC, id DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    audit_rows = _rows(
        db,
        """
        SELECT rowid, timestamp, event_type, content, related_symbol, related_scope
        FROM audit_log_fts
        ORDER BY rowid DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    grouped_ai = _rows(
        db,
        """
        SELECT scope, category, count(*) AS count
        FROM ai_memory
        GROUP BY scope, category
        ORDER BY scope, category
        """,
    )
    grouped_layered = _rows(
        db,
        """
        SELECT layer, count(*) AS count, min(updated_at) AS first_updated_at,
               max(updated_at) AS last_updated_at
        FROM decision_memory_layered
        GROUP BY layer
        ORDER BY layer
        """,
    )

    return {
        "database": {
            "ai_memory_count": _count(db, "ai_memory"),
            "stock_memory_items_count": _count(db, "stock_memory_items"),
            "memory_atoms_count": _count(db, "memory_atoms"),
            "memory_scenarios_count": _count(db, "memory_scenarios"),
            "memory_profiles_count": _count(db, "memory_profiles"),
            "decision_memory_layered_count": _count(db, "decision_memory_layered"),
            "audit_log_count": _count(db, "audit_log_fts"),
            "chat_sessions_count": _count(db, "chat_sessions"),
            "chat_messages_count": _count(db, "chat_messages"),
            "research_states_count": _count(db, "research_states"),
        },
        "ai_memory_by_scope_category": grouped_ai,
        "layered_by_layer": grouped_layered,
        "ai_memory": [
            {
                **{key: value for key, value in row.items() if key != "value"},
                "value_preview": _short(row.get("value")),
            }
            for row in ai_rows
        ],
        "layered_memory": [
            {
                **{key: value for key, value in row.items() if key != "content"},
                "content_preview": _short(row.get("content")),
            }
            for row in layered_rows
        ],
        "recent_audit": [
            {**row, "content": _short(row.get("content"))}
            for row in audit_rows
        ],
        "files": _memory_files(memory_path),
    }


def _latest_signal(db: Session, symbol: str) -> dict | None:
    try:
        row = (
            db.query(Signal)
            .filter(Signal.symbol == symbol)
            .order_by(Signal.date.desc(), Signal.id.desc())
            .first()
        )
    except OperationalError:
        return None
    if row is None:
        return None
    return {
        "date": row.date,
        "recommendation": row.recommendation,
        "composite_score": row.composite_score,
        "confidence": row.confidence,
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "rule_version": row.rule_version,
    }


def _research_copilot(db: Session, symbol: str) -> dict | None:
    try:
        row = db.query(ResearchState).filter(ResearchState.symbol == symbol).first()
    except OperationalError:
        return None
    if row is None:
        return None
    import json

    try:
        return json.loads(row.copilot_json) if row.copilot_json else None
    except Exception:
        return None


def stock_sage_stock_context(db: Session, symbol: str) -> dict:
    """Return the project context most useful before discussing one stock."""
    try:
        from backend.memory.stock_memory import build_memory_context
        memory_context = build_memory_context(db, symbol=symbol, task_type="stock_context")
    except Exception:
        memory_context = {"symbol": symbol, "task_type": "stock_context", "text": "",
                          "used_stock_memory_ids": [], "ai_memory_keys": []}
    try:
        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        position = (
            db.query(Position)
            .filter(Position.symbol == symbol, Position.status == "open")
            .order_by(Position.opened_at.desc(), Position.id.desc())
            .first()
        )
        label = (
            db.query(LongTermLabel)
            .filter(LongTermLabel.symbol == symbol)
            .order_by(LongTermLabel.date.desc(), LongTermLabel.id.desc())
            .first()
        )
    except OperationalError:
        stock = None
        position = None
        label = None
    layered = _rows(
        db,
        """
        SELECT layer, length(content) AS size, updated_at, content
        FROM decision_memory_layered
        WHERE symbol = :symbol
        ORDER BY updated_at DESC
        LIMIT 3
        """,
        {"symbol": symbol},
    )
    return {
        "symbol": symbol,
        "stock": {
            "name": stock.name,
            "market": stock.market,
            "industry": stock.industry,
            "active": stock.active,
        } if stock else None,
        "latest_signal": _latest_signal(db, symbol),
        "open_position": {
            "quantity": position.quantity,
            "avg_cost": position.avg_cost,
            "opened_at": position.opened_at,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
        } if position else None,
        "long_term_label": {
            "date": label.date,
            "label": label.label,
            "score": label.score,
            "expires_at": label.expires_at,
        } if label else None,
        "copilot": _research_copilot(db, symbol),
        "layered_memory": [
            {**row, "content_preview": _short(row.get("content"), 300)}
            for row in layered
        ],
        "memory_context": memory_context,
    }


def _open_positions(db: Session) -> dict:
    try:
        rows = db.query(Position).filter(Position.status == "open").all()
    except OperationalError:
        rows = []
    return {
        "open_count": len(rows),
        "symbols": [row.symbol for row in rows],
    }


def _watchlist(db: Session) -> dict:
    try:
        rows = db.query(Stock).filter(Stock.active).order_by(Stock.symbol.asc()).all()
    except OperationalError:
        rows = []
    return {
        "active_count": len(rows),
        "symbols": [row.symbol for row in rows[:80]],
    }


def stock_sage_context(
    db: Session,
    *,
    symbol: str | None = None,
    memory_dir: Path | str = DEFAULT_MEMORY_DIR,
) -> dict:
    """Return the compact startup context coding agents should read first."""
    memory = stock_sage_memory_snapshot(db, memory_dir=memory_dir)
    try:
        from backend.memory.stock_memory import build_memory_context
        memory_context = build_memory_context(
            db,
            symbol=symbol,
            task_type="project_context",
            limit=6,
        )
    except Exception:
        memory_context = {
            "symbol": symbol,
            "task_type": "project_context",
            "text": "",
            "used_stock_memory_ids": [],
            "ai_memory_keys": [],
            "used_memory_atom_ids": [],
            "l0_context": {},
        }
    context = {
        "agent_mode": agent_mode(),
        "project_root": str(PROJECT_ROOT),
        "docs": {
            "project": str(PROJECT_ROOT / "PROJECT.md"),
            "status": str(PROJECT_ROOT / "STATUS.md"),
            "roadmap": str(PROJECT_ROOT / "docs" / "ROADMAP.md"),
            "agents": str(PROJECT_ROOT / "AGENTS.md"),
        },
        "memory": memory["database"],
        "memory_context": memory_context,
        "positions": _open_positions(db),
        "watchlist": _watchlist(db),
    }
    if symbol:
        context["symbol_context"] = stock_sage_stock_context(db, symbol)
    return context


def stock_sage_memory_context(
    db: Session,
    *,
    symbol: str | None = None,
    query: str | None = None,
    task_type: str = "research",
    limit: int = 8,
) -> dict:
    """Return prompt-ready project memory for one stock or research task."""
    try:
        from backend.memory.stock_memory import build_memory_context

        return build_memory_context(
            db,
            symbol=symbol,
            query=query,
            task_type=task_type,
            limit=limit,
        )
    except Exception:
        return {
            "symbol": symbol,
            "task_type": task_type,
            "text": "",
            "used_stock_memory_ids": [],
            "ai_memory_keys": [],
            "used_memory_atom_ids": [],
            "l0_context": {},
        }
