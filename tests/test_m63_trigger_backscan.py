from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest

from backend.tools.m63_trigger_backscan import (
    SOURCES,
    SOURCE_R6_PRICE_MOVE,
    SOURCE_LHB,
    build_backscan_report,
    detect_episodes,
    render_markdown,
    summarize_backscan,
)


def _init_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        );
        CREATE TABLE news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            title TEXT,
            url TEXT,
            published_at DATETIME,
            source TEXT
        );
        CREATE TABLE lhb_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            trade_date DATETIME,
            reason TEXT,
            net_buy_amount REAL,
            provider TEXT
        );
        CREATE TABLE fund_flows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            trade_date DATETIME,
            main_net REAL,
            provider TEXT
        );
        CREATE TABLE m60_watchtower_trigger_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            target TEXT,
            trigger_type TEXT
        );
        CREATE TABLE forward_theses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            statement TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            invalidation_conditions_json TEXT,
            follow_up_metrics_json TEXT,
            updated_at TEXT
        );
        CREATE TABLE thesis_condition_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forward_thesis_id INTEGER,
            condition_type TEXT,
            spec_json TEXT,
            compiled_by TEXT,
            created_at TEXT
        );
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            closed_at TEXT
        );
        CREATE TABLE announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            title TEXT,
            published_at TEXT
        );
        CREATE TABLE research_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            title TEXT,
            publish_date TEXT
        );
        CREATE TABLE corporate_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            event_type TEXT,
            title TEXT,
            event_date TEXT
        );
        CREATE TABLE overseas_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            name TEXT,
            snap_date TEXT,
            close REAL,
            chg_pct_1d REAL,
            chg_pct_20d REAL
        );
        """
    )
    return con


def _write_universe(path, symbols):
    path.write_text(
        json.dumps(
            {
                "version": "unit",
                "source": "unit",
                "stocks": [
                    {"symbol": symbol, "name": symbol, "sector": sector, "origin": "unit"}
                    for symbol, sector in symbols
                ],
            }
        ),
        encoding="utf-8",
    )


def _dates(start: str, count: int) -> list[str]:
    base = date.fromisoformat(start)
    return [(base + timedelta(days=idx)).isoformat() for idx in range(count)]


def _insert_prices(con, symbol: str, dates: list[str], closes: list[float]) -> None:
    for day, close in zip(dates, closes):
        con.execute(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, 1000)
            """,
            (symbol, day, close, close, close, close),
        )


def test_detect_episodes_merges_consecutive_hits():
    rows = {
        "AAA": [
            {"date": f"2026-01-{day:02d}", "close": close}
            for day, close in enumerate([100, 100, 100, 100, 100, 111, 112, 113, 100], start=1)
        ]
    }

    episodes = detect_episodes(rows, start="2026-01-01", end="2026-01-31")

    assert len(episodes) == 1
    assert episodes[0]["start_date"] == "2026-01-06"
    assert episodes[0]["end_date"] == "2026-01-08"
    assert episodes[0]["direction"] == "up"
    assert episodes[0]["peak_return_pct"] == pytest.approx(13.0)


def test_backscan_classifies_captured_and_missed_and_source_denominator(tmp_path):
    db_path = tmp_path / "backscan.sqlite"
    universe_a = tmp_path / "universe_a.json"
    universe_b = tmp_path / "universe_b.json"
    _write_universe(universe_a, [("AAA", "sector_a"), ("BBB", "sector_b")])
    _write_universe(universe_b, [("CCC", "sector_c")])
    days = _dates("2026-01-01", 55)

    with _init_db(db_path) as con:
        aaa = [100.0] * 55
        for idx in range(30, 36):
            aaa[idx] = 112.0 + (idx - 30)
        for idx in range(36, 55):
            aaa[idx] = 112.0

        bbb = [100.0]
        for idx in range(1, 40):
            bbb.append(bbb[-1] * (1.03 if idx % 2 else 0.97))
        for _ in range(5):
            bbb.append(bbb[-1] * 0.978)
        bbb.extend([bbb[-1]] * (55 - len(bbb)))

        ccc = [100.0] * 55
        for idx in range(10, 16):
            ccc[idx] = 112.0
        for idx in range(16, 55):
            ccc[idx] = 100.0

        _insert_prices(con, "AAA", days, aaa)
        _insert_prices(con, "BBB", days, bbb)
        _insert_prices(con, "CCC", days, ccc)
        con.execute(
            """
            INSERT INTO lhb_records(symbol, trade_date, reason, net_buy_amount, provider)
            VALUES ('AAA', ?, 'unit spotlight', 1000000, 'unit')
            """,
            (f"{days[30]} 00:00:00",),
        )
        con.execute(
            """
            INSERT INTO news(symbol, title, url, published_at, source)
            VALUES ('AAA', '普通新闻', 'http://example.com', ?, 'unit')
            """,
            (f"{days[30]} 09:00:00",),
        )

    report = build_backscan_report(
        db_path=db_path,
        start="2026-01-01",
        end=days[-1],
        universe_paths=(universe_a, universe_b),
    )

    assert report["summary"]["episodes_total"] >= 3
    current_missed_symbols = {item["symbol"] for item in report["summary"]["missed_episodes"]}
    assert "AAA" not in current_missed_symbols
    assert "BBB" not in current_missed_symbols
    assert report["summary"]["pre_r6_stack"]["missed_by_all_sources"] >= 1
    assert report["summary"]["per_source"][SOURCE_LHB]["captured_episodes"] == 1
    assert report["summary"]["per_source"][SOURCE_LHB]["covered_episodes"] < report["summary"]["episodes_total"]
    markdown = render_markdown(report)
    assert "Overall miss rate" in markdown
    assert "买入" not in markdown
    assert "卖出" not in markdown


def test_backscan_r6_captures_price_move_blind_spot_with_damper_and_lag(tmp_path, monkeypatch):
    import backend.tools.m63_trigger_backscan as backscan

    monkeypatch.setattr(backscan, "build_watchtower_report_from_entries", lambda **_: {"triggers": []})
    db_path = tmp_path / "backscan.sqlite"
    universe = tmp_path / "universe.json"
    _write_universe(universe, [("R6A", "sector_r6"), ("R6B", "sector_r6")])
    days = _dates("2026-02-01", 25)

    with _init_db(db_path) as con:
        r6a = [100.0] * 25
        r6a[5] = 111.0
        r6a[6] = 112.0
        r6a[7] = 113.0
        r6a[8] = 114.0
        for idx in range(9, 25):
            r6a[idx] = 114.0

        r6b = [100.0] * 25
        r6b[5] = 111.0
        r6b[6] = 111.5
        r6b[7] = 112.0
        r6b[8] = 112.5
        r6b[9] = 113.0
        for idx in range(10, 25):
            r6b[idx] = 113.0

        _insert_prices(con, "R6A", days, r6a)
        _insert_prices(con, "R6B", days, r6b)

    report = build_backscan_report(
        db_path=db_path,
        start=days[0],
        end=days[-1],
        universe_paths=(universe,),
    )

    r6_stats = report["summary"]["per_source"][SOURCE_R6_PRICE_MOVE]
    assert r6_stats["captured_episodes"] == 2
    assert r6_stats["captured_trigger_count"] == 2
    assert report["summary"]["pre_r6_stack"]["missed_by_all_sources"] == 2
    assert report["summary"]["current_stack"]["missed_by_all_sources"] == 0
    assert report["summary"]["capture_lag"][SOURCE_R6_PRICE_MOVE] == {
        "count": 2,
        "median": 0.0,
        "p90": 0,
    }
    assert report["meta"]["r6_price_move"]["production_launch_date"] == "2026-07-05"

    markdown = render_markdown(report)
    assert "pre-R6 stack overall miss rate" in markdown
    assert "current stack overall miss rate" in markdown
    assert "r6_price_move" in markdown
    assert "R6 production launch date: 2026-07-05" in markdown


def test_capture_lag_summary_uses_first_trigger_relative_to_episode_start():
    episodes = [
        {
            "episode_id": "AAA:2026-03-03",
            "symbol": "AAA",
            "start_date": "2026-03-03",
            "end_date": "2026-03-05",
            "direction": "up",
            "peak_return_pct": 12.0,
            "event_dates": ["2026-03-03", "2026-03-04", "2026-03-05"],
        },
        {
            "episode_id": "BBB:2026-03-05",
            "symbol": "BBB",
            "start_date": "2026-03-05",
            "end_date": "2026-03-07",
            "direction": "down",
            "peak_return_pct": -11.0,
            "event_dates": ["2026-03-05", "2026-03-06", "2026-03-07"],
        },
    ]
    trading_dates = _dates("2026-03-01", 8)
    coverage = {
        source: {
            "status": "ok",
            "start": trading_dates[0],
            "effective_start": trading_dates[0],
            "end": trading_dates[-1],
        }
        for source in [SOURCE_LHB, SOURCE_R6_PRICE_MOVE]
    }
    for source in set(SOURCES) - set(coverage):
        coverage[source] = {"status": "no_coverage", "start": None, "effective_start": None, "end": None}
    triggered_by_symbol = {
        "AAA": {SOURCE_LHB: {"2026-03-02", "2026-03-05"}, SOURCE_R6_PRICE_MOVE: set()},
        "BBB": {SOURCE_LHB: {"2026-03-07"}, SOURCE_R6_PRICE_MOVE: set()},
    }

    summary = summarize_backscan(
        episodes=episodes,
        triggered_by_symbol=triggered_by_symbol,
        trading_dates=trading_dates,
        coverage=coverage,
    )

    assert summary["capture_lag"][SOURCE_LHB] == {"count": 2, "median": 0.5, "p90": 2}
