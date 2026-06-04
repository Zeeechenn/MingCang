import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest


def _prepare_memory_schema(db):
    from backend.memory.ai_memory import _ensure_schema
    from backend.memory.audit_log import _ensure_schema as _ensure_audit_schema

    _ensure_schema(db)
    _ensure_audit_schema(db)


def test_memory_snapshot_summarizes_project_memory(test_db, tmp_path):
    from backend.data.database import ChatSession, DecisionMemoryLayered
    from backend.memory.ai_memory import remember
    from backend.memory.audit_log import audit_write

    _prepare_memory_schema(test_db)
    remember(
        test_db,
        "validation_rule",
        "本地验证材料不进入 GitHub。",
        category="validation_rules",
        scope="global",
        force=True,
    )
    test_db.add(DecisionMemoryLayered(
        symbol="300308",
        layer="medium",
        content="# 300308 中期决策记忆\n| 日期 | 建议 |\n",
        updated_at=datetime.utcnow(),
    ))
    test_db.add(ChatSession(id="s1", title="新对话", mode="general"))
    test_db.commit()
    audit_write(test_db, "decision_memory.save", "symbol=300308 rec=可关注", related_symbol="300308")

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "medium_300308.md").write_text("# medium\n", encoding="utf-8")
    (memory_dir / "300308.md").write_text("# history\n", encoding="utf-8")
    (memory_dir / "backups").mkdir()
    (memory_dir / "backups" / "ai_memory_2026-05-19.json").write_text("[]", encoding="utf-8")

    from backend.agent.context import stock_sage_memory_snapshot

    snapshot = stock_sage_memory_snapshot(test_db, memory_dir=memory_dir)

    assert snapshot["database"]["ai_memory_count"] == 1
    assert snapshot["database"]["decision_memory_layered_count"] == 1
    assert snapshot["database"]["chat_sessions_count"] == 1
    assert snapshot["database"]["chat_messages_count"] == 0
    assert snapshot["files"]["markdown_total"] == 2
    assert snapshot["files"]["medium_markdown"] == 1
    assert snapshot["files"]["plain_symbol_markdown"] == 1
    assert snapshot["files"]["backup_files"] == ["ai_memory_2026-05-19.json"]
    assert snapshot["ai_memory"][0]["key"] == "validation_rule"
    assert snapshot["recent_audit"][0]["event_type"] == "decision_memory.save"


def test_local_mode_allows_sensitive_operations_without_api_key():
    from backend.agent.security import require_agent_access

    require_agent_access("write", env={"STOCKSAGE_AGENT_MODE": "local"})
    require_agent_access("write", env={})


def test_remote_mode_requires_api_key_for_read_and_disallows_write_by_default():
    from backend.agent.security import AgentSecurityError, require_agent_access

    with pytest.raises(AgentSecurityError):
        require_agent_access("read", env={"STOCKSAGE_AGENT_MODE": "remote"})

    require_agent_access(
        "read",
        env={"STOCKSAGE_AGENT_MODE": "remote", "STOCKSAGE_AGENT_API_KEY": "secret"},
        api_key="secret",
    )

    with pytest.raises(AgentSecurityError):
        require_agent_access(
            "write",
            env={"STOCKSAGE_AGENT_MODE": "remote", "STOCKSAGE_AGENT_API_KEY": "secret"},
            api_key="secret",
        )


def test_stock_sage_context_handles_uninitialized_database(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.agent.context import stock_sage_context

    engine = create_engine(f"sqlite:///{tmp_path / 'blank.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        context = stock_sage_context(db, symbol="300308")
    finally:
        db.close()

    assert context["memory"]["ai_memory_count"] == 0
    assert context["positions"] == {"open_count": 0, "symbols": []}
    assert context["watchlist"] == {"active_count": 0, "symbols": []}
    assert context["symbol_context"]["stock"] is None
    assert context["symbol_context"]["latest_signal"] is None


def test_stock_sage_memory_context_handles_uninitialized_database(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.agent.context import stock_sage_memory_context

    engine = create_engine(f"sqlite:///{tmp_path / 'blank-memory.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        context = stock_sage_memory_context(db, symbol="300308")
    finally:
        db.close()

    assert context["symbol"] == "300308"
    assert context["task_type"] == "research"
    assert context["text"] == ""
    assert context["used_stock_memory_ids"] == []
    assert context["ai_memory_keys"] == []
    assert context["used_memory_atom_ids"] == []
    assert "l0_context" in context


def test_stock_sage_context_includes_rules_memory_and_positions(test_db, sample_stocks):
    from backend.data.database import Position, Signal
    from backend.memory.ai_memory import remember
    from backend.memory.stock_memory import create_stock_memory

    _prepare_memory_schema(test_db)
    remember(
        test_db,
        "validation_rule",
        "本地验证材料不进入 GitHub。",
        category="validation_rules",
        scope="global",
        force=True,
    )
    test_db.add(Position(
        symbol="300308",
        name="中际旭创",
        market="CN",
        quantity=100,
        avg_cost=1000,
        opened_at="2026-05-21",
        status="open",
    ))
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="300308 若缩量上冲需降低仓位。",
        source_type="unit_test",
        importance=4,
        confidence=0.8,
    )
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-21",
        composite_score=36,
        recommendation="可小仓试错",
        confidence="中",
    ))
    test_db.commit()

    from backend.agent.context import stock_sage_context

    context = stock_sage_context(test_db, symbol="300308")

    assert context["agent_mode"] == "local"
    assert context["memory"]["ai_memory_count"] == 1
    assert context["positions"]["open_count"] == 1
    assert context["symbol_context"]["symbol"] == "300308"
    assert context["symbol_context"]["latest_signal"]["recommendation"] == "可小仓试错"
    assert "memory_context" in context
    assert "300308 若缩量上冲需降低仓位" in context["memory_context"]["text"]
    assert "300308 若缩量上冲需降低仓位" in context["symbol_context"]["memory_context"]["text"]


def test_mcp_server_smoke_lists_tools_and_reads_health(tmp_path):
    db_path = tmp_path / f"agent-smoke-{uuid.uuid4().hex}.db"
    db_url = f"sqlite:///{db_path}"
    repo = Path(__file__).resolve().parents[1]
    script = """
import asyncio
import json
import os
import sys
from pathlib import Path

repo = Path(os.environ["PYTHONPATH"])
db_url = os.environ["DATABASE_URL"]

from backend.data.database import init_db
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

init_db()

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.agent.mcp_server"],
        cwd=str(repo),
        env=os.environ.copy(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("stock_sage_health", arguments={})
            print(json.dumps({
                "tools": [tool.name for tool in tools.tools],
                "content": [getattr(item, "text", "") for item in result.content],
            }, ensure_ascii=False))

asyncio.run(main())
"""

    env = {
        "DATABASE_URL": db_url,
        "PYTHONPATH": str(repo),
        "STOCKSAGE_AGENT_MODE": "local",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )

    payload = result.stdout.strip().splitlines()[-1]
    data = json.loads(payload)

    assert data["tools"] == [
        "stock_sage_project_context",
        "stock_sage_memory_snapshot",
        "stock_sage_memory_context",
        "stock_sage_stock_context",
        "stock_sage_health",
    ]
    assert '"ok": true' in data["content"][0]


def test_mcp_server_remote_mode_requires_tool_api_key(tmp_path):
    db_path = tmp_path / f"agent-remote-{uuid.uuid4().hex}.db"
    db_url = f"sqlite:///{db_path}"
    repo = Path(__file__).resolve().parents[1]
    script = """
import asyncio
import json
import os
import sys
from pathlib import Path

repo = Path(os.environ["PYTHONPATH"])

from backend.data.database import init_db
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

init_db()

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.agent.mcp_server"],
        cwd=str(repo),
        env=os.environ.copy(),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            denied = await session.call_tool("stock_sage_health", arguments={})
            allowed = await session.call_tool("stock_sage_health", arguments={"api_key": "secret"})
            print(json.dumps({
                "denied": [getattr(item, "text", "") for item in denied.content],
                "allowed": [getattr(item, "text", "") for item in allowed.content],
            }, ensure_ascii=False))

asyncio.run(main())
"""
    env = {
        "DATABASE_URL": db_url,
        "PYTHONPATH": str(repo),
        "STOCKSAGE_AGENT_MODE": "remote",
        "STOCKSAGE_AGENT_API_KEY": "secret",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )

    data = json.loads(result.stdout.strip().splitlines()[-1])

    assert "invalid StockSage agent API key" in data["denied"][0]
    assert '"ok": true' in data["allowed"][0]
