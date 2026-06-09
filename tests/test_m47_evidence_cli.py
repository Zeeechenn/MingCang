from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path


def test_evidence_lookahead_cli_runs_read_only_on_demo_data(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'm47-demo-{uuid.uuid4().hex}.db'}"
    env = {
        "PYTHONPATH": str(repo),
        "DATABASE_URL": db_url,
        "STOCKSAGE_AGENT_MODE": "local",
    }

    seed = subprocess.run(
        [sys.executable, "scripts/demo_seed.py"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert seed.returncode == 0, seed.stderr

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.agent.cli",
            "evidence",
            "lookahead-check",
            "--demo",
            "--pretty",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "m47_lookahead_standing_check.v1"
    assert payload["source_audit_schema_version"] == "m46_5_lookahead_one_time_audit.v1"
    assert payload["milestone"] == "M47"
    assert payload["productized_cli"] is True
    assert payload["standing_check"] is True
    assert payload["demo_mode"] is True
    assert payload["writes_db"] is False
    assert payload["calls_llm_or_api"] is False
    assert payload["promotion_impact"] == "none"
    assert payload["read_contract"]["blocked_auto_promotion"] is False
    assert payload["status"] in {"pass", "warning", "blocked"}
