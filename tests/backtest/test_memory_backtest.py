from backend.tools.memory_backtest import (
    Calibration,
    GuardSpec,
    OutcomeSample,
    _load_canonical_signals,
    calibration_as_of,
    guard_blocks,
)


def test_signal_loader_selects_latest_complete_batch_without_partial_mix():
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE signals(
            id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, data_timestamp TEXT,
            market TEXT, quant_score REAL, technical_score REAL, sentiment_score REAL,
            stop_loss REAL, take_profit REAL
        )
    """)
    rows = [
        (1, "AAA", "2026-07-01T16:00+08:00", "2026-07-01", "CN", 1, 10, 10, 9, 12),
        (2, "BBB", "2026-07-01T16:00+08:00", "2026-07-01", "CN", 2, 20, 20, 9, 12),
        (3, "AAA", "2026-07-01T17:00+08:00", "2026-07-01", "CN", 99, 99, 99, 9, 12),
        (4, "AAA", "2026-07-02T17:00+08:00", "2026-07-02", "CN", 99, 99, 99, 9, 12),
    ]
    con.executemany("INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?)", rows)

    signals, health = _load_canonical_signals(
        con,
        {"AAA": "A", "BBB": "B"},
        "2026-07-01",
        "2026-07-02",
    )

    assert [(signal.symbol, signal.quant) for signal in signals] == [("AAA", 1.0), ("BBB", 2.0)]
    assert health["selected_complete_batch_days"] == 1
    assert health["days_without_complete_batch"] == 1
    assert health["non_selected_batch_rows_removed"] == 2


def test_calibration_excludes_outcome_that_matures_on_or_after_signal_date():
    samples = [
        OutcomeSample("AAA", "2026-06-01", "2026-06-15", -4.0, 1),
        OutcomeSample("AAA", "2026-06-02", "2026-06-16", 3.0, 2),
    ]

    calibration = calibration_as_of(samples, symbol="AAA", as_of="2026-06-16")

    assert calibration.sample_count == 1
    assert calibration.mean_excess_10d_pct == -4.0


def test_primary_guard_requires_sample_floor_and_both_negative_conditions():
    spec = GuardSpec("primary", 5, "dual_negative")

    assert guard_blocks(Calibration("AAA", "2026-07-01", 5, -1.0, 0.4, -8.0), spec)
    assert not guard_blocks(Calibration("AAA", "2026-07-01", 4, -1.0, 0.4, -8.0), spec)
    assert not guard_blocks(Calibration("AAA", "2026-07-01", 5, 1.0, 0.4, -8.0), spec)
    assert not guard_blocks(Calibration("AAA", "2026-07-01", 5, -1.0, 0.6, -8.0), spec)
