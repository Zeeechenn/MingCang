from __future__ import annotations

import json
import sqlite3

from backend.tools.m60_watchtower import (
    build_watchtower_report,
    compute_price_volume_signals,
    compute_sector_resonance,
    render_markdown,
)


def _init_watchtower_db(path):
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
        """
    )
    return con


def _write_watchlist(tmp_path, entry, filename="theme.json"):
    watchlist_dir = tmp_path / "watchlists"
    watchlist_dir.mkdir(exist_ok=True)
    (watchlist_dir / filename).write_text(json.dumps(entry), encoding="utf-8")
    return watchlist_dir


def test_compute_price_volume_signals_insufficient_history_flags_missing():
    result = compute_price_volume_signals([{"date": "2026-07-01", "close": 100.0, "volume": 1000.0}])
    assert "missing:insufficient_price_history" in result["flags"]
    assert result["z_triggered"] is False
    assert result["volume_triggered"] is False
    assert result["new_high_triggered"] is False


def test_compute_price_volume_signals_detects_anomaly_and_new_high():
    history = []
    closes = [100.0]
    for i in range(60):
        change = 0.5 if i % 2 == 0 else -0.5
        closes.append(closes[-1] * (1 + change / 100.0))
    closes.append(closes[-1] * 1.10)  # +10% jump on the final day
    for i, close in enumerate(closes):
        volume = 5000.0 if i == len(closes) - 1 else 1000.0
        history.append({"date": f"d{i:03d}", "close": close, "volume": volume})

    result = compute_price_volume_signals(
        history,
        lookback_days=60,
        volume_lookback_days=20,
        new_high_lookback_days=20,
        z_threshold=2.0,
        percentile_threshold=0.90,
        volume_ratio_threshold=2.0,
    )
    assert result["daily_return_pct"] is not None and result["daily_return_pct"] > 9.0
    assert result["z_triggered"] is True
    assert result["percentile_triggered"] is True
    assert result["volume_triggered"] is True
    assert result["volume_ratio"] == 5.0
    assert result["new_high_triggered"] is True
    assert result["flags"] == []


def test_compute_price_volume_signals_no_trigger_on_flat_prices():
    history = [{"date": f"d{i:03d}", "close": 100.0, "volume": 1000.0} for i in range(40)]
    result = compute_price_volume_signals(history, lookback_days=30, volume_lookback_days=20, new_high_lookback_days=20)
    assert result["daily_return_pct"] == 0.0
    assert result["z_triggered"] is False
    assert result["volume_triggered"] is False
    assert result["new_high_triggered"] is False


def test_compute_sector_resonance_triggers_on_majority_up_and_avg_gain():
    resonance = compute_sector_resonance(
        {"A": 3.0, "B": 2.5, "C": 3.5, "D": -1.0},
        min_ratio=0.5,
        min_avg_pct=1.5,
    )
    assert resonance["triggered"] is True
    assert resonance["up_ratio"] == 0.75
    assert resonance["up_member_symbols"] == ["A", "B", "C"]
    assert resonance["avg_up_pct"] == (3.0 + 2.5 + 3.5) / 3


def test_compute_sector_resonance_not_triggered_when_ratio_below_threshold():
    resonance = compute_sector_resonance({"A": 3.0, "B": -1.0, "C": -2.0}, min_ratio=0.5, min_avg_pct=1.5)
    assert resonance["triggered"] is False


def test_compute_sector_resonance_not_triggered_when_avg_below_threshold():
    resonance = compute_sector_resonance({"A": 1.0, "B": 0.8}, min_ratio=0.5, min_avg_pct=1.5)
    assert resonance["triggered"] is False


def test_compute_sector_resonance_reports_missing_price_symbols():
    resonance = compute_sector_resonance({"A": 3.0, "B": None})
    assert resonance["missing_price_symbols"] == ["B"]
    assert resonance["n_priced"] == 1


def test_build_watchtower_report_explicit_no_trigger_when_flat(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        for symbol in ("A", "B"):
            for day in range(1, 6):
                con.execute(
                    "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (symbol, f"2026-07-0{day}", 100, 100, 100, 100, 1000),
                )
    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "flat_theme",
            "title": "平淡主题",
            "thesis": "test placeholder",
            "symbols": ["A", "B"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    assert report["schema_version"] == "m60_watchtower.v1"
    assert report["triggers"] == []
    assert report["summary"]["text"] == "今日清单内无触发"
    assert sorted(report["no_trigger_symbols"]) == ["A", "B"]
    assert "今日清单内无触发" in render_markdown(report)


def test_build_watchtower_report_missing_watchlist_dir_is_explicit(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path):
        pass

    report = build_watchtower_report(
        db_path=db_path, as_of="2026-07-05", watchlist_dir=tmp_path / "does_not_exist"
    )
    assert report["triggers"] == []
    assert report["themes"] == []
    assert any("missing:directory" in e for e in report["watchlist_errors"])
    assert report["summary"]["text"] == "今日清单内无触发"


def test_build_watchtower_report_detects_price_volume_anomaly(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    closes = [100.0]
    for i in range(60):
        change = 0.5 if i % 2 == 0 else -0.5
        closes.append(closes[-1] * (1 + change / 100.0))
    closes.append(closes[-1] * 1.10)
    dates = []
    year, month, day = 2026, 1, 1
    for _ in closes:
        dates.append(f"{year}-{month:02d}-{day:02d}")
        day += 1
        if day > 28:
            day = 1
            month += 1
    dates[-1] = "2026-07-05"  # as_of day, kept last chronologically for the WHERE date <= as_of filter

    with _init_watchtower_db(db_path) as con:
        for i, (d, close) in enumerate(zip(dates, closes)):
            volume = 5000.0 if i == len(closes) - 1 else 1000.0
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("A", d, close, close, close, close, volume),
            )
        # Symbol B stays flat/insufficient so it must not trigger.
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('B', '2026-07-05', 50, 50, 50, 50, 1000)"
        )

    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "one_mover",
            "title": "单点异动",
            "thesis": "test placeholder",
            "symbols": ["A", "B"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    triggered_types = {t["trigger_type"] for t in report["triggers"] if t["symbol"] == "A"}
    assert "price_z_anomaly" in triggered_types
    assert "price_percentile_anomaly" in triggered_types
    assert "volume_ratio_anomaly" in triggered_types
    assert "new_high_breakout" in triggered_types
    assert all(t["symbol"] == "A" for t in report["triggers"])
    assert report["summary"]["text"] != "今日清单内无触发"


def test_build_watchtower_report_sector_resonance_across_theme(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        # Yesterday all at 100; today three symbols jump ~3%, one drops.
        for symbol, today_close in (("A", 103.0), ("B", 103.0), ("C", 103.0), ("D", 98.0)):
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, '2026-07-04', 100, 100, 100, 100, 1000)",
                (symbol,),
            )
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, '2026-07-05', ?, ?, ?, ?, 1000)",
                (symbol, today_close, today_close, today_close, today_close),
            )

    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "resonant_theme",
            "title": "共振主题",
            "thesis": "test placeholder",
            "symbols": ["A", "B", "C", "D"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    resonance_triggers = [t for t in report["triggers"] if t["trigger_type"] == "sector_resonance"]
    assert {t["symbol"] for t in resonance_triggers} == {"A", "B", "C"}
    assert report["sector_resonance"]["resonant_theme"]["triggered"] is True


def test_build_watchtower_report_news_trigger_fires_on_announcement(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', '2026-07-04', 100, 100, 100, 100, 1000)"
        )
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', '2026-07-05', 100, 100, 100, 100, 1000)"
        )
        con.execute(
            """
            INSERT INTO news(symbol, title, url, published_at, source)
            VALUES ('A', 'A公司发布重大合同公告', 'http://example.com/a-1', '2026-07-05 09:00:00', 'eastmoney')
            """
        )

    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "news_theme",
            "title": "新闻触发主题",
            "thesis": "test placeholder",
            "symbols": ["A"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    news_triggers = [t for t in report["triggers"] if t["trigger_type"] == "news_trigger"]
    assert len(news_triggers) == 1
    assert news_triggers[0]["symbol"] == "A"
    assert "new_announcement_event" in news_triggers[0]["detail"]["reasons"] or (
        "policy_keyword_hit" in news_triggers[0]["detail"]["reasons"]
    )
