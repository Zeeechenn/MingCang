from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "m43_2_amihud_ic.py"


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_synthetic_m43_db(path: Path) -> None:
    symbols = [f"00000{i}" for i in range(1, 9)]
    start = date(2020, 1, 1)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE stocks (symbol TEXT PRIMARY KEY, industry TEXT)")
        conn.execute(
            """
            CREATE TABLE prices (
                symbol TEXT,
                date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL
            )
            """
        )
        conn.executemany(
            "INSERT INTO stocks (symbol, industry) VALUES (?, ?)",
            [(symbol, "tech" if idx < 4 else "finance") for idx, symbol in enumerate(symbols)],
        )

        rows = []
        for day in range(560):
            current = start + timedelta(days=day)
            for idx, symbol in enumerate(symbols):
                base = 12.0 + idx * 1.7
                trend = 0.015 * (idx + 1) * day
                cycle = 0.7 * math.sin(day / 17 + idx * 0.45)
                close = max(1.0, base + trend + cycle)
                open_price = close * (1 - 0.002)
                high = close * (1 + 0.006)
                low = close * (1 - 0.006)
                volume = 100_000 + idx * 3_000 + day * (idx + 3) + 500 * math.cos(day / 11 + idx)
                rows.append((symbol, current.isoformat(), open_price, high, low, close, volume))
        conn.executemany(
            "INSERT INTO prices (symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def test_m43_2_help_lists_factor_all() -> None:
    result = _run_script("--help")

    assert result.returncode == 0
    assert "--factor" in result.stdout
    assert "all" in result.stdout
    assert "sealed" in result.stdout


def test_m43_2_sealed_guard_fails_before_opening_missing_db(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.sqlite"
    result = _run_script("--db-path", str(missing_db), "--end-date", "2025-01-01")

    assert result.returncode != 0
    assert "sealed 2025" in result.stderr
    assert not missing_db.exists()


def test_m43_2_missing_db_guard_does_not_create_empty_db(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.sqlite"
    result = _run_script("--db-path", str(missing_db))

    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert not missing_db.exists()


def test_m43_2_synthetic_db_runs_all_three_factors(tmp_path: Path) -> None:
    db_path = tmp_path / "m43.sqlite"
    output_json = tmp_path / "summary.json"
    _write_synthetic_m43_db(db_path)

    result = _run_script(
        "--db-path",
        str(db_path),
        "--factor",
        "all",
        "--start-date",
        "2021-01-01",
        "--end-date",
        "2021-06-30",
        "--stride",
        "5",
        "--output-json",
        str(output_json),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["metadata"]["sealed_2025_guard"] is True
    assert set(payload["results"]) == {
        "amihud_20",
        "sector_rel_strength_20_z",
        "rev_mom_12_1_z",
    }
    for factor, factor_result in payload["results"].items():
        assert factor_result["factor"] == factor
        assert factor_result["ic_summary"]["ic_days"] > 0
        assert factor_result["t_stat"] is not None
        assert factor_result["quintile_spread"]["quintile_means"] is not None
        assert factor_result["quintile_spread"]["n_quintile_dates"] > 0
        assert factor_result["verdict"] in {"PROMOTE", "REJECT", "INCONCLUSIVE"}


def test_m43_2_quintile_spread_is_datewise() -> None:
    from m43_2_amihud_ic import quintile_spread

    frame = pd.DataFrame({
        "date": ["2021-01-01"] * 5 + ["2021-01-02"] * 5,
        "factor": [1, 2, 3, 4, 5, 100, 101, 102, 103, 104],
        "label_5d": [1, 2, 3, 4, 5, 1, 2, 3, 4, 5],
    })

    result = quintile_spread(frame, "factor", "label_5d", min_names=5)

    assert result["quintile_means"] == [1, 2, 3, 4, 5]
    assert result["top_minus_bottom"] == 4
    assert result["n_quintile_dates"] == 2


def test_m43_2_sparse_ic_json_is_standard() -> None:
    from m43_2_amihud_ic import summarize_ic

    payload = {"summary": summarize_ic(pd.Series([0.25]))}

    assert payload["summary"]["ic_std"] is None
    assert payload["summary"]["icir"] == 0.0
    assert json.dumps(payload, allow_nan=False)
