from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _run_cli(repo: Path, db_url: str, *args: str, env: dict[str, str] | None = None):
    full_env = {
        "PYTHONPATH": str(repo),
        "DATABASE_URL": db_url,
        "STOCKSAGE_AGENT_MODE": "local",
    }
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "backend.agent.cli", *args],
        cwd=repo,
        env=full_env,
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_agent_cli_health_handles_uninitialized_database(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'blank-{uuid.uuid4().hex}.db'}"

    result = _run_cli(repo, db_url, "health")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["memory"]["ai_memory_count"] == 0
    assert payload["positions"] == {"open_count": 0, "symbols": []}


def test_agent_cli_context_commands_emit_json(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'context-{uuid.uuid4().hex}.db'}"

    for args in (
        ("project-context", "--symbol", "300308"),
        ("memory-snapshot",),
        ("stock-context", "300308"),
    ):
        result = _run_cli(repo, db_url, *args)

        assert result.returncode == 0, result.stderr
        assert isinstance(json.loads(result.stdout), dict)


def test_agent_cli_trading_rhythm_commands_are_dry_run_contract(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_path = tmp_path / f"rhythm-{uuid.uuid4().hex}.db"
    db_url = f"sqlite:///{db_path}"

    for command in ("premarket", "intraday", "postmarket", "weekend"):
        result = _run_cli(repo, db_url, command, "--symbol", "300308")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["phase"] == command
        assert payload["symbol"] == "300308"
        assert payload["dry_run"] is True
        assert payload["heavy_tasks_executed"] is False
        assert payload["reused_entrypoints"]
        assert payload["side_effects"]["default"] == []
        assert payload["side_effects"]["if_confirmed"]
        assert payload["confirmation_required"] is True

    assert not db_path.exists()


def test_agent_cli_memory_context_reads_project_memory(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'memory-context-{uuid.uuid4().hex}.db'}"

    setup = _run_cli(repo, db_url, "health")
    assert setup.returncode == 0, setup.stderr

    write = _run_cli(
        repo,
        db_url,
        "action",
        "memory.write",
        "--payload-json",
        '{"key":"pref:risk","value":"用户偏好：不追高","category":"preference","scope":"global"}',
        "--confirm",
    )
    assert write.returncode == 0, write.stderr

    result = _run_cli(repo, db_url, "memory-context", "--symbol", "300308")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "用户偏好：不追高" in payload["text"]


def test_agent_cli_actions_lists_registered_actions(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'actions-{uuid.uuid4().hex}.db'}"

    result = _run_cli(repo, db_url, "actions")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    names = {item["name"] for item in payload["actions"]}
    assert "research.prepare" in names
    assert "long_term.run" in names


def test_agent_cli_tools_lists_registry_with_boundaries(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'tools-{uuid.uuid4().hex}.db'}"

    result = _run_cli(repo, db_url, "tools", "--pretty")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload["categories"]) == {"stable", "maintenance", "evidence", "attic"}

    tools = {item["module"]: item for item in payload["tools"]}
    expected_modules = {
        f"backend.tools.{path.stem}"
        for path in (repo / "backend" / "tools").glob("*.py")
        if path.name not in {"__init__.py", "registry.py"}
    }
    expected_modules.update(
        f"backend.tools.attic.{path.stem}"
        for path in (repo / "backend" / "tools" / "attic").glob("*.py")
        if path.name != "__init__.py"
    )
    assert set(tools) == expected_modules

    for module in (
        "backend.tools.coverage_snapshot",
        "backend.tools.m45_import_ateacher_theses",
        "backend.tools.atlas_test4_stage2b_shadow",
        "backend.tools.attic.backfill_and_run",
    ):
        assert module in tools
        assert tools[module]["purpose"]
        assert tools[module]["read_write_boundary"]
        assert tools[module]["recommended_entrypoint"]

    assert tools["backend.tools.coverage_snapshot"]["category"] == "stable"
    assert tools["backend.tools.m45_import_ateacher_theses"]["category"] == "maintenance"
    assert tools["backend.tools.atlas_test4_stage2b_shadow"]["category"] == "evidence"
    assert tools["backend.tools.attic.backfill_and_run"]["category"] == "attic"
    assert tools["backend.tools.attic.backfill_and_run"]["still_runnable"] is False

    filtered = _run_cli(repo, db_url, "tools", "--category", "evidence")
    assert filtered.returncode == 0, filtered.stderr
    filtered_payload = json.loads(filtered.stdout)
    assert filtered_payload["category"] == "evidence"
    assert filtered_payload["tools"]
    assert {item["category"] for item in filtered_payload["tools"]} == {"evidence"}


def test_agent_cli_read_context_commands_do_not_record_stock_memory_usage(tmp_path):
    from backend.memory.stock_memory import create_stock_memory

    repo = Path(__file__).resolve().parents[1]
    db_path = tmp_path / f"readonly-context-{uuid.uuid4().hex}.db"
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        row = create_stock_memory(
            db,
            symbol="300308",
            memory_type="risk",
            summary="300308 只读上下文不应刷新使用痕迹",
            source_type="unit_test",
        )
    finally:
        db.close()

    for args in (
        ("project-context", "--symbol", "300308"),
        ("stock-context", "300308"),
        ("memory-context", "--symbol", "300308"),
    ):
        result = _run_cli(repo, db_url, *args)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if args[0] == "project-context":
            assert "300308 只读上下文不应刷新使用痕迹" in payload["memory_context"]["text"]
        elif args[0] == "stock-context":
            assert "300308 只读上下文不应刷新使用痕迹" in payload["memory_context"]["text"]
        else:
            assert "300308 只读上下文不应刷新使用痕迹" in payload["text"]

    db = Session()
    try:
        used = db.execute(
            text("SELECT last_used_at FROM stock_memory_items WHERE id = :id"),
            {"id": row["id"]},
        ).scalar()
        recalls = db.execute(
            text("SELECT count(*) FROM audit_log_fts WHERE event_type='stock_memory.recall'")
        ).scalar()
    finally:
        db.close()

    assert used is None
    assert recalls == 0


def test_agent_cli_action_without_confirm_returns_metadata_without_writing(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_path = tmp_path / f"dry-run-{uuid.uuid4().hex}.db"
    db_url = f"sqlite:///{db_path}"

    setup = _run_cli(repo, db_url, "health")
    assert setup.returncode == 0, setup.stderr

    result = _run_cli(
        repo,
        db_url,
        "action",
        "watchlist.add",
        "--payload-json",
        '{"symbol":"600519","name":"贵州茅台","market":"CN"}',
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["requires_confirmation"] is True
    assert payload["input_schema"]["required"] == ["symbol"]

    context = json.loads(_run_cli(repo, db_url, "project-context").stdout)
    assert "600519" not in context["watchlist"]["symbols"]


def test_agent_cli_heavy_action_dry_run_does_not_execute(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'deep-dry-run-{uuid.uuid4().hex}.db'}"

    result = _run_cli(
        repo,
        db_url,
        "action",
        "research.deep.run",
        "--payload-json",
        '{"topic":"AI算力产业链","symbols":["300308"]}',
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["risk_level"] == "high"
    assert payload["payload"]["topic"] == "AI算力产业链"
    assert "executed" not in payload


def test_agent_cli_action_with_confirm_executes_registered_action(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'confirm-{uuid.uuid4().hex}.db'}"

    setup = _run_cli(repo, db_url, "health")
    assert setup.returncode == 0, setup.stderr

    result = _run_cli(
        repo,
        db_url,
        "action",
        "watchlist.add",
        "--payload-json",
        '{"symbol":"600519","name":"贵州茅台","market":"CN"}',
        "--confirm",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["executed"] is True
    assert payload["result"] == {"symbol": "600519", "active": True}

    context = json.loads(_run_cli(repo, db_url, "project-context").stdout)
    assert "600519" in context["watchlist"]["symbols"]


def test_agent_cli_remote_mode_requires_api_key(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'remote-{uuid.uuid4().hex}.db'}"

    denied = _run_cli(
        repo,
        db_url,
        "health",
        env={
            "STOCKSAGE_AGENT_MODE": "remote",
            "STOCKSAGE_AGENT_API_KEY": "secret",
        },
    )

    assert denied.returncode != 0
    assert "invalid MingCang agent API key" in denied.stderr

    allowed = _run_cli(
        repo,
        db_url,
        "health",
        "--api-key",
        "secret",
        env={
            "STOCKSAGE_AGENT_MODE": "remote",
            "STOCKSAGE_AGENT_API_KEY": "secret",
        },
    )

    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout)["ok"] is True


def test_agent_cli_global_api_key_can_appear_before_subcommand(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'remote-before-{uuid.uuid4().hex}.db'}"

    result = _run_cli(
        repo,
        db_url,
        "--api-key",
        "secret",
        "health",
        env={
            "STOCKSAGE_AGENT_MODE": "remote",
            "STOCKSAGE_AGENT_API_KEY": "secret",
        },
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True
