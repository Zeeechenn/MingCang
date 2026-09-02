"""Regression guard for the 2026-09-02 empty-candidate-card defect.

The candidate card was empty on all ten One Loop close-confirmed days while the
authoritative batch carried 6-14 above-threshold names. Three independent breaks
each sufficed:

1. ``_build_buy_candidates`` matched ``signals.date`` exactly against a plain
   trade date, but One Loop made that column a minute-precision run timestamp.
2. ``BUY_RECOMMENDATIONS`` held only legacy wording ("买入"...), while the
   production ``new_framework`` vocabulary is 可小仓试错 / 可关注 / 观望 / 规避.
3. A catch-up run stamps ``date`` with the run day, not the trade day, so even
   a prefix match would have lost 2026-08-21 (batch written 2026-08-23).
   ``data_timestamp`` carries the trade date and is the correct key.

The pre-existing panel tests missed both because every fixture wrote
``date='2026-07-03'`` with ``recommendation='买入'`` -- two values production
never produces. These fixtures deliberately use the real shapes instead.
"""
from __future__ import annotations

import json
import sqlite3

from backend.portfolio.daily_panel import (
    _build_buy_candidates,
    _resolve_signal_batch,
    _run_declares_authoritative,
)

DAY = "2026-09-01"
OFFICIAL = "2026-09-01T15:52+08:00"
LIVE_TRACK = "2026-09-01T15:57+08:00"
DEEP_DIVE = "2026-09-01T16:08+08:00"


def _db(tmp_path, *, signals, job_runs=()):
    path = tmp_path / "panel.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, date TEXT, recommendation TEXT, composite_score REAL,
            stop_loss REAL, take_profit REAL, run_id TEXT
        );
        CREATE TABLE stocks (symbol TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, job_name TEXT, status TEXT, input_coverage_json TEXT
        );
        """
    )
    con.executemany(
        "INSERT INTO signals(symbol, date, recommendation, composite_score, stop_loss,"
        " take_profit, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        signals,
    )
    con.executemany(
        "INSERT INTO job_runs(run_id, job_name, status, input_coverage_json)"
        " VALUES (?, 'test2_signal_runner', 'success', ?)",
        [(run_id, json.dumps(coverage)) for run_id, coverage in job_runs],
    )
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def _official_day(tmp_path):
    """One official 3-name batch plus two same-day --universe research batches."""
    return _db(
        tmp_path,
        signals=[
            ("601318", OFFICIAL, "可小仓试错", 62.9, 50.0, 80.0, "run-official"),
            ("600036", OFFICIAL, "可小仓试错", 52.1, 30.0, 60.0, "run-official"),
            ("000568", OFFICIAL, "可关注", 18.0, 60.0, 90.0, "run-official"),
            ("002463", LIVE_TRACK, "可小仓试错", 61.7, 20.0, 40.0, "run-live"),
            ("600183", DEEP_DIVE, "可小仓试错", 60.6, 20.0, 40.0, "run-deep"),
        ],
        job_runs=[
            ("run-official", {"authoritative": True, "expected_symbols": 25}),
            ("run-live", {"authoritative": False, "expected_symbols": 56}),
            ("run-deep", {"authoritative": False, "expected_symbols": 7}),
        ],
    )


def test_timestamped_batch_is_found_by_trade_date(tmp_path):
    """The defect itself: a plain trade date must still reach a stamped batch."""
    con = _official_day(tmp_path)
    batch_dates, flags = _resolve_signal_batch(con, DAY)
    assert batch_dates == [OFFICIAL]
    assert flags == []


def test_candidate_card_lists_entry_tier_names(tmp_path):
    con = _official_day(tmp_path)
    result = _build_buy_candidates(con, DAY)
    assert [item["symbol"] for item in result["items"]] == ["601318", "600036"]
    assert all(item["recommendation"] == "可小仓试错" for item in result["items"])
    # highest composite score first
    assert result["items"][0]["composite_score"] == 62.9


def test_sub_threshold_tiers_are_not_candidates(tmp_path):
    con = _db(
        tmp_path,
        signals=[
            ("000568", OFFICIAL, "可关注", 18.0, 1.0, 2.0, "run-official"),
            ("600900", OFFICIAL, "观望", 12.0, 1.0, 2.0, "run-official"),
            ("601899", OFFICIAL, "规避", 4.0, 1.0, 2.0, "run-official"),
        ],
        job_runs=[("run-official", {"authoritative": True})],
    )
    assert _build_buy_candidates(con, DAY)["items"] == []


def test_universe_batches_never_enter_the_official_panel(tmp_path):
    """A --universe sweep must not be merged into the official candidate card."""
    con = _official_day(tmp_path)
    symbols = {item["symbol"] for item in _build_buy_candidates(con, DAY)["items"]}
    assert "002463" not in symbols  # live-track sweep
    assert "600183" not in symbols  # subset deep dive


def test_no_authoritative_batch_is_reported_not_guessed(tmp_path):
    con = _db(
        tmp_path,
        signals=[("002463", LIVE_TRACK, "可小仓试错", 61.7, 1.0, 2.0, "run-live")],
        job_runs=[("run-live", {"authoritative": False})],
    )
    result = _build_buy_candidates(con, DAY)
    assert result["items"] == []
    assert f"missing:no_authoritative_signal_batch:{DAY}" in result["flags"]


def test_missing_day_is_flagged(tmp_path):
    con = _official_day(tmp_path)
    result = _build_buy_candidates(con, "2026-08-30")
    assert result["items"] == []
    assert "missing:no_signal_batch:2026-08-30" in result["flags"]


def test_earlier_authoritative_reruns_are_recorded_as_superseded(tmp_path):
    con = _db(
        tmp_path,
        signals=[
            ("601318", OFFICIAL, "可小仓试错", 62.9, 1.0, 2.0, "run-a"),
            ("600036", LIVE_TRACK, "可小仓试错", 52.1, 1.0, 2.0, "run-b"),
        ],
        job_runs=[
            ("run-a", {"authoritative": True}),
            ("run-b", {"authoritative": True}),
        ],
    )
    result = _build_buy_candidates(con, DAY)
    assert [item["symbol"] for item in result["items"]] == ["600036"]
    assert "superseded_signal_batches:1" in result["flags"]


def test_legacy_plain_date_rows_still_render(tmp_path):
    """Pre-One-Loop rows stored a plain date and no run id."""
    con = _db(
        tmp_path,
        signals=[("300308", "2026-07-03", "买入", 72.5, 100.0, 130.0, None)],
    )
    result = _build_buy_candidates(con, "2026-07-03")
    assert [item["symbol"] for item in result["items"]] == ["300308"]


def test_run_without_coverage_flag_counts_as_authoritative(tmp_path):
    con = _official_day(tmp_path)
    assert _run_declares_authoritative(con, "run-official") is True
    assert _run_declares_authoritative(con, "run-live") is False
    assert _run_declares_authoritative(con, "unknown-run") is True
    assert _run_declares_authoritative(con, None) is True


def test_catch_up_run_is_keyed_on_trade_date_not_run_day(tmp_path):
    """2026-08-21's official batch was written on 2026-08-23 and was lost."""
    path = tmp_path / "catchup.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, date TEXT, recommendation TEXT, composite_score REAL,
            stop_loss REAL, take_profit REAL, run_id TEXT, data_timestamp TEXT
        );
        CREATE TABLE stocks (symbol TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, job_name TEXT, status TEXT, input_coverage_json TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO signals(symbol, date, recommendation, composite_score, stop_loss,"
        " take_profit, run_id, data_timestamp)"
        " VALUES ('603259', '2026-08-23T23:19+08:00', '可小仓试错', 65.0, 1.0, 2.0,"
        " 'run-catchup', '2026-08-21')"
    )
    con.execute(
        "INSERT INTO job_runs(run_id, job_name, status, input_coverage_json)"
        " VALUES ('run-catchup', 'test2_signal_runner', 'success', ?)",
        (json.dumps({"authoritative": True}),),
    )
    con.commit()
    con.row_factory = sqlite3.Row
    result = _build_buy_candidates(con, "2026-08-21")
    assert [item["symbol"] for item in result["items"]] == ["603259"]
    # and the run day itself holds no batch of its own
    assert _build_buy_candidates(con, "2026-08-23")["items"] == []


def test_database_without_data_timestamp_column_still_renders(tmp_path):
    con = _db(
        tmp_path,
        signals=[("601318", OFFICIAL, "可小仓试错", 62.9, 1.0, 2.0, "run-official")],
        job_runs=[("run-official", {"authoritative": True})],
    )
    assert [item["symbol"] for item in _build_buy_candidates(con, DAY)["items"]] == ["601318"]
