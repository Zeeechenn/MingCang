from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

AGENT_HEALTH_KEYS = {"ok", "agent_mode", "project_root", "memory", "positions", "watchlist"}
PROJECT_CONTEXT_KEYS = {
    "agent_mode",
    "project_root",
    "docs",
    "memory",
    "memory_context",
    "positions",
    "watchlist",
    "symbol_context",
}
MEMORY_SNAPSHOT_KEYS = {
    "database",
    "ai_memory_by_scope_category",
    "layered_by_layer",
    "ai_memory",
    "layered_memory",
    "recent_audit",
    "files",
}
STOCK_CONTEXT_KEYS = {
    "symbol",
    "stock",
    "latest_signal",
    "open_position",
    "long_term_label",
    "copilot",
    "layered_memory",
    "memory_context",
}
WEB_DATA_COVERAGE_KEYS = {"summary", "provider_health", "stocks"}
WEB_HEALTH_KEYS = {
    "healthy",
    "db_ok",
    "db_path",
    "latest_price_date",
    "data_age_days",
    "data_stale_threshold_days",
    "kill_switch",
    "consecutive_losses",
    "consecutive_losses_threshold",
    "scheduler",
    "runtime_readiness",
    "llm_budget_alert",   # M25.3: daily LLM cost alert status
}


def _assert_exact_keys(payload: dict, expected: set[str]) -> None:
    assert set(payload) == expected


def _run_cli(repo: Path, db_url: str, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "backend.agent.cli", *args],
        cwd=repo,
        env={
            "PYTHONPATH": str(repo),
            "DATABASE_URL": db_url,
            "STOCKSAGE_AGENT_MODE": "local",
        },
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_pi_context_contracts_keep_prompt_entry_fields(test_db, sample_stocks):
    from backend.agent.context import (
        stock_sage_context,
        stock_sage_memory_snapshot,
        stock_sage_stock_context,
    )

    project = stock_sage_context(test_db, symbol="300308")
    memory = stock_sage_memory_snapshot(test_db)
    stock = stock_sage_stock_context(test_db, "300308")

    _assert_exact_keys(project, PROJECT_CONTEXT_KEYS)
    _assert_exact_keys(memory, MEMORY_SNAPSHOT_KEYS)
    _assert_exact_keys(stock, STOCK_CONTEXT_KEYS)
    assert set(project["docs"]) == {"project", "status", "roadmap", "agents"}
    assert {"ai_memory_count", "stock_memory_items_count", "decision_memory_layered_count"} <= set(project["memory"])
    assert {"open_count", "symbols"} <= set(project["positions"])
    assert {"active_count", "symbols"} <= set(project["watchlist"])
    assert stock["symbol"] == "300308"
    assert {"symbol", "task_type", "text", "used_stock_memory_ids", "ai_memory_keys"} <= set(stock["memory_context"])


def test_agent_cli_read_commands_keep_json_contracts(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'contracts-{uuid.uuid4().hex}.db'}"

    health = _run_cli(repo, db_url, "health")
    project = _run_cli(repo, db_url, "project-context", "--symbol", "300308")
    memory = _run_cli(repo, db_url, "memory-snapshot")
    stock = _run_cli(repo, db_url, "stock-context", "300308")

    assert health.returncode == 0, health.stderr
    assert project.returncode == 0, project.stderr
    assert memory.returncode == 0, memory.stderr
    assert stock.returncode == 0, stock.stderr
    _assert_exact_keys(json.loads(health.stdout), AGENT_HEALTH_KEYS)
    _assert_exact_keys(json.loads(project.stdout), PROJECT_CONTEXT_KEYS)
    _assert_exact_keys(json.loads(memory.stdout), MEMORY_SNAPSHOT_KEYS)
    _assert_exact_keys(json.loads(stock.stdout), STOCK_CONTEXT_KEYS)


def test_mcp_health_contract_matches_agent_health(monkeypatch, test_db):
    from backend.agent import mcp_server

    monkeypatch.setattr(mcp_server, "SessionLocal", lambda: test_db)

    health = mcp_server.stock_sage_health()

    _assert_exact_keys(health, AGENT_HEALTH_KEYS)
    assert health["ok"] is True
    assert isinstance(health["memory"]["ai_memory_count"], int)
    assert {"open_count", "symbols"} <= set(health["positions"])
    assert {"active_count", "symbols"} <= set(health["watchlist"])


def test_web_system_contracts_keep_monitoring_fields(test_db, sample_stocks):
    from backend.api.routes.system import data_coverage, system_health

    coverage = data_coverage(db=test_db)
    health = system_health(db=test_db)

    _assert_exact_keys(coverage, WEB_DATA_COVERAGE_KEYS)
    _assert_exact_keys(health, WEB_HEALTH_KEYS)
    assert {"active_stocks", "price_covered", "financial_covered", "news_24h_covered"} <= set(
        coverage["summary"]
    )
    assert coverage["stocks"][0].keys() >= {
        "symbol",
        "name",
        "market",
        "industry",
        "price_rows",
        "latest_price_date",
        "latest_financial_report",
        "news_24h_count",
    }
    assert {"provider", "usable", "reason", "local_cli", "search"} <= set(health["runtime_readiness"])
