"""Tests for M42 remediation CLI (backend/tools/m42_remediate_hfq_contamination.py).

All tests use a real SQLite file under pytest's tmp_path fixture — NOT the
test_db fixture — because:
  1. shutil.copy2 backup requires a real filesystem path (not ':memory:').
  2. The remediation CLI creates its own sqlite3 connection from --db-url,
     independent of SQLAlchemy.

No test ever touches /tmp/m42_prod_copy.db or the live stock-sage.db.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_prices_db(path: Path) -> None:
    """Create a minimal prices table in the SQLite file at *path*."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            atr14 REAL, source TEXT, fetched_at TEXT, adjustment TEXT,
            UNIQUE(symbol, date)
        )
    """)
    conn.commit()
    conn.close()


def _insert_rows(path: Path, rows: list[dict]) -> None:
    """Insert price rows into the DB at *path*."""
    conn = sqlite3.connect(str(path))
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO prices (symbol, date, open, high, low, close, volume, adjustment) "
            "VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :adjustment)",
            row,
        )
    conn.commit()
    conn.close()


def _count_rows(path: Path, symbol: str, date_str: str) -> int:
    conn = sqlite3.connect(str(path))
    n = conn.execute(
        "SELECT COUNT(*) FROM prices WHERE symbol=? AND date=?", (symbol, date_str)
    ).fetchone()[0]
    conn.close()
    return n


def _make_clean_history(symbol: str, close: float = 10.0, n: int = 10) -> list[dict]:
    """Return *n* clean qfq-scale rows for *symbol* dated 2026-05-01 .. 2026-05-N."""
    return [
        {
            "symbol": symbol, "date": f"2026-05-{i + 1:02d}",
            "open": close, "high": close + 0.5, "low": close - 0.5,
            "close": close, "volume": 1_000_000, "adjustment": None,
        }
        for i in range(n)
    ]


@pytest.fixture()
def clean_db(tmp_path: Path) -> Path:
    """DB with only clean rows — no contamination."""
    db = tmp_path / "clean.db"
    _create_prices_db(db)
    _insert_rows(db, _make_clean_history("000001", close=10.5))
    return db


@pytest.fixture()
def contaminated_db(tmp_path: Path) -> Path:
    """DB with clean history + one hfq-contaminated row (ratio≈200×)."""
    db = tmp_path / "contaminated.db"
    _create_prices_db(db)
    # 10 clean rows.
    _insert_rows(db, _make_clean_history("000001", close=10.86))
    # 1 hfq-contaminated row (close ≈ 193× preceding median).
    _insert_rows(db, [{
        "symbol": "000001", "date": "2026-05-26",
        "open": 2000.0, "high": 2100.0, "low": 1950.0,
        "close": 2098.01, "volume": 500_000, "adjustment": None,
    }])
    return db


@pytest.fixture()
def snapback_db(tmp_path: Path) -> Path:
    """DB with a subtler contamination (ratio≈2×) that triggers secondary/snap-back predicate."""
    db = tmp_path / "snapback.db"
    _create_prices_db(db)
    # 10 clean rows at close=5.0.
    _insert_rows(db, _make_clean_history("600027", close=5.15))
    # Contaminated row: close=10.13 (~1.97×median), snaps back to 5.29 next day.
    _insert_rows(db, [
        {"symbol": "600027", "date": "2026-05-26",
         "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.13,
         "volume": 1_000_000, "adjustment": None},
        {"symbol": "600027", "date": "2026-05-27",
         "open": 5.2, "high": 5.4, "low": 5.1, "close": 5.29,
         "volume": 1_000_000, "adjustment": None},
    ])
    return db


# ---------------------------------------------------------------------------
# Detection tests (dry-run, no writes)
# ---------------------------------------------------------------------------


def test_dry_run_clean_db_flags_nothing(clean_db):
    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{clean_db}", execute=False)

    assert result["run_mode"] == "dry_run"
    assert result["writes_db"] is False
    assert result["flagged_rows_total"] == 0
    assert result["rows_deleted"] == 0
    assert result["backup_path"] is None


def test_dry_run_detects_primary_contamination(contaminated_db):
    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{contaminated_db}", execute=False)

    assert result["flagged_primary"] >= 1
    assert result["flagged_rows_total"] >= 1
    # Dry-run must NOT delete anything.
    assert result["rows_deleted"] == 0
    assert result["backup_path"] is None
    # The contaminated row should appear in details.
    dates = [d["date"] for d in result["details"] if d["symbol"] == "000001"]
    assert "2026-05-26" in dates


def test_dry_run_detects_secondary_snapback(snapback_db):
    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{snapback_db}", execute=False)

    snapback_rows = [d for d in result["details"] if d["predicate"] == "secondary_snapback"]
    assert len(snapback_rows) >= 1
    assert any(d["symbol"] == "600027" and d["date"] == "2026-05-26" for d in snapback_rows)


# ---------------------------------------------------------------------------
# Execute tests (real deletes on throwaway DB copies)
# ---------------------------------------------------------------------------


def test_execute_deletes_primary_contamination(tmp_path, contaminated_db):
    """Execute mode must delete the contaminated row and leave clean rows intact."""
    # Make a throwaway copy.
    work = tmp_path / "work.db"
    import shutil
    shutil.copy2(contaminated_db, work)

    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{work}", execute=True)

    assert result["run_mode"] == "execute"
    assert result["writes_db"] is True
    assert result["rows_deleted"] >= 1
    assert result["backup_path"] is not None
    # Backup must exist on disk.
    assert Path(result["backup_path"]).exists()
    # Contaminated row must be gone.
    assert _count_rows(work, "000001", "2026-05-26") == 0
    # Clean history rows must still be there.
    assert _count_rows(work, "000001", "2026-05-01") == 1


def test_execute_idempotent(tmp_path, contaminated_db):
    """Running execute twice must produce 0 deletions on the second run."""
    work = tmp_path / "work2.db"
    import shutil
    shutil.copy2(contaminated_db, work)

    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    r1 = run_remediation(f"sqlite:///{work}", execute=True)
    assert r1["rows_deleted"] >= 1

    r2 = run_remediation(f"sqlite:///{work}", execute=True)
    assert r2["rows_deleted"] == 0
    assert r2["flagged_rows_total"] == 0


def test_execute_creates_backup_before_delete(tmp_path, contaminated_db):
    """Backup must be created before deletes, and must contain the contaminated row."""
    work = tmp_path / "work3.db"
    import shutil
    shutil.copy2(contaminated_db, work)

    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{work}", execute=True)
    backup_path = Path(result["backup_path"])

    # Backup must exist and contain the row that was deleted from work.
    assert backup_path.exists()
    assert _count_rows(backup_path, "000001", "2026-05-26") == 1
    assert _count_rows(work, "000001", "2026-05-26") == 0


# ---------------------------------------------------------------------------
# Safety / guard tests
# ---------------------------------------------------------------------------


def test_refuses_to_operate_on_prod_copy_db(tmp_path):
    """The tool must refuse a --db-url whose filename matches m42_prod_copy.db."""
    forbidden = tmp_path / "m42_prod_copy.db"
    _create_prices_db(forbidden)

    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    with pytest.raises(ValueError, match="refuses to operate on"):
        run_remediation(f"sqlite:///{forbidden}", execute=True)


def test_refuses_to_operate_on_stock_sage_db(tmp_path):
    """The tool must refuse a --db-url whose filename matches stock-sage.db."""
    forbidden = tmp_path / "stock-sage.db"
    _create_prices_db(forbidden)

    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    with pytest.raises(ValueError, match="refuses to operate on"):
        run_remediation(f"sqlite:///{forbidden}", execute=True)


def test_dry_run_also_refuses_forbidden_paths(tmp_path):
    """Safety guard must apply even in dry-run mode."""
    forbidden = tmp_path / "stock-sage.db"
    _create_prices_db(forbidden)

    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    with pytest.raises(ValueError, match="refuses to operate on"):
        run_remediation(f"sqlite:///{forbidden}", execute=False)


def test_missing_db_raises_file_not_found(tmp_path):
    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    with pytest.raises(FileNotFoundError):
        run_remediation(f"sqlite:///{tmp_path}/nonexistent.db", execute=False)


# ---------------------------------------------------------------------------
# Result schema / structured output tests
# ---------------------------------------------------------------------------


def test_result_schema_dry_run(clean_db):
    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{clean_db}", execute=False)

    required_keys = {
        "generated_at", "schema_version", "milestone", "run_mode",
        "writes_db", "writes_tables", "production_unchanged",
        "db_path", "total_symbols_scanned", "flagged_rows_total",
        "flagged_primary", "flagged_secondary_snapback",
        "flagged_symbols_count", "backup_path", "rows_deleted",
        "rows_deleted_primary", "rows_deleted_secondary", "details",
    }
    assert required_keys.issubset(result.keys())
    assert result["milestone"] == "M42"
    assert result["production_unchanged"] is True


def test_result_is_json_serialisable(contaminated_db):
    from backend.tools.m42_remediate_hfq_contamination import run_remediation

    result = run_remediation(f"sqlite:///{contaminated_db}", execute=False)
    # Must not raise.
    dumped = json.dumps(result, default=str)
    reloaded = json.loads(dumped)
    assert reloaded["milestone"] == "M42"


# ---------------------------------------------------------------------------
# _detect_contaminated unit tests (pure logic, no DB)
# ---------------------------------------------------------------------------


def test_detect_contaminated_primary_only():
    from backend.tools.m42_remediate_hfq_contamination import _detect_contaminated

    rows = {
        "000001": [
            *[(f"2026-05-{i + 1:02d}", 10.86, None) for i in range(10)],
            ("2026-05-26", 2098.01, None),   # hfq
        ]
    }
    flagged = _detect_contaminated(rows)
    assert any(s == "000001" and d == "2026-05-26" for s, d, _ in flagged)


def test_detect_contaminated_skips_non_null_adjustment():
    """Rows with a non-NULL adjustment value must not be flagged."""
    from backend.tools.m42_remediate_hfq_contamination import _detect_contaminated

    rows = {
        "000002": [
            *[(f"2026-05-{i + 1:02d}", 3.70, "qfq") for i in range(10)],
            ("2026-05-26", 1225.49, "qfq"),   # hfq-scale but adjustment='qfq' → skip
        ]
    }
    flagged = _detect_contaminated(rows)
    assert not any(s == "000002" for s, _, _ in flagged)


def test_detect_contaminated_insufficient_history_passes():
    """Fewer than 5 preceding rows → guard must not fire."""
    from backend.tools.m42_remediate_hfq_contamination import _detect_contaminated

    rows = {
        "NEW_SYM": [
            ("2026-05-01", 10.0, None),
            ("2026-05-02", 9999.0, None),   # only 1 preceding row
        ]
    }
    flagged = _detect_contaminated(rows)
    assert not flagged


def test_detect_contaminated_snapback_secondary():
    """Secondary snap-back predicate must fire for moderate-ratio + snap-back rows."""
    from backend.tools.m42_remediate_hfq_contamination import _detect_contaminated

    rows = {
        "600027": [
            *[(f"2026-05-{i + 1:02d}", 5.15, None) for i in range(10)],
            ("2026-05-26", 10.13, None),   # ratio≈1.97×, between 1.5 and 3.0
            ("2026-05-27", 5.29, None),    # snaps back to qfq scale
        ]
    }
    flagged = _detect_contaminated(rows)
    snapback = [f for f in flagged if f[2] == "secondary_snapback" and f[0] == "600027"]
    assert len(snapback) >= 1
