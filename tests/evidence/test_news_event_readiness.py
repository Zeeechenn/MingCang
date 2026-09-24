import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from backend.evidence import news_event_readiness as audit


def _db(path: Path, *, full: bool = True) -> None:
    with sqlite3.connect(path) as conn:
        if not full:
            conn.execute("CREATE TABLE unrelated (id INTEGER)")
            return
        conn.executescript(
            """
            CREATE TABLE news_shadow_runs (
                run_id TEXT, symbol TEXT, as_of TEXT, status TEXT, created_at TEXT,
                attribution_json TEXT, trigger_reasons_json TEXT, tokens_spent INTEGER,
                evidence_json TEXT, degradation_flags_json TEXT, profile TEXT
            );
            CREATE TABLE news_shadow_feedback (
                run_id TEXT, created_at TEXT, category TEXT, evidence_ref TEXT
            );
            CREATE TABLE news (
                id INTEGER, published_at TEXT, fetched_at TEXT, content TEXT
            );
            """
        )
        valid_card = json.dumps({"main_cause": "company_event", "timeline": []})
        manifests = json.dumps({"items": [{"published_at": "2026-09-10T12:00:00"}, {"published_at": "2026-09-11T12:00:00"}]})
        rows = [
            ("r1", "A", "2026-09-10", "evidence", "2026-09-10T12:00:00", valid_card, "[]", 0, manifests, "[]", "production_mirror"),
            ("r2", "B", "2026-09-10", "evidence", "2026-09-10T12:00:00", None, "[]", None, '{"bad":', '["PYRAMID_NOT_TRIGGERED"]', "production_mirror"),
            ("r3", "C", "2026-09-10", "evidence", "2026-09-10T12:00:00", "{\"main_cause\":\"company_event\",\"timeline\":[]}", "[]", -1, "{}", "[\"PYRAMID_NOT_TRIGGERED\"]", "production_mirror"),
            ("r4", "D", "2026-09-10", "evidence", "2026-09-11T00:01:00", "{\"main_cause\":\"policy\",\"timeline\":[]}", "[]", "nan", "{}", "[]", "production_mirror"),
            ("future", "E", "2026-09-11", "evidence", "2026-09-11T10:00:00", valid_card, "[]", 20, "{}", "[]", "production_mirror"),
        ]
        conn.executemany("INSERT INTO news_shadow_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.executemany(
            "INSERT INTO news VALUES (?,?,?,?)",
            [
                (1, "2026-09-09T10:00:00", "2026-09-09T10:10:00", "body"),
                (2, "2026-09-09T10:00:00", "2026-09-11T10:10:00", "late body"),
                (3, "2026-09-10T10:00:00", None, "unknown fetch"),
                (4, "2026-09-11T10:00:00", "2026-09-11T10:10:00", "future body"),
                (5, "2026-09-09T10:00:00", "2026-09-09T10:10:00", "   "),
                (6, "not-a-date", "2026-09-09T10:10:00", "unknown published date"),
            ],
        )
        conn.executemany(
            "INSERT INTO news_shadow_feedback VALUES (?,?,?,?)",
            [("r1", "2026-09-11T09:00:00", "ok", "ref"), ("r4", "2026-09-09T09:00:00", "earlier", "ref")],
        )


def test_empty_and_missing_tables_degrade_without_failure(tmp_path):
    empty = tmp_path / "empty.db"
    _db(empty, full=False)
    with sqlite3.connect(f"file:{empty}?mode=ro&immutable=1", uri=True) as conn:
        report = audit.build_readiness(conn, as_of="2026-09-10")
    assert report["news_shadow_runs"]["eligible_as_of_count"] == 0
    assert report["gates"]["event_risk"]["data"]["status"] == "blocked"
    assert report["gates"]["direction"]["status"] == "blocked"


def test_asof_trigger_cost_pit_feedback_and_nonpromotion(tmp_path):
    db_path = tmp_path / "audit.db"
    _db(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        report = audit.build_readiness(conn, as_of="2026-09-10", snapshot_sha256=before)

    runs = report["news_shadow_runs"]
    assert runs["all_history_count"] == 5
    assert runs["eligible_as_of_count"] == 4
    assert runs["future_runs_excluded"] == 1
    assert runs["eligible_rows_created_after_as_of_boundary"] == 1
    assert runs["actually_available_by_as_of_count"] == 3
    assert runs["scored_evidence_denominator"] == 3
    assert runs["evidence_denominator_cohort"] == "actually_available_by_as_of_count"
    assert (runs["triggered"], runs["untriggered"], runs["trigger_unknown"]) == (1, 1, 1)
    assert runs["trigger_fraction"] == 1 / 3
    assert runs["tokens_spent_known_sum_informational_only"] == 0
    assert runs["tokens_spent_unknown_row_count"] == 1
    assert runs["tokens_spent_invalid_row_count"] == 1
    assert runs["tokens_spent_historical_known_sum_informational_only"] == 0
    assert runs["status_counts_as_of"] == {"evidence": 3}
    assert runs["status_counts_eligible_historical"] == {"evidence": 4}
    assert report["news_coverage"]["future_rows_excluded"] == 1
    assert report["news_coverage"]["published_time_unknown_excluded"] == 1
    assert report["news_coverage"]["rows_with_unknown_fetch_time_excluded"] == 1
    assert report["news_coverage"]["rows_fetched_after_as_of_excluded"] == 1
    assert report["news_coverage"]["body_present_rows"] == 1
    assert report["shadow_manifest_pit"]["future_items_excluded"] == 1
    assert report["shadow_manifest_pit"]["total_item_count_unknown"] is True
    assert report["shadow_manifest_pit"]["coverage"] is None
    assert report["feedback"]["future_feedback_excluded"] == 1
    assert report["feedback"]["eligible_as_of_run_count"] == 0
    assert report["feedback"]["eligible_historical_run_count"] == 1
    assert report["feedback"]["actually_available_feedback_count"] == 0
    assert report["feedback"]["status_counts"] == {}
    assert report["feedback"]["evidence_ref_count"] == 0
    assert "no_feedback_for_as_of_run_cohort" in report["gates"]["event_risk"]["review"]["reasons"]
    assert report["schema_version"] == "news_event_readiness.v2"
    gates = report["gates"]["event_risk"]
    assert gates["data"]["status"] == "unknown"
    assert gates["review"]["status"] == "unknown"
    assert gates["cost"]["status"] == "unknown"
    assert gates["readiness"] == "blocked"
    assert report["gates"]["direction"]["direction_weights_allowed"] is False
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_late_or_unknown_created_runs_cannot_refresh_or_enter_asof_metrics(tmp_path):
    db_path = tmp_path / "availability.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE news_shadow_runs (
                   run_id TEXT, as_of TEXT, status TEXT, created_at TEXT,
                   attribution_json TEXT, degradation_flags_json TEXT,
                   tokens_spent INTEGER, evidence_json TEXT
               )"""
        )
        valid_card = json.dumps({"main_cause": "company_event", "timeline": []})
        conn.executemany(
            "INSERT INTO news_shadow_runs VALUES (?,?,?,?,?,?,?,?)",
            [
                ("old", "2026-09-01", "verified_no_news", "2026-09-01T12:00:00", None, "[]", 2, None),
                ("late-failure", "2026-09-10", "score_failed", "2026-09-11T09:00:00", None, "[]", 99, None),
                ("unknown-created", "2026-09-10", "evidence", None, valid_card, "[]", 50, "{}"),
            ],
        )
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        report = audit.build_readiness(conn, as_of="2026-09-10", max_staleness_days=7)

    runs = report["news_shadow_runs"]
    assert runs["eligible_as_of_count"] == 3
    assert runs["actually_available_by_as_of_count"] == 1
    assert runs["eligible_rows_created_after_as_of_boundary"] == 1
    assert runs["eligible_rows_created_at_unknown"] == 1
    assert runs["unavailable_eligible_count"] == 2
    assert runs["latest_eligible_as_of"] == "2026-09-10"
    assert runs["latest_available_as_of"] == "2026-09-01"
    assert runs["freshness_age_days"] == 9
    assert runs["failed_run_count"] == 0
    assert runs["eligible_historical_failed_run_count"] == 1
    assert runs["status_counts_as_of"] == {"verified_no_news": 1}
    assert runs["status_counts_eligible_historical"] == {
        "evidence": 1, "score_failed": 1, "verified_no_news": 1
    }
    assert runs["scored_evidence_denominator"] == 0
    assert runs["tokens_spent_known_sum_informational_only"] == 2
    assert runs["tokens_spent_known_row_count"] == 1
    assert runs["tokens_spent_historical_known_sum_informational_only"] == 151
    assert report["gates"]["event_risk"]["runtime"]["status"] == "blocked"
    assert "latest_run_is_stale" in report["gates"]["event_risk"]["runtime"]["reasons"]
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_missing_created_at_column_is_unavailable_for_asof_metrics():
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE news_shadow_runs (run_id TEXT, as_of TEXT, status TEXT, tokens_spent INTEGER)")
        conn.execute("INSERT INTO news_shadow_runs VALUES ('unknown-created','2026-09-10','evidence',40)")
        report = audit.build_readiness(conn, as_of="2026-09-10")

    runs = report["news_shadow_runs"]
    assert runs["eligible_as_of_count"] == 1
    assert runs["eligible_rows_created_at_unknown"] == 1
    assert runs["actually_available_by_as_of_count"] == 0
    assert runs["scored_evidence_denominator"] == 0
    assert runs["tokens_spent_known_row_count"] == 0
    assert runs["tokens_spent_historical_known_sum_informational_only"] == 40
    assert report["gates"]["event_risk"]["runtime"]["status"] == "blocked"
    assert "run_created_at_unknown_availability" in report["gates"]["event_risk"]["data"]["reasons"]


def test_missing_columns_are_unknown_not_zero(tmp_path):
    db_path = tmp_path / "partial.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE news_shadow_runs (run_id TEXT, as_of TEXT, status TEXT, created_at TEXT)")
        conn.execute("INSERT INTO news_shadow_runs VALUES ('old','2020-01-01','evidence','2020-01-01T12:00:00')")
        conn.execute("CREATE TABLE news (published_at TEXT)")
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        report = audit.build_readiness(conn, as_of="2026-09-10")
    assert report["news_coverage"]["body_coverage"] is None
    assert report["news_coverage"]["eligible_as_of_row_count"] is None
    assert report["news_shadow_runs"]["trigger_unknown"] == 1
    assert report["news_shadow_runs"]["freshness_age_days"] > 7
    assert report["gates"]["event_risk"]["runtime"]["status"] == "blocked"


def test_manifest_fixed_denominator_includes_missing_timestamp_and_future_item(tmp_path):
    db_path = tmp_path / "manifest.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE news_shadow_runs (as_of TEXT, status TEXT, created_at TEXT, evidence_json TEXT)")
        conn.execute(
            "INSERT INTO news_shadow_runs VALUES (?,?,?,?)",
            (
                "2026-09-10",
                "evidence",
                "2026-09-10T12:00:00",
                json.dumps({"items": [
                    {"published_at": "2026-09-10T10:00:00"},
                    {"title": "missing timestamp"},
                    {"published_at": "2026-09-11T10:00:00"},
                ]}),
            ),
        )
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        report = audit.build_readiness(conn, as_of="2026-09-10")
    manifest = report["shadow_manifest_pit"]
    assert manifest["item_count"] == 3
    assert manifest["items_on_or_before_each_run_day"] == 1
    assert manifest["future_items_excluded"] == 1
    assert manifest["parse_or_timestamp_unknown_count"] == 1
    assert manifest["coverage"] == 1 / 3


def test_cli_readonly_and_output_guard(tmp_path):
    db_path = tmp_path / "snapshot.db"
    _db(db_path, full=False)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    output = tmp_path / "report.json"
    command = [
        sys.executable, "-m", "backend.evidence.news_event_readiness",
        "--db", str(db_path), "--as-of", "2026-09-10", "--output", str(output),
    ]
    import os
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["scope"]["writes_database"] is False
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    blocked = subprocess.run(command[:-1] + [str(db_path)], capture_output=True, text=True, env=env)
    assert blocked.returncode == 2
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_output_guard_rejects_hardlink_without_touching_snapshot(tmp_path):
    db_path = tmp_path / "source.db"
    _db(db_path, full=False)
    hardlink = tmp_path / "alias.json"
    hardlink.hardlink_to(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    try:
        audit._validate_paths(db_path, hardlink, output_format="json")
    except ValueError as exc:
        assert "hard link" in str(exc)
    else:
        raise AssertionError("snapshot hardlink must be rejected")
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_output_guard_rejects_wal_snapshot_and_preserves_existing_output(tmp_path):
    db_path = tmp_path / "source.db"
    _db(db_path, full=False)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    output = tmp_path / "report.json"
    output.write_text("keep", encoding="utf-8")
    Path(str(db_path) + "-wal").write_bytes(b"uncheckpointed")
    try:
        audit._validate_paths(db_path, output, output_format="json")
    except ValueError as exc:
        assert "WAL" in str(exc)
    else:
        raise AssertionError("non-empty WAL must be rejected")
    Path(str(db_path) + "-wal").unlink()
    try:
        audit._validate_paths(db_path, output, output_format="json")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("existing report must be preserved")
    assert output.read_text(encoding="utf-8") == "keep"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
