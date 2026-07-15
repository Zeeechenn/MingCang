from __future__ import annotations

import json
import sqlite3

from backend.tools.m68_test2_compare import (
    PYRAMID_FRAMEWORK,
    build_comparison,
    write_outputs,
)


def _seed(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY,
            market TEXT,
            symbol TEXT,
            date TEXT,
            quant_score REAL,
            technical_score REAL,
            sentiment_score REAL,
            stop_loss REAL,
            take_profit REAL
        );
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY,
            market TEXT,
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL
        );
        CREATE TABLE news_shadow_runs (
            id INTEGER PRIMARY KEY,
            profile TEXT,
            symbol TEXT,
            as_of TEXT,
            status TEXT,
            legacy_signal_id INTEGER,
            legacy_signal_date TEXT,
            pyramid_sentiment_score REAL,
            counterfactual_composite REAL,
            event_risk_level TEXT,
            would_change_action INTEGER
        );
        """
    )
    con.executemany(
        """
        INSERT INTO signals VALUES (?, 'CN', ?, ?, 0, ?, ?, ?, ?)
        """,
        [
            (1, "AAA", "2026-07-16T16:30+08:00", 50, -100, 90, 150),
            (2, "BBB", "2026-07-16T16:30+08:00", 20, 100, 90, 150),
        ],
    )
    price_rows = []
    for index, day in enumerate(
        ("2026-07-16", "2026-07-17", "2026-07-20", "2026-07-21", "2026-07-22")
    ):
        aaa = 100 + index * 3
        bbb = 100 - index * 2
        price_rows.extend(
            [
                ("CN", "AAA", day, aaa, aaa + 1, aaa - 1, aaa),
                ("CN", "BBB", day, bbb, bbb + 1, bbb - 1, bbb),
            ]
        )
    con.executemany(
        "INSERT INTO prices(market,symbol,date,open,high,low,close) VALUES (?,?,?,?,?,?,?)",
        price_rows,
    )
    con.executemany(
        """
        INSERT INTO news_shadow_runs(
            profile,symbol,as_of,status,legacy_signal_id,legacy_signal_date,
            pyramid_sentiment_score,counterfactual_composite,event_risk_level,
            would_change_action
        ) VALUES ('production_mirror',?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                "AAA",
                "2026-07-16",
                "evidence",
                1,
                "2026-07-16T16:30+08:00",
                100,
                70,
                "high",
                1,
            ),
            (
                "BBB",
                "2026-07-16",
                "evidence",
                2,
                "2026-07-16T16:30+08:00",
                -100,
                -28,
                "low",
                1,
            ),
        ],
    )
    con.commit()
    con.close()


def _universe(path):
    path.write_text(
        json.dumps(
            {
                "stocks": [
                    {"symbol": "AAA", "name": "A", "sector": "one"},
                    {"symbol": "BBB", "name": "B", "sector": "two"},
                ]
            }
        ),
        encoding="utf-8",
    )


def test_common_window_pyramid_arm_is_independent_and_timestamp_aware(tmp_path):
    db_path = tmp_path / "test.sqlite"
    universe_path = tmp_path / "universe.json"
    _seed(db_path)
    _universe(universe_path)

    report = build_comparison(
        db_path=db_path,
        universe_path=universe_path,
        as_of="2026-07-22",
    )

    assert report["meta"]["window"] == {"start": "2026-07-16", "end": "2026-07-22"}
    assert report["coverage"]["valid_direction_rows"] == 2
    assert report["coverage"]["neutral_no_decision_rows"] == 0
    assert set(report["arms"]) == {"A_quant_on", "B_quant_off", "C_pyramid_shadow"}
    assert report["arms"][PYRAMID_FRAMEWORK.key]["daily_entries"] == {
        "2026-07-16": ["AAA"]
    }
    assert report["outcomes"]["h1"]["n"] == 2
    assert report["outcomes"]["h1"]["event_risk"]["abs_return_lift_pct_points"] > 0
    assert report["promotion"]["eligible"] is False
    assert "test2_ab_state.json is never read or written" in report["meta"]["epoch_rule"]


def test_missing_shadow_table_skips_without_synthesizing_history(tmp_path):
    db_path = tmp_path / "empty.sqlite"
    universe_path = tmp_path / "universe.json"
    _universe(universe_path)
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE prices (
            market TEXT, symbol TEXT, date TEXT,
            open REAL, high REAL, low REAL, close REAL
        );
        CREATE TABLE signals (
            id INTEGER, market TEXT, symbol TEXT, date TEXT,
            quant_score REAL, technical_score REAL, sentiment_score REAL,
            stop_loss REAL, take_profit REAL
        );
        """
    )
    con.executemany(
        "INSERT INTO prices VALUES ('CN',?,'2026-07-16',10,11,9,10)",
        [("AAA",), ("BBB",)],
    )
    con.commit()
    con.close()

    report = build_comparison(
        db_path=db_path,
        universe_path=universe_path,
        as_of="2026-07-16",
    )

    assert report["skipped"] is True
    assert "starts only from first real shadow date" in report["reason"]


def test_outputs_are_derived_artifacts_only(tmp_path):
    report = {"ok": True, "skipped": True, "reason": "unit"}
    json_path = tmp_path / "state.json"
    md_path = tmp_path / "report.md"

    write_outputs(report, json_path=json_path, md_path=md_path)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    assert "未运行：unit" in md_path.read_text(encoding="utf-8")
