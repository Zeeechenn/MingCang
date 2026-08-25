from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.ops.one_loop_continuity import audit_one_loop_continuity

CARD_TYPES = (
    "batch_integrity",
    "candidate",
    "position_health",
    "event_risk",
    "watchtower",
    "daily_delta",
    "human_confirmation",
    "review_attribution",
)


def _init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            close REAL
        );
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            data_timestamp TEXT,
            run_id TEXT
        );
        CREATE TABLE job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            job_name TEXT,
            trigger_source TEXT,
            as_of TEXT,
            status TEXT,
            started_at TEXT,
            finished_at TEXT,
            input_coverage_json TEXT,
            degradation_reasons_json TEXT,
            output_summary_json TEXT,
            artifact_path TEXT,
            error TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _days(count: int, start: str = "2026-08-19") -> list[str]:
    base = date.fromisoformat(start)
    return [(base + timedelta(days=offset)).isoformat() for offset in range(count)]


def _seed_price(conn: sqlite3.Connection, day: str) -> None:
    conn.execute("INSERT INTO prices(symbol, date, close) VALUES (?, ?, ?)", ("000001", day, 10.0))


def _seed_signals(
    conn: sqlite3.Connection,
    day: str,
    *,
    batch_id: str | None = None,
    symbols: int = 2,
    run_id: str | None = None,
) -> str:
    batch = batch_id or f"{day}T22:00:00+08:00"
    for idx in range(symbols):
        conn.execute(
            "INSERT INTO signals(symbol, date, data_timestamp, run_id) VALUES (?, ?, ?, ?)",
            (f"00000{idx}", batch, day, run_id),
        )
    return batch


def _envelope(
    day: str,
    batch_id: str,
    artifact: str,
    *,
    entrypoint: str = "m63_postmarket",
    status: str = "complete",
    database: str = "configured",
    authoritative: bool = True,
    freshness_as_of: str | None = None,
    run_id: str | None = None,
    symbols: int = 2,
) -> dict[str, object]:
    return {
        "schema_version": "run_envelope.v1",
        "run_id": run_id or f"run-{day}",
        "batch_id": batch_id,
        "trade_date": day,
        "as_of": day,
        "scope": "daily",
        "entrypoint": entrypoint,
        "trigger_source": "scheduler",
        "status": status,
        "expected": {"symbols": symbols},
        "completed": {"symbols": symbols if status == "complete" else symbols - 1},
        "failed": {"symbols": 0 if status == "complete" else 1},
        "freshness": {
            "as_of": freshness_as_of or day,
            "input_coverage": {
                "database": database,
                "authoritative": authoritative,
                "batch_id": batch_id,
                "signal_batch_id": batch_id,
            },
        },
        "degradations": [],
        "artifacts": [artifact],
    }


def _seed_job(
    conn: sqlite3.Connection,
    day: str,
    envelope: dict[str, object],
    artifact: str,
    *,
    job_name: str = "m63_postmarket",
    row_status: str = "success",
) -> None:
    conn.execute(
        """
        INSERT INTO job_runs(
            run_id, job_name, trigger_source, as_of, status, started_at, finished_at,
            input_coverage_json, degradation_reasons_json, output_summary_json, artifact_path, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            envelope["run_id"],
            job_name,
            "scheduler",
            day,
            row_status,
            f"{day}T22:00:00",
            f"{day}T22:01:00",
            json.dumps({"run_envelope": envelope}),
            "[]",
            json.dumps({"run_envelope": envelope}),
            artifact,
            None,
        ),
    )


def _panel_work_metrics() -> dict[str, dict[str, object]]:
    return {
        "duplicate_suppression": {"status": "available", "evaluated": 1, "suppressed": 0},
        "human_review": {"status": "available", "required": 1, "completed": 1},
        "review_freshness": {"status": "available", "total": 1, "stale": 0},
        "failure_recovery": {"status": "available", "recovered": 0, "open_failures": 0},
    }


def _daily_panel_payload(
    day: str,
    panel_envelope: dict[str, object],
    *,
    schema_version: str = "daily_panel.v1",
    card_types: tuple[str, ...] = CARD_TYPES,
    run_identity: str = "match",
    work_metrics: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    run_envelope = {
        "run_id": panel_envelope["run_id"],
        "batch_id": panel_envelope["batch_id"],
    }
    if run_identity == "wrong":
        run_envelope = {"run_id": "wrong-run", "batch_id": "wrong-batch"}
    return {
        "schema_version": schema_version,
        "as_of": day,
        "status": "ready",
        "run_envelope": run_envelope,
        "ledger_commit_state": "committed",
        "cards": [
            {
                "card_type": card_type,
                "lifecycle": "stable",
                "status": "ready",
                "summary": card_type,
                "payload": {},
                "evidence_refs": [{"source_type": "test", "source_ref": card_type, "as_of": day}],
                "run_ref": {"run_id": panel_envelope["run_id"], "batch_id": panel_envelope["batch_id"], "as_of": day},
            }
            for card_type in card_types
        ],
        "work_metrics": work_metrics if work_metrics is not None else _panel_work_metrics(),
        "artifact_contract": {
            "schema_version": "daily_panel_artifact_contract.v1",
        },
    }


def _seed_complete_day(
    conn: sqlite3.Connection,
    repo_root: Path,
    day: str,
    *,
    envelope_status: str = "complete",
    batch_id: str | None = None,
    envelope_batch_id: str | None = None,
    database: str = "configured",
    authoritative: bool = True,
    freshness_as_of: str | None = None,
    panel_freshness_as_of: str | None = None,
    signal_freshness_as_of: str | None = None,
    signal_entrypoint: str = "test2_signal_runner",
    duplicate: bool = False,
    artifact_date: str | None = None,
    artifact_kind: str = "daily_panel_json",
    panel_schema_version: str = "daily_panel.v1",
    panel_card_types: tuple[str, ...] = CARD_TYPES,
    panel_run_identity: str = "match",
    panel_work_metrics: dict[str, dict[str, object]] | None = None,
) -> None:
    _seed_price(conn, day)
    signal_batch = _seed_signals(conn, day, batch_id=batch_id)
    suffix = ".md" if artifact_kind == "markdown_only" else ".json"
    artifact_path = repo_root / "panels" / f"panel-{day}{suffix}"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    panel_envelope = _envelope(
        day,
        f"m63_postmarket:{day}",
        str(artifact_path),
        entrypoint="m63_postmarket",
        status="complete",
        database=database,
        authoritative=authoritative,
        freshness_as_of=panel_freshness_as_of or freshness_as_of,
        run_id=f"panel-{day}",
    )
    if artifact_kind == "markdown_only":
        artifact_path.write_text(f"# Panel {artifact_date or day}\n", encoding="utf-8")
    else:
        panel_payload = _daily_panel_payload(
            artifact_date or day,
            panel_envelope,
            schema_version=panel_schema_version,
            card_types=panel_card_types,
            run_identity=panel_run_identity,
            work_metrics=panel_work_metrics,
        )
        artifact_path.write_text(json.dumps(panel_payload), encoding="utf-8")
    _seed_job(conn, day, panel_envelope, str(artifact_path), job_name="m63_postmarket")
    signal_envelope = _envelope(
        day,
        envelope_batch_id or signal_batch,
        str(artifact_path),
        entrypoint=signal_entrypoint,
        status=envelope_status,
        database=database,
        authoritative=authoritative,
        freshness_as_of=signal_freshness_as_of or freshness_as_of,
        run_id=f"signal-{day}",
    )
    _seed_job(conn, day, signal_envelope, str(artifact_path), job_name=signal_entrypoint)
    if duplicate:
        second = dict(signal_envelope)
        second["run_id"] = f"dupe-{day}"
        _seed_job(conn, day, second, str(artifact_path), job_name=signal_entrypoint)


def _audit(tmp_path: Path, days: list[str], **overrides):
    db_path = tmp_path / "audit.db"
    repo_root = tmp_path / "repo"
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    for day in days:
        _seed_complete_day(conn, repo_root, day, **overrides)
    conn.commit()
    conn.close()
    return audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )


def test_continuity_reports_insufficient_days_for_less_than_twenty(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(19))

    assert result["status"] == "insufficient_days"
    assert result["metrics"]["close_confirmed_days"] == 19
    assert result["metrics"]["recovery_blockers"]["insufficient_close_confirmed_days"] == 1


@pytest.mark.parametrize("signal_entrypoint", ["postmarket", "test2_signal_runner", "paper_trading.test2_signal_runner"])
def test_continuity_completes_on_exactly_twenty_clean_close_confirmed_days(
    tmp_path: Path,
    signal_entrypoint: str,
) -> None:
    result = _audit(tmp_path, _days(20), signal_entrypoint=signal_entrypoint)

    assert result["status"] == "complete"
    assert result["metrics"]["close_confirmed_days"] == 20
    assert result["metrics"]["ledger_coverage"] == {"complete": 20}
    assert result["metrics"]["batch_identity"] == {"matched": 20}
    assert result["metrics"]["artifact_panel_completeness"] == {"complete": 20}
    assert result["metrics"]["work_metrics"]["completeness_rate"]["value"] == 1.0
    assert result["metrics"]["work_metrics"]["duplicate_suppression_rate"]["status"] == "available"
    assert result["days"][0]["panel_envelope_batch_id"] == "m63_postmarket:2026-08-19"
    assert result["days"][0]["signal_envelope_batch_id"] == "2026-08-19T22:00:00+08:00"


def test_continuity_accepts_daily_panel_top_level_committed_ledger_state(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20))

    artifact_path = tmp_path / "repo" / "panels" / "panel-2026-08-19.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["status"] == "complete"
    assert payload["ledger_commit_state"] == "committed"
    assert payload["artifact_contract"]["schema_version"] == "daily_panel_artifact_contract.v1"


def test_continuity_fails_closed_on_partial_run_envelope(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), envelope_status="partial")

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["run_envelope"] == "complete"
    assert "missing_authoritative_signal_run" in result["days"][0]["blockers"]
    assert "excluded_signal_run:not_complete:1" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_duplicate_complete_runs(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), duplicate=True)

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["signal_run"] == "ambiguous"
    assert "ambiguous_authoritative_signal_run" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_signal_batch_mismatch(tmp_path: Path) -> None:
    result = _audit(
        tmp_path,
        _days(20),
        batch_id="2026-08-19T22:00:00+08:00",
        envelope_batch_id="2026-08-19T21:00:00+08:00",
    )

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["batch_envelope_match"] == "mismatched"
    assert "excluded_signal_run:mismatched_signal_batch:1" in result["days"][0]["blockers"]
    assert "missing_authoritative_signal_run" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_custom_database_run(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), database="custom")

    assert result["status"] == "incomplete"
    assert "missing_authoritative_complete_run" in result["days"][0]["blockers"]
    assert "missing_authoritative_signal_run" in result["days"][0]["blockers"]
    assert "excluded_run:non_authoritative_or_custom:1" in result["days"][0]["blockers"]
    assert "excluded_signal_run:non_authoritative_or_custom:1" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_non_authoritative_run(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), authoritative=False)

    assert result["status"] == "incomplete"
    assert "excluded_run:non_authoritative_or_custom:1" in result["days"][0]["blockers"]
    assert "excluded_signal_run:non_authoritative_or_custom:1" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_stale_freshness(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), freshness_as_of="2026-08-18")

    assert result["status"] == "incomplete"
    assert result["metrics"]["stale_count"] == 20
    assert "stale_freshness_as_of" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_stale_signal_freshness(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), signal_freshness_as_of="2026-08-18")

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["run_envelope"] == "complete"
    assert "missing_authoritative_signal_run" in result["days"][0]["blockers"]
    assert "excluded_signal_run:stale_signal_freshness_as_of:1" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_panel_artifact_date_mismatch(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), artifact_date="2026-08-18")

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["artifact_panel"] == "missing"
    assert "daily_panel_date_mismatch" in result["days"][0]["blockers"]


def test_continuity_fails_closed_on_markdown_only_panel_artifact(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), artifact_kind="markdown_only")

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["artifact_panel"] == "missing"
    assert "missing_daily_panel_json_artifact" in result["days"][0]["blockers"]


@pytest.mark.parametrize(
    ("overrides", "expected_blocker"),
    [
        ({"panel_schema_version": "legacy_panel.v1"}, "daily_panel_schema_mismatch"),
        ({"panel_card_types": CARD_TYPES[:-1]}, "daily_panel_card_types_mismatch"),
        ({"panel_run_identity": "wrong"}, "daily_panel_run_id_mismatch"),
    ],
)
def test_continuity_fails_closed_on_invalid_daily_panel_json(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_blocker: str,
) -> None:
    result = _audit(tmp_path, _days(20), **overrides)

    assert result["status"] == "incomplete"
    assert result["days"][0]["checks"]["artifact_panel"] == "missing"
    assert expected_blocker in result["days"][0]["blockers"]


def test_continuity_fails_closed_when_panel_work_metrics_are_missing(tmp_path: Path) -> None:
    result = _audit(tmp_path, _days(20), panel_work_metrics={})

    assert result["status"] == "incomplete"
    assert "missing_panel_work_metric:duplicate_suppression" in result["days"][0]["blockers"]
    assert result["metrics"]["work_metrics"]["duplicate_suppression_rate"]["status"] == "missing"
    assert result["metrics"]["recovery_blockers"]["blocking_work_metric_missing_or_unavailable"] == 1


def test_continuity_fails_closed_when_panel_work_metric_is_unavailable(tmp_path: Path) -> None:
    metrics = _panel_work_metrics()
    metrics["human_review"] = {"status": "unavailable", "reason": "queue_missing"}

    result = _audit(tmp_path, _days(20), panel_work_metrics=metrics)

    assert result["status"] == "incomplete"
    assert "unavailable_panel_work_metric:human_review" in result["days"][0]["blockers"]
    assert result["metrics"]["work_metrics"]["human_review_rate"]["status"] == "missing"
    assert result["metrics"]["recovery_blockers"]["blocking_work_metric_missing_or_unavailable"] == 1


def test_continuity_zero_denominator_work_metrics_are_not_applicable_not_zero(tmp_path: Path) -> None:
    result = _audit(
        tmp_path,
        _days(20),
        panel_work_metrics={
            "duplicate_suppression": {"status": "available", "evaluated": 0, "suppressed": 0},
            "human_review": {"status": "available", "required": 0, "completed": 0},
            "review_freshness": {"status": "available", "total": 0, "stale": 0},
            "failure_recovery": {"status": "available", "recovered": 0, "open_failures": 0},
        },
    )

    assert result["status"] == "complete"
    work = result["metrics"]["work_metrics"]
    assert work["duplicate_suppression_rate"]["status"] == "not_applicable"
    assert work["duplicate_suppression_rate"]["value"] is None
    assert work["human_review_rate"]["status"] == "not_applicable"
    assert work["human_review_rate"]["value"] is None
    assert work["review_freshness"]["status"] == "not_applicable"
    assert work["review_freshness"]["value"] is None


@pytest.mark.parametrize("ledger_commit_state", [None, "pending"])
def test_continuity_fails_closed_when_daily_panel_ledger_commit_state_missing_or_pending(
    tmp_path: Path,
    ledger_commit_state: str | None,
) -> None:
    result = _audit(tmp_path, _days(20), panel_schema_version="daily_panel.v1")
    assert result["status"] == "complete"

    # Patch one artifact after seeding to simulate a missing or pending pre-commit file.
    artifact_path = tmp_path / "repo" / "panels" / "panel-2026-08-19.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if ledger_commit_state is None:
        payload.pop("ledger_commit_state", None)
    else:
        payload["ledger_commit_state"] = ledger_commit_state
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    rerun = audit_one_loop_continuity(
        db_path=tmp_path / "audit.db",
        implementation_since="2026-08-19",
        repo_root=tmp_path / "repo",
    )

    assert rerun["status"] == "incomplete"
    assert "daily_panel_ledger_commit_state_not_committed" in rerun["days"][0]["blockers"]


def test_continuity_cli_prints_json_without_default_file_write(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    repo_root = tmp_path / "repo"
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    for day in _days(20):
        _seed_complete_day(conn, repo_root, day)
    conn.commit()
    conn.close()

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/audit_one_loop_continuity.py",
            "--db",
            str(db_path),
            "--implementation-since",
            "2026-08-19",
            "--repo-root",
            str(repo_root),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["status"] == "complete"
    assert not (tmp_path / "one_loop_continuity.json").exists()


def _seed_days(tmp_path: Path, days: list[str]) -> tuple[Path, Path, sqlite3.Connection]:
    db_path = tmp_path / "audit.db"
    repo_root = tmp_path / "repo"
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    for day in days:
        _seed_complete_day(conn, repo_root, day)
    return db_path, repo_root, conn


def test_continuity_resolves_duplicate_batches_by_explicit_run_binding(tmp_path: Path) -> None:
    """An untracked rerun on the same date must not cost the day when the
    authoritative batch names its owning run."""
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ?",
        (f"signal-{days[0]}", days[0]),
    )
    _seed_signals(conn, days[0], batch_id=f"{days[0]}T23:30:00+08:00")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert first_day["checks"]["signal_batch_identity"] == "unique_by_run_id"
    assert first_day["status"] == "complete"
    assert result["status"] == "complete"


def test_continuity_still_fails_closed_on_duplicate_batches_without_run_binding(tmp_path: Path) -> None:
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    _seed_signals(conn, days[0], batch_id=f"{days[0]}T23:30:00+08:00")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert first_day["checks"]["signal_batch_identity"] == "ambiguous"
    assert "ambiguous_signal_batches" in first_day["blockers"]
    assert result["status"] == "incomplete"


def test_continuity_rejects_a_batch_bound_to_a_different_run(tmp_path: Path) -> None:
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ?",
        ("some-other-run", days[0]),
    )
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert "missing_authoritative_signal_run" in first_day["blockers"]
    assert result["status"] == "incomplete"


def test_continuity_reads_legacy_signals_tables_without_a_run_id_column(tmp_path: Path) -> None:
    """Rows written before the migration keep the date-matching path."""
    days = _days(20)
    db_path = tmp_path / "legacy.db"
    repo_root = tmp_path / "repo"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, date TEXT, close REAL
        );
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, date TEXT, data_timestamp TEXT
        );
        CREATE TABLE job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, job_name TEXT, trigger_source TEXT,
            as_of TEXT, status TEXT, started_at TEXT, finished_at TEXT, input_coverage_json TEXT,
            degradation_reasons_json TEXT, output_summary_json TEXT, artifact_path TEXT, error TEXT
        );
        """
    )
    for day in days:
        _seed_price(conn, day)
        batch = f"{day}T22:00:00+08:00"
        for idx in range(2):
            conn.execute(
                "INSERT INTO signals(symbol, date, data_timestamp) VALUES (?, ?, ?)",
                (f"00000{idx}", batch, day),
            )
        artifact_path = repo_root / "panels" / f"panel-{day}.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        panel_envelope = _envelope(
            day, f"m63_postmarket:{day}", str(artifact_path), run_id=f"panel-{day}"
        )
        artifact_path.write_text(json.dumps(_daily_panel_payload(day, panel_envelope)), encoding="utf-8")
        _seed_job(conn, day, panel_envelope, str(artifact_path), job_name="m63_postmarket")
        signal_envelope = _envelope(
            day, batch, str(artifact_path), entrypoint="test2_signal_runner", run_id=f"signal-{day}"
        )
        _seed_job(conn, day, signal_envelope, str(artifact_path), job_name="test2_signal_runner")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    assert result["days"][0]["checks"]["signal_batch_identity"] == "unique"
    assert result["status"] == "complete"


def test_continuity_rejects_a_partly_stamped_batch(tmp_path: Path) -> None:
    """Half tracked, half untracked is a mixture, not an attributable batch."""
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ? AND symbol = ?",
        (f"signal-{days[0]}", days[0], "000000"),
    )
    _seed_signals(conn, days[0], batch_id=f"{days[0]}T23:30:00+08:00")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert first_day["checks"]["signal_batch_identity"] == "ambiguous"
    assert result["status"] == "incomplete"


def test_continuity_rejects_a_panel_run_that_declares_it_ran_before_the_close(tmp_path: Path) -> None:
    """A postmarket run executed mid-session describes the previous session."""
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    row = conn.execute(
        "SELECT output_summary_json FROM job_runs WHERE job_name='m63_postmarket' AND as_of=?",
        (days[0],),
    ).fetchone()
    payload = json.loads(row[0])
    payload["run_envelope"]["freshness"]["close_confirmed"] = False
    conn.execute(
        "UPDATE job_runs SET output_summary_json=? WHERE job_name='m63_postmarket' AND as_of=?",
        (json.dumps(payload), days[0]),
    )
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert "missing_authoritative_complete_run" in first_day["blockers"]
    assert "excluded_run:panel_run_not_close_confirmed:1" in first_day["blockers"]
    assert result["status"] == "incomplete"


def test_continuity_rejects_a_panel_artifact_marked_not_close_confirmed(tmp_path: Path) -> None:
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    conn.commit()
    conn.close()
    artifact = repo_root / "panels" / f"panel-{days[0]}.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["artifact_contract"]["close_confirmed"] = False
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    assert "daily_panel_not_close_confirmed" in result["days"][0]["blockers"]
    assert result["status"] == "incomplete"


def test_continuity_counts_a_day_whose_pre_close_run_was_superseded(tmp_path: Path) -> None:
    """Expected pre-close residue is a note, not a reason to withhold the day."""
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    row = conn.execute(
        "SELECT output_summary_json, artifact_path FROM job_runs "
        "WHERE job_name='m63_postmarket' AND as_of=?",
        (days[0],),
    ).fetchone()
    superseded = json.loads(row[0])
    superseded["run_envelope"]["freshness"]["close_confirmed"] = False
    superseded["run_envelope"]["run_id"] = f"pre-close-{days[0]}"
    conn.execute(
        """
        INSERT INTO job_runs(
            run_id, job_name, trigger_source, as_of, status, started_at, finished_at,
            input_coverage_json, degradation_reasons_json, output_summary_json, artifact_path, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"pre-close-{days[0]}",
            "m63_postmarket",
            "manual_cli",
            days[0],
            "success",
            f"{days[0]}T12:00:00",
            f"{days[0]}T12:01:00",
            json.dumps(superseded),
            "[]",
            json.dumps(superseded),
            row[1],
            None,
        ),
    )
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert first_day["blockers"] == []
    assert first_day["notes"] == ["excluded_run:panel_run_not_close_confirmed:1"]
    assert first_day["status"] == "complete"
    assert result["status"] == "complete"


def test_continuity_ignores_non_authoritative_research_reruns(tmp_path: Path) -> None:
    """The live-track sweep and subset deep-eval are reruns, not the day's batch.

    The signal runner marks any non-default universe non-authoritative, so the
    daily test-running routine (test2 25-name pool, then a live-track sweep over
    its own universe) must still leave exactly one official batch.
    """
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ?",
        (f"signal-{days[0]}", days[0]),
    )
    _seed_signals(conn, days[0], batch_id=f"{days[0]}T15:32+08:00", run_id="live-track-run")
    sweep = _envelope(
        days[0],
        f"{days[0]}T15:32+08:00",
        "sweep",
        entrypoint="test2_signal_runner",
        run_id="live-track-run",
        authoritative=False,
    )
    _seed_job(conn, days[0], sweep, "sweep", job_name="test2_signal_runner")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert first_day["checks"]["signal_batch_identity"] == "unique"
    assert first_day["blockers"] == []
    assert "non_authoritative_signal_batches:1" in first_day["notes"]
    # the rerun stays visible in the evidence, it is only excluded from identity
    assert [batch["authoritative"] for batch in first_day["signal_batches"]] == [False, True]
    assert result["status"] == "complete"


def test_continuity_fails_closed_when_only_a_research_rerun_exists(tmp_path: Path) -> None:
    """Dropping reruns must not invent an official batch that never ran."""
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ?",
        ("live-track-run", days[0]),
    )
    sweep = _envelope(
        days[0],
        f"{days[0]}T22:00:00+08:00",
        "sweep",
        entrypoint="test2_signal_runner",
        run_id="live-track-run",
        authoritative=False,
    )
    conn.execute("DELETE FROM job_runs WHERE job_name='test2_signal_runner' AND as_of=?", (days[0],))
    _seed_job(conn, days[0], sweep, "sweep", job_name="test2_signal_runner")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert "missing_signal_batch" in first_day["blockers"]
    assert result["status"] == "incomplete"


def _seed_failed_rerun(
    conn: sqlite3.Connection,
    repo_root: Path,
    day: str,
    *,
    run_id: str,
    batch_time: str,
) -> None:
    """An earlier attempt that lost its data source mid-batch and said so."""
    batch = _seed_signals(
        conn, day, batch_id=f"{day}T{batch_time}+08:00", symbols=1, run_id=run_id
    )
    envelope = _envelope(
        day,
        batch,
        str(repo_root / "panels" / f"panel-{day}.json"),
        entrypoint="test2_signal_runner",
        status="incomplete",
        run_id=run_id,
    )
    _seed_job(
        conn, day, envelope, str(repo_root / "panels" / f"panel-{day}.json"),
        job_name="test2_signal_runner",
    )


def test_continuity_lets_a_self_reported_failed_batch_yield_to_the_complete_one(
    tmp_path: Path,
) -> None:
    """数据源故障后重跑是常态（2026-08-25 连跑三轮才 25/25）。

    先前那轮自己在 envelope 里写了 failed>0，它是被取代的残留，不该和达标批次
    并列竞争当天的官方批次，把一扇实际已锁上的门报成断的。
    """
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    day = days[0]
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ?",
        (f"signal-{day}", day),
    )
    _seed_failed_rerun(conn, repo_root, day, run_id=f"failed-{day}", batch_time="16:29:00")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert "superseded_signal_batches:1" in first_day["notes"]
    assert first_day["checks"]["signal_batch_identity"] == "unique"
    assert first_day["blockers"] == []
    assert first_day["status"] == "complete"


def test_continuity_still_fails_closed_when_every_batch_reported_failure(
    tmp_path: Path,
) -> None:
    """不放水的边界：当天没有任何一轮达标时，排除逻辑必须整个让开。

    否则「全都没跑完」会被误读成「有一个干净批次」，门就被凭空放行了。
    """
    days = _days(20)
    db_path, repo_root, conn = _seed_days(tmp_path, days)
    day = days[0]
    conn.execute(
        "UPDATE signals SET run_id = ? WHERE data_timestamp = ?",
        (f"signal-{day}", day),
    )
    # 当天唯一那轮也自报未达标
    row = conn.execute(
        "SELECT output_summary_json FROM job_runs WHERE run_id = ?", (f"signal-{day}",)
    ).fetchone()
    envelope = json.loads(row[0])["run_envelope"]
    envelope["status"] = "incomplete"
    envelope["completed"] = {"symbols": 1}
    envelope["failed"] = {"symbols": 1}
    conn.execute(
        "UPDATE job_runs SET output_summary_json = ?, input_coverage_json = ? WHERE run_id = ?",
        (
            json.dumps({"run_envelope": envelope}),
            json.dumps({"run_envelope": envelope}),
            f"signal-{day}",
        ),
    )
    _seed_failed_rerun(conn, repo_root, day, run_id=f"failed-{day}", batch_time="16:29:00")
    conn.commit()
    conn.close()

    result = audit_one_loop_continuity(
        db_path=db_path,
        implementation_since=days[0],
        repo_root=repo_root,
    )

    first_day = result["days"][0]
    assert "superseded_signal_batches:1" not in first_day["notes"]
    assert first_day["status"] == "incomplete"
    assert result["status"] == "incomplete"
