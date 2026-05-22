from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path


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
    assert "invalid StockSage agent API key" in denied.stderr

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
