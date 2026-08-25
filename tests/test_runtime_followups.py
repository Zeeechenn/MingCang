from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.audit_runtime_followups import audit_runtime_followups


def _db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE job_runs(
            run_id TEXT, job_name TEXT, status TEXT, as_of TEXT,
            started_at TEXT, finished_at TEXT, error TEXT
        );
        CREATE TABLE degradation_events(
            id INTEGER PRIMARY KEY, ts TEXT, component TEXT, category TEXT,
            provider TEXT, error TEXT, context_json TEXT
        );
        INSERT INTO job_runs VALUES
          ('stale-1', 'm63_postmarket', 'running', '2026-08-24', '2026-08-25 08:00:00', NULL, NULL),
          ('fresh-1', 'm63_postmarket', 'running', '2026-08-25', '2026-08-25 17:30:00', NULL, NULL),
          ('done-1', 'm63_postmarket', 'success', '2026-08-25', '2026-08-25 08:00:00', '2026-08-25 08:05:00', NULL);
        INSERT INTO degradation_events VALUES
          (1, '2026-08-24 10:00:00', 'market', 'adjustment_basis_drift', 'ifind', 'drift', '{"symbol":"600547"}'),
          (2, '2026-08-25 10:00:00', 'market', 'adjustment_basis_drift', 'ifind', 'drift', '{"symbol":"600547"}'),
          (3, '2026-08-25 11:00:00', 'market', 'adjustment_basis_drift', 'ifind', 'drift', '{}');
        """
    )
    connection.commit()
    connection.close()
    return path


def _continuity(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "status": "incomplete",
                "metrics": {
                    "work_metrics": {
                        "degradation_rate": {
                            "status": "available",
                            "value": 0.5,
                            "evidence": {"degradation_days": 1, "close_confirmed_days": 2},
                        },
                        "human_review_rate": {"status": "available", "value": 0.75},
                        "review_freshness": {"status": "available", "value": 0.6},
                    }
                },
                "days": [
                    {
                        "date": "2026-08-24",
                        "degradations": ["--no-llm: planned", "unexpected provider timeout"],
                        "panel_work_metrics": {
                            "human_review": {"status": "available", "required": 4, "completed": 3},
                            "review_freshness": {"status": "available", "total": 5, "stale": 2},
                        },
                    },
                    {
                        "date": "2026-08-25",
                        "degradations": ["--no-shadow"],
                        "panel_work_metrics": {
                            "human_review": {"status": "available", "required": 2, "completed": 2},
                            "review_freshness": {"status": "available", "total": 6, "stale": 1},
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_runtime_followups_is_read_only_and_separates_evidence(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "audit.sqlite")
    continuity_path = _continuity(tmp_path / "continuity.json")

    result = audit_runtime_followups(
        db_path=db_path,
        continuity_path=continuity_path,
        stale_running_hours=6,
        as_of="2026-08-25 18:00:00",
    )

    assert result["database"]["mode"] == "ro&immutable=1"
    assert [row["run_id"] for row in result["stale_running"]["jobs"]] == ["stale-1"]
    drift = result["adjustment_basis_drift"]
    assert drift["event_count"] == 3
    assert drift["by_symbol"][0]["symbol"] == "600547"
    assert drift["by_symbol"][0]["count"] == 2
    assert drift["unknown_symbol_count"] == 1

    degradation = result["continuity"]["degradations"]
    assert degradation["contract_degradation_rate"]["value"] == 0.5
    assert degradation["intentional_skips"] == {"--no-llm: planned": 1, "--no-shadow": 1}
    assert degradation["unexpected_degradations"] == {"unexpected provider timeout": 1}

    reviews = result["continuity"]["review_evidence"]
    assert reviews["human_review"]["observation_days"] == 2
    assert reviews["review_freshness"]["observation_days"] == 2
    assert "cross-day backlog observations" in reviews["review_freshness"]["semantics"]
    assert "not a unique task count" in reviews["review_freshness"]["semantics"]

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 3


def test_runtime_followups_cli_requires_explicit_db_and_accepts_cwd_outside_repo(
    tmp_path: Path,
) -> None:
    db_path = _db(tmp_path / "audit.sqlite")
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_runtime_followups.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--db", str(db_path), "--as-of", "2026-08-25"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "runtime_followups.v1"
    assert payload["continuity"]["available"] is False

    missing = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True
    )
    assert missing.returncode != 0


@pytest.mark.parametrize("sidecar_suffix", ["-wal", "-shm"])
def test_runtime_followups_rejects_active_wal_db(tmp_path: Path, sidecar_suffix: str) -> None:
    db_path = _db(tmp_path / "audit.sqlite")
    sidecar_path = db_path.with_name(db_path.name + sidecar_suffix)
    sidecar_path.write_bytes(b"")

    with pytest.raises(ValueError) as excinfo:
        audit_runtime_followups(db_path=db_path, as_of="2026-08-25 18:00:00")

    message = str(excinfo.value)
    assert "sqlite_consistent_snapshot" in message
    assert "-wal/-shm" in message


@pytest.mark.parametrize("sidecar_suffix", ["-wal", "-shm"])
def test_runtime_followups_cli_rejects_active_wal_db(
    tmp_path: Path, sidecar_suffix: str
) -> None:
    db_path = _db(tmp_path / "audit.sqlite")
    sidecar_path = db_path.with_name(db_path.name + sidecar_suffix)
    sidecar_path.write_bytes(b"")
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_runtime_followups.py"

    proc = subprocess.run(
        [sys.executable, str(script), "--db", str(db_path), "--as-of", "2026-08-25"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "sqlite_consistent_snapshot" in proc.stderr


def test_runtime_followups_allow_live_db_bypasses_wal_check(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "audit.sqlite")
    wal_path = db_path.with_name(db_path.name + "-wal")
    wal_path.write_bytes(b"")

    result = audit_runtime_followups(
        db_path=db_path,
        as_of="2026-08-25 18:00:00",
        allow_live_db=True,
    )

    assert result["schema_version"] == "runtime_followups.v1"


def test_runtime_followups_cli_allow_live_db_bypasses_wal_check(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "audit.sqlite")
    wal_path = db_path.with_name(db_path.name + "-wal")
    wal_path.write_bytes(b"")
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_runtime_followups.py"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--db",
            str(db_path),
            "--as-of",
            "2026-08-25",
            "--allow-live-db",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "runtime_followups.v1"
