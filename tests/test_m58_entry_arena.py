from __future__ import annotations

import sqlite3

import pytest

from backend.tools import m58_entry_arena as arena


def _init_db(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            atr14 REAL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            created_at TEXT,
            signal_type TEXT,
            composite_score REAL,
            stop_loss REAL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE long_term_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            as_of TEXT,
            label TEXT,
            confidence REAL
        )
        """
    )
    return con


def _insert_prices(con, symbol: str, closes: list[float]) -> None:
    for idx, close in enumerate(closes, start=1):
        con.execute(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume, atr14)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                f"2026-01-{idx:02d}",
                close,
                close + 1,
                close - 1,
                close,
                1000,
                2.0,
            ),
        )


def test_pit_inputs_exclude_future_rows_even_when_future_signal_would_change_score(tmp_path):
    db_path = tmp_path / "arena.sqlite"
    with _init_db(db_path) as con:
        _insert_prices(con, "AAA", [10, 11, 12, 50])
        con.execute(
            "INSERT INTO signals(symbol, created_at, signal_type, composite_score, stop_loss) VALUES (?, ?, ?, ?, ?)",
            ("AAA", "2026-01-02T15:00:00", "watch", 20.0, 8.0),
        )
        con.execute(
            "INSERT INTO signals(symbol, created_at, signal_type, composite_score, stop_loss) VALUES (?, ?, ?, ?, ?)",
            ("AAA", "2026-01-04T15:00:00", "buy", 99.0, 40.0),
        )
        con.execute(
            "INSERT INTO long_term_labels(symbol, as_of, label, confidence) VALUES (?, ?, ?, ?)",
            ("AAA", "2026-01-04", "bullish_future", 0.99),
        )

    with arena.connect_readonly(db_path) as con:
        case = arena.build_arena_case(
            con,
            symbol="AAA",
            as_of="2026-01-02",
            trigger_source="unit",
            trigger_payload={"future_hint": "must stay only as trigger metadata"},
            universe=["AAA"],
            horizons=(1,),
        )

    assert case.inputs["price"]["date"] == "2026-01-02"
    assert case.inputs["signal"]["composite_score"] == 20.0
    assert case.inputs["signal"]["signal_type"] == "watch"
    assert case.inputs["long_term_label"] is None
    assert case.outcome["horizons"]["d1"]["raw_return"] == pytest.approx((12 / 11) - 1)


def test_outcome_uses_same_pool_equal_weight_baseline_and_atr_stop(tmp_path):
    db_path = tmp_path / "arena.sqlite"
    with _init_db(db_path) as con:
        _insert_prices(con, "AAA", [100, 90, 110, 120])
        _insert_prices(con, "BBB", [50, 55, 50, 50])
        con.execute("UPDATE prices SET low = 96 WHERE symbol = 'AAA' AND date = '2026-01-02'")

    with arena.connect_readonly(db_path) as con:
        outcome = arena.compute_outcome(
            con,
            symbol="AAA",
            as_of="2026-01-01",
            universe=["AAA", "BBB"],
            horizons=(2,),
        )

    d2 = outcome["horizons"]["d2"]
    aaa_ret = (110 / 100) - 1
    bbb_ret = (50 / 50) - 1
    baseline = (aaa_ret + bbb_ret) / 2
    assert d2["raw_return"] == pytest.approx(aaa_ret)
    assert d2["baseline_return"] == pytest.approx(baseline)
    assert d2["excess_return"] == pytest.approx(aaa_ret - baseline)
    assert d2["max_drawdown"] == pytest.approx(-0.10)
    assert d2["atr_stop_hit"] is True
    assert outcome["atr_stop_hit_any"] is True


def test_random_control_arm_matches_case_sample_count(tmp_path):
    db_path = tmp_path / "arena.sqlite"
    with _init_db(db_path) as con:
        _insert_prices(con, "AAA", [10, 11, 12, 13])
        _insert_prices(con, "BBB", [20, 19, 18, 17])

    triggers = [
        arena.TriggerPoint(symbol="AAA", as_of="2026-01-01", trigger_source="unit"),
        arena.TriggerPoint(symbol="AAA", as_of="2026-01-02", trigger_source="unit"),
    ]
    result = arena.build_arena_batch(
        db_path=db_path,
        triggers=triggers,
        universe=["AAA", "BBB"],
        horizons=(1,),
        random_seed=7,
    )

    assert len(result["cases"]) == 2
    assert len(result["control_cases"]) == 2
    assert result["meta"]["trial_count"] == 4
    assert {case["arm"] for case in result["cases"] + result["control_cases"]} == {"entry", "random_control"}


def test_calibrate_reports_bins_baseline_and_spearman_shape():
    cases = [
        arena.ArenaCase(
            symbol=f"S{idx}",
            as_of="2026-01-01",
            trigger_source="unit",
            inputs={"score": score},
            outcome={
                "horizons": {
                    "d5": {
                        "excess_return": excess,
                        "baseline_return": baseline,
                    }
                }
            },
            arm="entry",
        )
        for idx, (score, excess, baseline) in enumerate(
            [(0.1, -0.02, -0.01), (0.2, 0.01, -0.01), (0.8, 0.03, 0.01), (0.9, 0.04, 0.01)]
        )
    ]

    report = arena.calibrate(cases, lambda case: case.inputs["score"], bins=[0.0, 0.5, 1.0])

    assert report["horizon"] == "d5"
    assert report["spearman"]["n"] == 4
    assert report["spearman"]["rho"] == pytest.approx(1.0)
    assert [row["sample_status"] for row in report["bins"]] == ["insufficient", "insufficient"]
    assert report["bins"][0]["sample_count"] == 2
    assert report["bins"][0]["win_rate"] == 0.5
    assert report["bins"][1]["baseline_win_rate"] == 1.0
