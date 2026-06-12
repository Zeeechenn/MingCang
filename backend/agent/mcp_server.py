"""MCP server exposing MingCang as local-first agent tools.

Run locally with:
    PYTHONPATH=. python -m backend.agent.mcp_server

Remote stdio MCP calls should set MINGCANG_AGENT_MODE=remote and pass
MINGCANG_AGENT_API_KEY as the tool ``api_key`` argument.
"""
from __future__ import annotations

from backend.agent.context import (
    mingcang_context as build_mingcang_context,
)
from backend.agent.context import (
    mingcang_memory_context as build_mingcang_memory_context,
)
from backend.agent.context import (
    mingcang_memory_snapshot as build_mingcang_memory_snapshot,
)
from backend.agent.context import (
    mingcang_stock_context as build_mingcang_stock_context,
)
from backend.agent.security import require_agent_access
from backend.data.database import SessionLocal

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised only without optional extra
    raise SystemExit(
        "MCP SDK is not installed. Run `pip install -e '.[agent]'` first."
    ) from exc


mcp = FastMCP("mingcang")


def _with_db(fn):
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


def _project_context(symbol: str | None = None, api_key: str | None = None) -> dict:
    require_agent_access("read", api_key=api_key)
    return _with_db(lambda db: build_mingcang_context(db, symbol=symbol))


def _memory_snapshot(api_key: str | None = None) -> dict:
    require_agent_access("read", api_key=api_key)
    return _with_db(build_mingcang_memory_snapshot)


def _memory_context(
    symbol: str,
    task_type: str | None = None,
    query: str | None = None,
    api_key: str | None = None,
) -> dict:
    require_agent_access("read", api_key=api_key)
    return _with_db(lambda db: build_mingcang_memory_context(
        db,
        symbol=symbol,
        query=query,
        task_type=task_type or "research",
    ))


def _stock_context(symbol: str, api_key: str | None = None) -> dict:
    require_agent_access("read", api_key=api_key)
    return _with_db(lambda db: build_mingcang_stock_context(db, symbol))


def _health(api_key: str | None = None) -> dict:
    require_agent_access("read", api_key=api_key)

    def _read(db):
        context = build_mingcang_context(db)
        return {
            "ok": True,
            "agent_mode": context["agent_mode"],
            "project_root": context["project_root"],
            "memory": context["memory"],
            "positions": context["positions"],
            "watchlist": context["watchlist"],
        }

    return _with_db(_read)


@mcp.tool()
def mingcang_project_context(symbol: str | None = None, api_key: str | None = None) -> dict:
    """Read MingCang startup context, memory counts, watchlist, and positions."""
    return _project_context(symbol=symbol, api_key=api_key)


@mcp.tool()
def mingcang_memory_snapshot(api_key: str | None = None) -> dict:
    """Read MingCang project-owned memory summary and recent entries."""
    return _memory_snapshot(api_key=api_key)


@mcp.tool()
def mingcang_memory_context(
    symbol: str,
    task_type: str | None = None,
    query: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Read prompt-ready MingCang memory context for one stock."""
    return _memory_context(symbol, task_type=task_type, query=query, api_key=api_key)


@mcp.tool()
def mingcang_stock_context(symbol: str, api_key: str | None = None) -> dict:
    """Read signal, position, long-term label, and memory context for one stock."""
    return _stock_context(symbol, api_key=api_key)


@mcp.tool()
def mingcang_health(api_key: str | None = None) -> dict:
    """Read basic database-backed agent health."""
    return _health(api_key=api_key)


if __name__ == "__main__":
    mcp.run()
