"""Tests for the M58 exit-parameter shadow arm (test2 v2, owner option B).

Coverage required by the task:
1. The two exit variants (current x2.5/none, shadow x3.5/drawdown_10) are
   hardcoded and cannot be overridden from the public API.
2. Zero writes to any production/test2 state file -- verified both
   statically (source never references test2_ab_state / raw sqlite3.connect)
   and functionally (the synthetic DB and the real repo's
   paper_trading/test2_ab_state.json are byte-for-byte unchanged after a
   run).
3. The shadow-history JSONL append is idempotent per calendar day.
4. The early-v2 "no closed-trade divergence yet" path reports open-position
   stop-line comparisons instead of an empty diff table.
5. A genuine divergence (shadow exits earlier via the floating take-profit,
   current variant stays open) shows up in trade_differences.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from backend.tools import m58_exit_shadow as shadow
from backend.tools.m58_exit_sweep import ExitVariant

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_TEXT = Path(shadow.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Hardcoded variants, no override surface.
# ---------------------------------------------------------------------------


def test_variants_are_locked_to_owner_decision():
    assert shadow.CURRENT_VARIANT == ExitVariant(2.5, "none")
    assert shadow.SHADOW_VARIANT == ExitVariant(3.5, "drawdown_10")


def test_build_shadow_report_accepts_no_variant_override():
    params = set(inspect.signature(shadow.build_shadow_report).parameters)
    assert "variant" not in params
    assert "variants" not in params
    assert "trailing_atr_mult" not in params
    assert "profit_mode" not in params


def test_cli_rejects_an_unknown_variant_flag():
    # main()'s argparse surface has no --variant/--trailing-mult/--profit-mode
    # flag at all; passing one is an argparse error (SystemExit(2)), not a
    # way to override the hardcoded pair.
    with pytest.raises(SystemExit):
        shadow.main(["--variant", "9.9"])


# ---------------------------------------------------------------------------
# Static read/write-boundary checks.
# ---------------------------------------------------------------------------


def test_source_never_references_test2_ab_state_as_a_write_target():
    assert "write_state(" not in SOURCE_TEXT
    assert "save_news_to_db" not in SOURCE_TEXT


def test_source_never_opens_raw_write_capable_sqlite_connection():
    # The module must only reach the DB through the read-only helpers
    # (`_connect_readonly` from m58_exit_sweep, or test2_ab_data.connect_ro
    # inside run_test2_comparison/load_prices/load_universe) -- never a bare
    # sqlite3.connect call of its own.
    assert "sqlite3.connect(" not in SOURCE_TEXT
    assert "import sqlite3" not in SOURCE_TEXT


# ---------------------------------------------------------------------------
# Synthetic fixture builders.
# ---------------------------------------------------------------------------


def _seed_db(db_path: Path, *, signals: list[tuple], prices: list[tuple]) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE signals (symbol TEXT, date TEXT, quant_score REAL, "
        "technical_score REAL, sentiment_score REAL, stop_loss REAL, take_profit REAL)"
    )
    con.execute(
        "CREATE TABLE prices (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL)"
    )
    con.executemany(
        "INSERT INTO signals (symbol, date, quant_score, technical_score, sentiment_score, "
        "stop_loss, take_profit) VALUES (?, ?, ?, ?, ?, ?, ?)",
        signals,
    )
    con.executemany(
        "INSERT INTO prices (symbol, date, open, high, low, close) VALUES (?, ?, ?, ?, ?, ?)",
        prices,
    )
    con.commit()
    con.close()


def _write_universe(path: Path, *, symbol: str, name: str) -> None:
    path.write_text(
        json.dumps({"stocks": [{"symbol": symbol, "name": name, "sector": "TestSector", "origin": "synthetic"}]}),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _divergence_db(tmp_path: Path) -> Path:
    """One symbol whose price path makes the shadow arm exit via the 10%
    floating take-profit while the current (x2.5/none) arm stays open.

    entry_price=100, stop_loss=80 -> entry_atr=10 (INITIAL_ATR_MULT=2.0).
    Peak close=150 on 2026-01-06.
    - current (x2.5): stop_line = 150 - 25 = 125; every low stays > 125 ->
      never triggers, still open at the last available bar.
    - shadow (x3.5/drawdown_10): trailing stop_line = 150 - 35 = 115 (never
      breached), but the drawdown line = 150*0.9 = 135 IS breached on
      2026-01-07 (low=130) -> exits at the 2026-01-08 open (131).
    """
    db_path = tmp_path / "divergence.sqlite"
    _seed_db(
        db_path,
        signals=[
            ("AAA000", "2026-01-04", 0.0, 100.0, 100.0, 80.0, 200.0),  # entry trigger, both frameworks
            ("AAA000", "2026-01-09", 0.0, 0.0, 0.0, 80.0, 200.0),  # advances the replay day-loop only
        ],
        prices=[
            ("AAA000", "2026-01-05", 100.0, 101.0, 99.0, 100.0),  # entry bar
            ("AAA000", "2026-01-06", 105.0, 152.0, 140.0, 150.0),  # peak
            ("AAA000", "2026-01-07", 145.0, 146.0, 130.0, 132.0),  # shadow drawdown trigger day
            ("AAA000", "2026-01-08", 131.0, 133.0, 129.0, 130.0),  # shadow exec day (exit @131 open)
            ("AAA000", "2026-01-09", 129.0, 131.0, 126.0, 128.0),  # last day, current still open
        ],
    )
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, symbol="AAA000", name="TestCo A")
    return db_path, universe_path


def _calm_db(tmp_path: Path) -> Path:
    """One symbol whose price path never approaches either variant's exit
    line, so both arms stay open with zero closed trades -- the "shadow arm
    has no divergence yet" branch."""
    db_path = tmp_path / "calm.sqlite"
    _seed_db(
        db_path,
        signals=[
            ("BBB000", "2026-01-04", 0.0, 100.0, 100.0, 90.0, 200.0),
            ("BBB000", "2026-01-09", 0.0, 0.0, 0.0, 90.0, 200.0),
        ],
        prices=[
            ("BBB000", "2026-01-05", 100.0, 101.0, 99.0, 100.0),  # entry bar
            ("BBB000", "2026-01-06", 101.0, 103.0, 99.0, 102.0),
            ("BBB000", "2026-01-07", 102.0, 104.0, 100.0, 103.0),
            ("BBB000", "2026-01-08", 103.0, 105.0, 101.0, 104.0),
            ("BBB000", "2026-01-09", 104.0, 106.0, 102.0, 105.0),  # last day, highest_close=105
        ],
    )
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, symbol="BBB000", name="TestCo B")
    return db_path, universe_path


# ---------------------------------------------------------------------------
# 5. Divergence scenario.
# ---------------------------------------------------------------------------


def test_shadow_exits_earlier_via_floating_take_profit_while_current_stays_open(tmp_path, monkeypatch):
    pytest.importorskip("paper_trading.test2_ab_models", reason="paper_trading/test2 baseline is local-only, not checked into CI")
    db_path, universe_path = _divergence_db(tmp_path)
    monkeypatch.setattr("paper_trading.test2_ab_models.START_DATE", "2026-01-04")

    report = shadow.build_shadow_report(db_path=db_path, universe_path=universe_path, run_date="2026-01-09")

    assert report["meta"]["window"] == {"start": "2026-01-04", "end": "2026-01-09"}
    assert report["no_divergence_yet"] is False
    assert report["trade_differences"], "expected the shadow arm's early exit to register as a trade difference"

    diff = report["trade_differences"][0]
    assert diff["symbol"] == "AAA000"
    assert diff["classification"] == "candidate_exited_extra"
    assert diff["candidate_exit"]["exit_reason"] == "profit_drawdown_10"
    assert diff["candidate_exit"]["exit_price"] == pytest.approx(131.0)

    for _arm_key, payload in report["arm_summary"].items():
        assert payload["current"]["closed"] == 0
        assert payload["current"]["open"] == 1
        assert payload["shadow"]["closed"] == 1
        assert payload["shadow"]["open"] == 0
        # ~30.6% net gain locked in by the shadow arm on this path.
        assert payload["shadow"]["realized_net_pct"] == pytest.approx(30.6, abs=0.05)


# ---------------------------------------------------------------------------
# 4. Early-v2 "no divergence yet" -> open-position stop-line comparison.
# ---------------------------------------------------------------------------


def test_no_divergence_yet_reports_open_position_stop_lines(tmp_path, monkeypatch):
    pytest.importorskip("paper_trading.test2_ab_models", reason="paper_trading/test2 baseline is local-only, not checked into CI")
    db_path, universe_path = _calm_db(tmp_path)
    monkeypatch.setattr("paper_trading.test2_ab_models.START_DATE", "2026-01-04")

    report = shadow.build_shadow_report(db_path=db_path, universe_path=universe_path, run_date="2026-01-09")

    assert report["no_divergence_yet"] is True
    assert report["trade_differences"] == []
    assert report["open_position_count"] > 0
    assert report["open_position_lines"], "expected per-holding stop-line comparison rows"

    row = next(r for r in report["open_position_lines"] if r["symbol"] == "BBB000")
    assert row["current_stop_line"] == pytest.approx(92.5)
    assert row["shadow_stop_line"] == pytest.approx(90.0)
    assert row["shadow_drawdown_line"] == pytest.approx(94.5)
    assert row["current_still_open"] is True
    assert row["shadow_still_open"] is True

    md = shadow._markdown(report)
    assert "影子臂尚无分歧" in md
    assert "持仓中" in md


def test_no_divergence_and_no_open_positions_message(tmp_path, monkeypatch):
    pytest.importorskip("paper_trading.test2_ab_models", reason="paper_trading/test2 baseline is local-only, not checked into CI")
    db_path = tmp_path / "empty.sqlite"
    _seed_db(db_path, signals=[], prices=[("ZZZ000", "2026-01-05", 10.0, 10.5, 9.5, 10.0)])
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, symbol="ZZZ000", name="Empty")
    monkeypatch.setattr("paper_trading.test2_ab_models.START_DATE", "2026-01-04")

    report = shadow.build_shadow_report(db_path=db_path, universe_path=universe_path, run_date="2026-01-05")

    assert report["no_divergence_yet"] is True
    assert report["open_position_count"] == 0
    assert report["open_position_lines"] == []
    md = shadow._markdown(report)
    assert "无持仓中标的" in md


# ---------------------------------------------------------------------------
# 2. Zero writes to state files (functional, not just static).
# ---------------------------------------------------------------------------


def test_run_never_mutates_the_source_database(tmp_path, monkeypatch):
    pytest.importorskip("paper_trading.test2_ab_models", reason="paper_trading/test2 baseline is local-only, not checked into CI")
    db_path, universe_path = _divergence_db(tmp_path)
    monkeypatch.setattr("paper_trading.test2_ab_models.START_DATE", "2026-01-04")
    before_hash = _sha256(db_path)
    before_mtime = db_path.stat().st_mtime_ns

    shadow.build_shadow_report(db_path=db_path, universe_path=universe_path, run_date="2026-01-09")

    assert _sha256(db_path) == before_hash
    assert db_path.stat().st_mtime_ns == before_mtime


def test_run_never_touches_real_test2_ab_state_json(tmp_path, monkeypatch):
    pytest.importorskip("paper_trading.test2_ab_models", reason="paper_trading/test2 baseline is local-only, not checked into CI")
    real_state = REPO_ROOT / "paper_trading" / "test2_ab_state.json"
    assert real_state.exists(), "expected the real test2 v1/v2 state file to exist in this repo"
    before_hash = _sha256(real_state)
    before_mtime = real_state.stat().st_mtime_ns

    db_path, universe_path = _divergence_db(tmp_path)
    monkeypatch.setattr("paper_trading.test2_ab_models.START_DATE", "2026-01-04")
    report = shadow.build_shadow_report(db_path=db_path, universe_path=universe_path, run_date="2026-01-09")
    shadow.write_report(report, json_path=tmp_path / "r.json", md_path=tmp_path / "r.md")
    shadow.append_history(report, history_path=tmp_path / "history.jsonl")

    assert _sha256(real_state) == before_hash
    assert real_state.stat().st_mtime_ns == before_mtime


# ---------------------------------------------------------------------------
# 3. Idempotent JSONL history append.
# ---------------------------------------------------------------------------


def test_append_history_is_idempotent_same_day_overwrite(tmp_path):
    history_path = tmp_path / "history.jsonl"
    record_v1 = {"meta": {"run_date": "2026-01-09", "note": "first"}}
    record_v2 = {"meta": {"run_date": "2026-01-09", "note": "rerun"}}

    shadow.append_history(record_v1, history_path=history_path)
    shadow.append_history(record_v2, history_path=history_path)

    lines = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["meta"]["note"] == "rerun"


def test_append_history_keeps_prior_days(tmp_path):
    history_path = tmp_path / "history.jsonl"
    day1 = {"meta": {"run_date": "2026-01-08", "note": "day1"}}
    day2 = {"meta": {"run_date": "2026-01-09", "note": "day2"}}

    shadow.append_history(day1, history_path=history_path)
    shadow.append_history(day2, history_path=history_path)
    shadow.append_history(day2, history_path=history_path)  # idempotent rerun of day2

    lines = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert {line["meta"]["run_date"] for line in lines} == {"2026-01-08", "2026-01-09"}
