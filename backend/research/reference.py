"""Read-only research reference pack shared by panels and LLM confirmation."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _latest_long_term_label(
    connection: sqlite3.Connection, symbol: str, as_of: str
) -> dict[str, Any]:
    if not _table_exists(connection, "long_term_labels"):
        return {
            "label": None,
            "quality": None,
            "expires_at": None,
            "status": "missing:table:long_term_labels",
        }
    columns = _columns(connection, "long_term_labels")
    if "symbol" not in columns:
        return {
            "label": None,
            "quality": None,
            "expires_at": None,
            "status": "missing:columns:symbol",
        }
    order_column = "date" if "date" in columns else (
        "created_at" if "created_at" in columns else None
    )
    if order_column is None:
        return {
            "label": None,
            "quality": None,
            "expires_at": None,
            "status": "missing:columns:date,created_at",
        }
    expiry_clause = ""
    parameters: list[Any] = [symbol]
    if "expires_at" in columns:
        expiry_clause = "AND (expires_at IS NULL OR expires_at >= ?)"
        parameters.append(as_of)
    selected = [
        column
        for column in ("label", "quality", "expires_at", order_column)
        if column in columns
    ]
    row = connection.execute(
        f"SELECT {', '.join(selected)} FROM long_term_labels "
        f"WHERE symbol = ? {expiry_clause} ORDER BY {order_column} DESC LIMIT 1",
        parameters,
    ).fetchone()
    if row is None:
        return {
            "label": None,
            "quality": None,
            "expires_at": None,
            "status": "missing:no_valid_label",
        }
    data = dict(row)
    return {
        "label": data.get("label"),
        "quality": data.get("quality"),
        "expires_at": data.get("expires_at"),
        "status": "ok",
    }


def _latest_research_pointer(connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
    if not _table_exists(connection, "stock_memory_items"):
        return {
            "summary": None,
            "created_at": None,
            "status": "missing:table:stock_memory_items",
        }
    columns = _columns(connection, "stock_memory_items")
    missing = sorted({"symbol", "memory_type", "summary", "created_at"} - columns)
    if missing:
        return {
            "summary": None,
            "created_at": None,
            "status": f"missing:columns:{','.join(missing)}",
        }
    row = connection.execute(
        """
        SELECT summary, created_at
        FROM stock_memory_items
        WHERE symbol = ? AND memory_type = 'research_pointer'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None:
        return {
            "summary": None,
            "created_at": None,
            "status": "missing:no_research_pointer",
        }
    return {"summary": row["summary"], "created_at": row["created_at"], "status": "ok"}


def _latest_copilot_card(connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
    if not _table_exists(connection, "research_states"):
        return {
            "summary": None,
            "trigger_quality": None,
            "status": "missing:table:research_states",
        }
    columns = _columns(connection, "research_states")
    missing = sorted({"symbol", "copilot_json"} - columns)
    if missing:
        return {
            "summary": None,
            "trigger_quality": None,
            "status": f"missing:columns:{','.join(missing)}",
        }
    row = connection.execute(
        """
        SELECT copilot_json
        FROM research_states
        WHERE symbol = ? AND copilot_json IS NOT NULL
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None:
        return {
            "summary": None,
            "trigger_quality": None,
            "status": "missing:no_copilot",
        }
    try:
        card = json.loads(row["copilot_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        return {
            "summary": None,
            "trigger_quality": None,
            "status": f"invalid:copilot_json:{exc.__class__.__name__}",
        }
    if not isinstance(card, dict):
        return {
            "summary": None,
            "trigger_quality": None,
            "status": "invalid:copilot_json:not_object",
        }
    return {
        "summary": card.get("summary_opinion"),
        "stance": card.get("stance"),
        "reentry_trigger": card.get("reentry_trigger"),
        "trigger_quality": card.get("trigger_quality") or "ok",
        "status": "ok",
    }


def build_research_reference(
    connection: sqlite3.Connection, symbol: str, as_of: str
) -> dict[str, Any]:
    """Return non-scoring long-term, research-pointer, and copilot context."""
    return {
        "long_term_label": _latest_long_term_label(connection, symbol, as_of),
        "research_pointer": _latest_research_pointer(connection, symbol),
        "copilot": _latest_copilot_card(connection, symbol),
    }


__all__ = ["build_research_reference"]
