import json
import sqlite3


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _artifact(path, *, exit_days, end="2026-05-29"):
    return _write_json(
        path,
        {
            "generated_at": "2026-06-01T00:00:00Z",
            "run_mode": "offline_read_only_forward_shadow_rolling",
            "production_unchanged": True,
            "writes_db": False,
            "calls_llm_or_api": False,
            "saves_model": False,
            "start": "2026-04-01",
            "end": end,
            "exit_days": exit_days,
        },
    )


def _artifacts(tmp_path, *, end="2026-05-29"):
    return [
        _artifact(tmp_path / f"m29_forward_shadow_rolling_20260401_{end.replace('-', '')}_{exit_days}d.json",
                  exit_days=exit_days, end=end)
        for exit_days in (1, 3, 5)
    ]


def _price_db(path, symbols, dates, *, missing_provenance_dates=None):
    missing_provenance_dates = set(missing_provenance_dates or [])
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE prices (
                symbol TEXT,
                date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                source TEXT,
                fetched_at TEXT,
                adjustment TEXT
            )
            """
        )
        rows = []
        for date in dates:
            source = "unit_provider"
            fetched_at = "2026-06-01T00:00:00"
            adjustment = "qfq"
            if date in missing_provenance_dates:
                source = ""
                fetched_at = ""
                adjustment = ""
            rows.extend(
                (symbol, date, 10.0, 11.0, 9.0, 10.5, 1000.0, source, fetched_at, adjustment)
                for symbol in symbols
            )
        conn.executemany(
            """
            INSERT INTO prices
              (symbol, date, open, high, low, close, volume, source, fetched_at, adjustment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_readiness_blocks_without_db_url(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    report = tool.build_readiness(
        db_url=None,
        universe_symbols={"A"},
        artifact_paths=[],
        artifact_dir=tmp_path,
    )

    assert report["run_mode"] == "read_only_forward_readiness_guard"
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["trains_model"] is False
    assert report["runs_forward_shadow"] is False
    assert report["readiness"]["ready_to_run_forward_shadow"] is False
    assert report["price_data"]["error"] == "db_url_not_provided"
    assert report["next_forward_commands"] == []


def test_readiness_blocks_partial_new_day(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    db_path = tmp_path / "prices.sqlite"
    _price_db(db_path, ["A", "B"], ["2026-05-28", "2026-05-29", "2026-06-01"])

    report = tool.build_readiness(
        db_url=str(db_path),
        universe_symbols={"A", "B"},
        artifact_paths=_artifacts(tmp_path),
        artifact_dir=tmp_path,
    )

    assert report["readiness"]["ready_to_run_forward_shadow"] is False
    assert report["readiness"]["recommended_forward_end"] is None
    assert "no_new_complete_5d_forward_coverage" in report["readiness"]["blockers"]
    assert report["next_forward_commands"] == []


def test_readiness_emits_commands_when_all_horizons_have_complete_coverage(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    db_path = tmp_path / "prices.sqlite"
    _price_db(
        db_path,
        ["A", "B"],
        [
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
        ],
    )

    report = tool.build_readiness(
        db_url=str(db_path),
        universe_symbols={"A", "B"},
        artifact_paths=_artifacts(tmp_path),
        artifact_dir=tmp_path,
    )

    assert report["readiness"]["ready_to_run_forward_shadow"] is True
    assert report["readiness"]["recommended_forward_end"] == "2026-06-01"
    assert report["readiness"]["ready_exit_days"] == [1, 3, 5]
    assert len(report["next_forward_commands"]) == 3
    assert all("--end 2026-06-01" in command for command in report["next_forward_commands"])
    assert "--exit-days 1" in report["next_forward_commands"][0]
    assert "--exit-days 3" in report["next_forward_commands"][1]
    assert "--exit-days 5" in report["next_forward_commands"][2]


def test_readiness_blocks_skewed_artifact_ends_that_would_regress_a_horizon(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    db_path = tmp_path / "prices.sqlite"
    _price_db(
        db_path,
        ["A", "B"],
        [
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
        ],
    )
    artifacts = [
        _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260605_1d.json", exit_days=1, end="2026-06-05"),
        _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260603_3d.json", exit_days=3, end="2026-06-03"),
        _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260529_5d.json", exit_days=5, end="2026-05-29"),
    ]

    report = tool.build_readiness(
        db_url=str(db_path),
        universe_symbols={"A", "B"},
        artifact_paths=artifacts,
        artifact_dir=tmp_path,
    )

    assert report["readiness"]["ready_to_run_forward_shadow"] is False
    assert report["readiness"]["recommended_forward_end"] is None
    assert "no_new_complete_1d_forward_coverage" in report["readiness"]["blockers"]
    assert "no_new_complete_3d_forward_coverage" in report["readiness"]["blockers"]
    assert report["next_forward_commands"] == []


def test_readiness_blocks_common_end_that_is_not_after_all_existing_artifacts(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    db_path = tmp_path / "prices.sqlite"
    _price_db(
        db_path,
        ["A", "B"],
        [
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
            "2026-06-09",
            "2026-06-10",
            "2026-06-11",
        ],
    )
    artifacts = [
        _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260608_1d.json", exit_days=1, end="2026-06-08"),
        _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260603_3d.json", exit_days=3, end="2026-06-03"),
        _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260529_5d.json", exit_days=5, end="2026-05-29"),
    ]

    report = tool.build_readiness(
        db_url=str(db_path),
        universe_symbols={"A", "B"},
        artifact_paths=artifacts,
        artifact_dir=tmp_path,
    )

    assert report["readiness"]["ready_to_run_forward_shadow"] is False
    assert report["readiness"]["recommended_forward_end"] is None
    assert "recommended_forward_end_not_after_all_existing_artifacts" in report["readiness"]["blockers"]
    assert report["next_forward_commands"] == []


def test_readiness_blocks_price_rows_without_provenance(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    db_path = tmp_path / "prices.sqlite"
    _price_db(
        db_path,
        ["A", "B"],
        [
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
        ],
        missing_provenance_dates={"2026-06-08"},
    )

    report = tool.build_readiness(
        db_url=str(db_path),
        universe_symbols={"A", "B"},
        artifact_paths=_artifacts(tmp_path),
        artifact_dir=tmp_path,
    )

    assert report["readiness"]["ready_to_run_forward_shadow"] is False
    assert report["readiness"]["recommended_forward_end"] is None
    assert "price_provenance_incomplete_after_existing_artifacts" in report["readiness"]["blockers"]
    assert report["next_forward_commands"] == []


def test_readiness_blocks_missing_provenance_even_when_date_count_is_sufficient(tmp_path):
    from backend.tools import m29_forward_readiness as tool

    db_path = tmp_path / "prices.sqlite"
    _price_db(
        db_path,
        ["A", "B"],
        [
            "2026-05-29",
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-08",
            "2026-06-09",
        ],
        missing_provenance_dates={"2026-06-02"},
    )

    report = tool.build_readiness(
        db_url=str(db_path),
        universe_symbols={"A", "B"},
        artifact_paths=_artifacts(tmp_path),
        artifact_dir=tmp_path,
    )

    assert report["readiness"]["max_safe_forward_end_by_exit_days"]["5"] == "2026-06-01"
    assert report["readiness"]["ready_to_run_forward_shadow"] is False
    assert report["readiness"]["recommended_forward_end"] is None
    assert "price_provenance_incomplete_after_existing_artifacts" in report["readiness"]["blockers"]
    assert "no_new_complete_5d_forward_coverage" not in report["readiness"]["blockers"]
    assert report["next_forward_commands"] == []


def test_readiness_uses_latest_discovered_m29_artifacts(tmp_path):
    from backend.tools import m29_evidence_ledger
    from backend.tools import m29_forward_readiness as tool

    _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260601_1d.json", exit_days=1, end="2026-06-01")
    latest = _artifact(
        tmp_path / "m29_forward_shadow_rolling_20260401_20260605_1d.json",
        exit_days=1,
        end="2026-06-05",
    )
    _artifact(tmp_path / "m29_forward_shadow_rolling_20260401_20260603_3d.json", exit_days=3, end="2026-06-03")

    paths = m29_evidence_ledger.default_artifacts(static_artifacts=[], artifact_dir=tmp_path)
    artifacts = tool.latest_forward_artifacts(paths)

    assert artifacts[1]["path"] == str(latest)
    assert artifacts[1]["end"] == "2026-06-05"
    assert artifacts[3]["end"] == "2026-06-03"
