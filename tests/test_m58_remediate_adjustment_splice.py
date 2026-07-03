"""Tests for the M58 remediation tool's pure detection logic (hermetic, no DB)."""
from __future__ import annotations

import sqlite3

from backend.tools.m58_remediate_adjustment_splice import (
    detect_splice_transitions,
    run_remediation,
)


def test_detect_flags_primary_down_splice():
    """A row whose close/median ratio is <1/3 with an adjustment discontinuity
    is a PRIMARY candidate (mirrors the real 002130 production case)."""
    rows = {
        "002130": [
            ("2026-05-22", 471.0, None),
            ("2026-05-25", 470.0, None),
            ("2026-05-26", 465.0, None),
            ("2026-05-27", 468.0, None),
            ("2026-05-28", 469.9, None),
            ("2026-05-29", 21.99, "qfq"),  # ratio ~= 0.0469
        ]
    }
    primary, suspect = detect_splice_transitions(rows)
    assert len(primary) == 1
    assert primary[0]["symbol"] == "002130"
    assert primary[0]["date"] == "2026-05-29"
    assert not suspect


def test_detect_flags_primary_up_splice():
    rows = {
        "999999": [
            ("2026-05-22", 10.0, None),
            ("2026-05-25", 10.0, None),
            ("2026-05-26", 10.1, None),
            ("2026-05-27", 9.9, None),
            ("2026-05-28", 10.2, None),
            ("2026-05-29", 45.0, "forward_additive"),  # ratio ~4.5
        ]
    }
    primary, suspect = detect_splice_transitions(rows)
    assert len(primary) == 1
    assert primary[0]["date"] == "2026-05-29"


def test_detect_does_not_flag_when_adjustment_stable():
    """Even a huge ratio should NOT be flagged if the adjustment basis is
    unchanged across the transition — that would be a genuine (if extreme)
    price move on a self-consistent series, out of scope for this tool."""
    rows = {
        "000001": [
            ("2026-05-22", 10.0, "qfq"),
            ("2026-05-25", 10.0, "qfq"),
            ("2026-05-26", 10.1, "qfq"),
            ("2026-05-27", 9.9, "qfq"),
            ("2026-05-28", 10.2, "qfq"),
            ("2026-05-29", 45.0, "qfq"),
        ]
    }
    primary, suspect = detect_splice_transitions(rows)
    assert not primary
    assert not suspect


def test_detect_flags_suspect_band_not_primary():
    """A ~0.5x move (consistent with a 10-for-10 bonus share issue) with an
    adjustment discontinuity lands in the suspect band, not primary."""
    rows = {
        "300570": [
            ("2026-05-22", 301.0, None),
            ("2026-05-25", 300.0, None),
            ("2026-05-26", 298.0, None),
            ("2026-05-27", 302.0, None),
            ("2026-05-28", 313.22, None),
            ("2026-05-29", 165.42, "qfq"),  # ratio ~= 0.528
        ]
    }
    primary, suspect = detect_splice_transitions(rows)
    assert not primary
    assert len(suspect) == 1
    assert suspect[0]["date"] == "2026-05-29"


def test_detect_respects_min_preceding():
    """Fewer than 5 usable preceding closes -> never flagged, regardless of ratio."""
    rows = {
        "000002": [
            ("2026-05-25", 10.0, None),
            ("2026-05-26", 10.0, None),
            ("2026-05-27", 10.0, None),
            ("2026-05-28", 1000.0, "qfq"),  # only 3 preceding closes
        ]
    }
    primary, suspect = detect_splice_transitions(rows)
    assert not primary
    assert not suspect


def test_detect_respects_window_bounds():
    rows = {
        "000003": [
            ("2020-01-01", 10.0, None),
            ("2020-01-02", 10.0, None),
            ("2020-01-03", 10.0, None),
            ("2020-01-04", 10.0, None),
            ("2020-01-05", 10.0, None),
            ("2020-01-06", 0.5, "qfq"),  # extreme, but outside window
        ]
    }
    primary, suspect = detect_splice_transitions(
        rows, window_start="2026-05-20", window_end="2026-07-05"
    )
    assert not primary
    assert not suspect


def _seed_002130(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE prices (symbol TEXT, date TEXT, close REAL, adjustment TEXT)"
    )
    base = [
        ("002130", "2026-05-22", 471.0, None),
        ("002130", "2026-05-25", 470.0, None),
        ("002130", "2026-05-26", 465.0, None),
        ("002130", "2026-05-27", 468.0, None),
        ("002130", "2026-05-28", 469.9, None),
        ("002130", "2026-05-29", 21.99, "qfq"),
    ]
    conn.executemany(
        "INSERT INTO prices (symbol, date, close, adjustment) VALUES (?,?,?,?)", base
    )
    conn.commit()


def test_run_remediation_dry_run_does_not_write(tmp_path):
    db_path = tmp_path / "fake_mingcang.db"
    conn = sqlite3.connect(str(db_path))
    _seed_002130(conn)
    conn.close()

    result = run_remediation(f"sqlite:///{db_path}", execute=False)
    assert result["run_mode"] == "dry_run"
    assert result["primary_flagged_rows"] == 1
    assert result["rows_deleted"] == 0
    assert result["backup_path"] is None

    # DB untouched.
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    conn.close()
    assert count == 6


def test_run_remediation_execute_deletes_and_backs_up(tmp_path):
    db_path = tmp_path / "fake_mingcang.db"
    conn = sqlite3.connect(str(db_path))
    _seed_002130(conn)
    conn.close()

    backup_dir = tmp_path / "backups"
    result = run_remediation(
        f"sqlite:///{db_path}", execute=True, backup_dir=backup_dir
    )
    assert result["run_mode"] == "execute"
    assert result["rows_deleted"] == 1
    assert result["backup_path"] is not None

    backups = list(backup_dir.iterdir())
    assert len(backups) == 1

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    remaining_dates = [r[0] for r in conn.execute("SELECT date FROM prices")]
    conn.close()
    assert count == 5
    assert "2026-05-29" not in remaining_dates


def test_run_remediation_idempotent(tmp_path):
    db_path = tmp_path / "fake_mingcang.db"
    conn = sqlite3.connect(str(db_path))
    _seed_002130(conn)
    conn.close()

    backup_dir = tmp_path / "backups"
    first = run_remediation(f"sqlite:///{db_path}", execute=True, backup_dir=backup_dir)
    assert first["rows_deleted"] == 1

    second = run_remediation(f"sqlite:///{db_path}", execute=True, backup_dir=backup_dir)
    assert second["rows_deleted"] == 0
    assert second["primary_flagged_rows"] == 0
    # Second execute-with-nothing-to-delete must not create a backup.
    assert second["backup_path"] is None
