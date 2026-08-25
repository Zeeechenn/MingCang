"""实盘门（Track B）测试：覆盖率门 + 持仓硬门，5 个场景 + 退出码契约。

退出码契约：0 = pass，5 = fail（门没过），2 = 用法/IO 错误。见
scripts/live_track_gate.py 顶部说明。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE_SCRIPT = REPO_ROOT / "scripts" / "live_track_gate.py"

DAY = "2026-08-25"
UNIVERSE_SYMBOLS = [
    ("600000", "示例银行"),
    ("600001", "示例地产"),
    ("600002", "示例钢铁"),
    ("600003", "示例化工"),
]


def _make_db(db_path: Path, *, signals: list[tuple[str, str]], prices: list[tuple[str, str]]) -> None:
    """signals: list of (symbol, data_timestamp). prices: list of (symbol, date) — one row per bar."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR,
                date VARCHAR,
                data_timestamp TEXT,
                composite_score FLOAT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE prices (
                id INTEGER PRIMARY KEY,
                symbol VARCHAR,
                date VARCHAR,
                close FLOAT
            )
            """
        )
        conn.executemany(
            "INSERT INTO signals (symbol, date, data_timestamp, composite_score) VALUES (?, ?, ?, 50.0)",
            [(sym, ts, ts) for sym, ts in signals],
        )
        conn.executemany(
            "INSERT INTO prices (symbol, date, close) VALUES (?, ?, 10.0)",
            prices,
        )
        conn.commit()
    finally:
        conn.close()


def _make_universe(path: Path, symbols: list[tuple[str, str]]) -> None:
    payload = {
        "version": "test",
        "source": "test",
        "stocks": [{"symbol": s, "name": n, "sector": "", "origin": "live"} for s, n in symbols],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_state(path: Path, *, positions: list[dict] | None) -> None:
    payload = {
        "version": 1,
        "as_of": DAY,
        "portfolio_value": "100000.00",
        "positions": positions if positions is not None else [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_gate(tmp_path: Path, *, min_coverage: float = 0.90, json_out: Path | None = None) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        str(GATE_SCRIPT),
        "--date",
        DAY,
        "--db",
        str(tmp_path / "mingcang.db"),
        "--universe",
        str(tmp_path / "universe.json"),
        "--state",
        str(tmp_path / "state.json"),
        "--min-coverage",
        str(min_coverage),
    ]
    if json_out is not None:
        args += ["--json-out", str(json_out)]
    return subprocess.run(args, capture_output=True, text=True)


def test_all_fresh_and_empty_positions_passes(tmp_path: Path) -> None:
    _make_db(
        tmp_path / "mingcang.db",
        signals=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
        prices=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
    )
    _make_universe(tmp_path / "universe.json", UNIVERSE_SYMBOLS)
    _make_state(tmp_path / "state.json", positions=[])

    json_out = tmp_path / "verdict.json"
    result = _run_gate(tmp_path, json_out=json_out)

    assert result.returncode == 0, result.stdout + result.stderr
    verdict = json.loads(json_out.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "pass"
    assert verdict["reasons"] == []
    assert verdict["universe_size"] == 4
    assert verdict["fresh_signal_symbols"] == 4
    assert verdict["coverage_ratio"] == 1.0
    assert verdict["missing_symbols"] == []
    assert verdict["holdings"] == []
    assert verdict["stale_holdings"] == []


def test_low_coverage_fails(tmp_path: Path) -> None:
    # Only 2 of 4 symbols have a fresh signal + fresh bar -> coverage 0.5 < 0.90 default.
    fresh = UNIVERSE_SYMBOLS[:2]
    _make_db(
        tmp_path / "mingcang.db",
        signals=[(s, DAY) for s, _ in fresh],
        prices=[(s, DAY) for s, _ in fresh] + [(s, "2026-08-20") for s, _ in UNIVERSE_SYMBOLS[2:]],
    )
    _make_universe(tmp_path / "universe.json", UNIVERSE_SYMBOLS)
    _make_state(tmp_path / "state.json", positions=[])

    json_out = tmp_path / "verdict.json"
    result = _run_gate(tmp_path, json_out=json_out)

    assert result.returncode == 5, result.stdout + result.stderr
    verdict = json.loads(json_out.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "fail"
    assert "low_coverage" in verdict["reasons"]
    assert verdict["coverage_ratio"] == pytest.approx(0.5)
    assert set(verdict["missing_symbols"]) == {s for s, _ in UNIVERSE_SYMBOLS[2:]}


def test_stale_holdings_fails(tmp_path: Path) -> None:
    # Full coverage on the (unrelated) live universe -> B1 passes on its own.
    # The held position 600099 is NOT in the live universe (a holding can sit
    # outside the 56-stock pool) and has only a stale bar -> B2 must fail.
    held_symbol = "600099"
    _make_db(
        tmp_path / "mingcang.db",
        signals=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
        prices=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS] + [(held_symbol, "2026-08-20")],
    )
    _make_universe(tmp_path / "universe.json", UNIVERSE_SYMBOLS)
    _make_state(tmp_path / "state.json", positions=[{"symbol": held_symbol, "market_value": "5000.00"}])

    json_out = tmp_path / "verdict.json"
    result = _run_gate(tmp_path, json_out=json_out)

    assert result.returncode == 5, result.stdout + result.stderr
    verdict = json.loads(json_out.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "fail"
    assert "stale_holdings" in verdict["reasons"]
    assert "low_coverage" not in verdict["reasons"]
    assert verdict["stale_holdings"] == [held_symbol]
    assert verdict["holdings"] == [held_symbol]


def test_corrupt_state_file_fails_closed(tmp_path: Path) -> None:
    _make_db(
        tmp_path / "mingcang.db",
        signals=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
        prices=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
    )
    _make_universe(tmp_path / "universe.json", UNIVERSE_SYMBOLS)
    (tmp_path / "state.json").write_text("{not valid json", encoding="utf-8")

    json_out = tmp_path / "verdict.json"
    result = _run_gate(tmp_path, json_out=json_out)

    assert result.returncode == 5, result.stdout + result.stderr
    verdict = json.loads(json_out.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "fail"
    assert "holdings_unreadable" in verdict["reasons"]
    # B1 passed on its own (full coverage) — only the fail-closed holdings check fails.
    assert "low_coverage" not in verdict["reasons"]


def test_missing_state_file_fails_closed(tmp_path: Path) -> None:
    _make_db(
        tmp_path / "mingcang.db",
        signals=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
        prices=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
    )
    _make_universe(tmp_path / "universe.json", UNIVERSE_SYMBOLS)
    # No state.json written at all.

    result = _run_gate(tmp_path)

    assert result.returncode == 5, result.stdout + result.stderr
    assert "holdings_unreadable" in result.stdout


def test_empty_positions_passes_b2(tmp_path: Path) -> None:
    _make_db(
        tmp_path / "mingcang.db",
        signals=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
        prices=[(s, DAY) for s, _ in UNIVERSE_SYMBOLS],
    )
    _make_universe(tmp_path / "universe.json", UNIVERSE_SYMBOLS)
    _make_state(tmp_path / "state.json", positions=[])

    result = _run_gate(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
