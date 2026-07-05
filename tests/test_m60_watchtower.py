from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from backend.tools.m60_watchtower import (
    build_watchtower_report,
    compute_price_volume_signals,
    compute_sector_resonance,
    render_markdown,
)
from backend.tools.m60_thesis_conditions import (
    compile_condition,
    compile_forward_thesis_conditions,
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
            super_large_net REAL,
            large_net REAL,
            medium_net REAL,
            small_net REAL,
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


def _write_watchlist(tmp_path, entry, filename="theme.json"):
    watchlist_dir = tmp_path / "watchlists"
    watchlist_dir.mkdir(exist_ok=True)
    entry.setdefault("created_at", "2026-07-03")
    entry.setdefault("source_ref", "unit")
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


def test_thesis_condition_compiler_covers_four_templates_and_manual():
    price = compile_condition("若回调 8% 则证伪", condition_type="invalidation")
    flow = compile_condition("主力净流入持续 3 日", condition_type="validation")
    event = compile_condition("公告/研报出现关键词: 合同", condition_type="validation")
    overseas = compile_condition("海外映射标的上涨 5%", condition_type="validation")
    manual = compile_condition("管理层战略执行力明显变差", condition_type="invalidation")

    assert price["kind"] == "price_pct_move"
    assert price["params"]["direction"] == "down"
    assert flow["kind"] == "fund_flow_streak"
    assert flow["params"]["days"] == 3
    assert event["kind"] == "event_keyword"
    assert "合同" in event["params"]["keywords"]
    assert overseas["kind"] == "overseas_pct_move"
    assert manual["kind"] == "manual_review"


def _insert_theme_thesis(con, *, theme_key="thesis_theme", validation=None, invalidation=None):
    con.execute(
        """
        INSERT INTO forward_theses(
            statement, status, follow_up_metrics_json, invalidation_conditions_json, updated_at
        )
        VALUES (?, 'active', ?, ?, '2026-07-01 00:00:00')
        """,
        (
            f"[theme:{theme_key}]测试论点",
            json.dumps(validation or [], ensure_ascii=False),
            json.dumps(invalidation or [], ensure_ascii=False),
        ),
    )


def test_compile_forward_thesis_conditions_persists_specs(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        _insert_theme_thesis(
            con,
            validation=["主力净流入持续 2 日", "公告出现关键词: 合同"],
            invalidation=["需要专家访谈确认"],
        )

    summary = compile_forward_thesis_conditions(db_path=db_path)

    assert summary["forward_theses"] == 1
    assert summary["total_conditions"] == 3
    assert summary["compiled_conditions"] == 2
    assert summary["manual_review_conditions"] == 1
    with sqlite3.connect(db_path) as con:
        rows = con.execute("SELECT compiled_by, spec_json FROM thesis_condition_specs ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["rule", "rule", "manual"]


def test_build_watchtower_report_thesis_validation_triggers_and_queues_rule(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        for d, value in (("2026-07-04", 100.0), ("2026-07-05", 101.0)):
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', ?, ?, ?, ?, ?, 1000)",
                (d, value, value, value, value),
            )
        con.execute(
            "INSERT INTO fund_flows(symbol, trade_date, main_net, provider) VALUES ('A', '2026-07-04', 10, 'unit')"
        )
        con.execute(
            "INSERT INTO fund_flows(symbol, trade_date, main_net, provider) VALUES ('A', '2026-07-05', 20, 'unit')"
        )
        _insert_theme_thesis(con, validation=["主力净流入持续 2 日"])
    compile_forward_thesis_conditions(db_path=db_path)
    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "thesis_theme",
            "title": "论点主题",
            "thesis": "test",
            "symbols": ["A"],
            "validation_conditions": [],
            "invalidation_conditions": [],
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    triggers = [t for t in report["triggers"] if t["trigger_type"] == "thesis_validation"]
    assert len(triggers) == 1
    assert triggers[0]["trigger_rule"] == "R7_thesis_validated"
    assert triggers[0]["detail"]["state_machine_unchanged"] is True
    assert "论点验证进展" in triggers[0]["card"]


def test_build_watchtower_report_thesis_invalidation_flags_holding_risk(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', '2026-07-04', 100, 100, 100, 100, 1000)"
        )
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', '2026-07-05', 91, 91, 91, 91, 1000)"
        )
        con.execute("INSERT INTO positions(symbol, closed_at) VALUES ('A', NULL)")
        _insert_theme_thesis(con, invalidation=["回调 8%"])
    compile_forward_thesis_conditions(db_path=db_path)
    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "thesis_theme",
            "title": "论点主题",
            "thesis": "test",
            "symbols": ["A"],
            "validation_conditions": [],
            "invalidation_conditions": [],
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    triggers = [t for t in report["triggers"] if t["trigger_type"] == "thesis_invalidation"]
    assert len(triggers) == 1
    assert triggers[0]["detail"]["holding_thesis_risk"] is True
    assert "持仓论点风险" in triggers[0]["card"]


def test_build_watchtower_report_thesis_conditions_respect_pit_and_damper(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        for d, value in (("2026-07-04", 100.0), ("2026-07-05", 101.0), ("2026-07-06", 110.0)):
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', ?, ?, ?, ?, ?, 1000)",
                (d, value, value, value, value),
            )
        con.execute(
            "INSERT INTO announcements(symbol, title, published_at) VALUES ('A', 'A公司获得重大合同', '2026-07-06 09:00:00')"
        )
        _insert_theme_thesis(con, validation=["公告出现关键词: 合同"])
    compile_forward_thesis_conditions(db_path=db_path)
    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "thesis_theme",
            "title": "论点主题",
            "thesis": "test",
            "symbols": ["A"],
            "validation_conditions": [],
            "invalidation_conditions": [],
        },
    )

    pit_report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)
    assert [t for t in pit_report["triggers"] if t["trigger_type"] == "thesis_validation"] == []

    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            INSERT INTO m60_watchtower_trigger_history(date, target, trigger_type)
            VALUES ('2026-07-05', 'thesis_theme', 'thesis_validation')
            """
        )
    damped_report = build_watchtower_report(db_path=db_path, as_of="2026-07-06", watchlist_dir=watchlist_dir)
    assert [t for t in damped_report["triggers"] if t["trigger_type"] == "thesis_validation"] == []


def test_m63_router_enqueues_thesis_validation_only(tmp_path):
    from backend.tools.m63_daily import run_trigger_router

    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', '2026-07-05', 10, 10, 10, 10, 1000)"
        )
    watchtower = {
        "triggers": [
            {"symbol": "A", "themes": ["thesis_theme"], "trigger_type": "thesis_validation", "trigger_rule": "R7_thesis_validated", "card": "论点验证进展"},
            {"symbol": "A", "themes": ["thesis_theme"], "trigger_type": "thesis_invalidation", "trigger_rule": "R7_thesis_invalidated", "card": "论点证伪警报"},
        ]
    }

    result = run_trigger_router(
        db_path=db_path,
        as_of="2026-07-05",
        watchtower=watchtower,
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        allow_auto_refresh=False,
    )

    r7_items = [item for item in result["pending"] if item["trigger_rule"] == "R7_thesis_validated"]
    assert len(r7_items) == 1
    assert r7_items[0]["target"] == "A"
    assert not [item for item in result["pending"] if item["trigger_rule"] == "R7_thesis_invalidated"]


def test_build_watchtower_report_lhb_spotlight_fires_for_watchlist_symbol(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', '2026-07-05', 10, 10, 10, 10, 1000)"
        )
        con.execute(
            """
            INSERT INTO lhb_records(symbol, trade_date, reason, net_buy_amount, provider)
            VALUES ('A', '2026-07-05 00:00:00', '日涨幅偏离值达7%', 12345678.0, 'unit')
            """
        )
        con.execute(
            """
            INSERT INTO lhb_records(symbol, trade_date, reason, net_buy_amount, provider)
            VALUES ('OFF', '2026-07-05 00:00:00', '非关注面', 999.0, 'unit')
            """
        )

    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "lhb_theme",
            "title": "龙虎榜主题",
            "thesis": "test placeholder",
            "symbols": ["A"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-05", watchlist_dir=watchlist_dir)

    triggers = [t for t in report["triggers"] if t["trigger_type"] == "lhb_spotlight"]
    assert len(triggers) == 1
    assert triggers[0]["symbol"] == "A"
    assert triggers[0]["value"] == 12345678.0
    assert triggers[0]["detail"]["net_buy_amount"] == 12345678.0
    assert "龙虎榜上榜" in triggers[0]["card"]
    assert all(t["symbol"] != "OFF" for t in report["triggers"])


def test_build_watchtower_report_lhb_spotlight_damped_within_five_trading_days(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        for day in range(1, 7):
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', ?, 10, 10, 10, 10, 1000)",
                (f"2026-07-0{day}",),
            )
        con.execute(
            """
            INSERT INTO lhb_records(symbol, trade_date, reason, net_buy_amount, provider)
            VALUES ('A', '2026-07-03 00:00:00', '前次上榜', 100.0, 'unit')
            """
        )
        con.execute(
            """
            INSERT INTO lhb_records(symbol, trade_date, reason, net_buy_amount, provider)
            VALUES ('A', '2026-07-06 00:00:00', '再次上榜', 200.0, 'unit')
            """
        )
    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "lhb_theme",
            "title": "龙虎榜主题",
            "thesis": "test placeholder",
            "symbols": ["A"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-06", watchlist_dir=watchlist_dir)

    assert all(t["trigger_type"] != "lhb_spotlight" for t in report["triggers"])


def test_build_watchtower_report_flow_anomaly_fires_and_reports_insufficient_history(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        base = date(2026, 5, 1)
        for symbol in ("A", "B", "C"):
            for idx in range(60):
                con.execute(
                    "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, ?, 10, 10, 10, 10, 1000)",
                    (symbol, (base + timedelta(days=idx)).isoformat()),
                )
        for idx in range(60):
            day = (base + timedelta(days=idx)).isoformat()
            main_net = 1000.0 + (idx % 7) * 10.0 if idx < 59 else 5000.0
            con.execute(
                """
                INSERT INTO fund_flows(symbol, trade_date, main_net, provider)
                VALUES ('A', ?, ?, 'unit')
                """,
                (f"{day} 00:00:00", main_net),
            )
        for idx in range(60):
            day = (base + timedelta(days=idx)).isoformat()
            con.execute(
                """
                INSERT INTO fund_flows(symbol, trade_date, main_net, provider)
                VALUES ('B', ?, ?, 'unit')
                """,
                (f"{day} 00:00:00", 1000.0 + (idx % 7) * 10.0),
            )
        for idx in range(19):
            day = (base + timedelta(days=41 + idx)).isoformat()
            con.execute(
                """
                INSERT INTO fund_flows(symbol, trade_date, main_net, provider)
                VALUES ('C', ?, 1000.0, 'unit')
                """,
                (f"{day} 00:00:00",),
            )

    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "flow_theme",
            "title": "资金流主题",
            "thesis": "test placeholder",
            "symbols": ["A", "B", "C"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-06-29", watchlist_dir=watchlist_dir)

    triggers = [t for t in report["triggers"] if t["trigger_type"] == "flow_anomaly"]
    assert len(triggers) == 1
    assert triggers[0]["symbol"] == "A"
    assert triggers[0]["detail"]["rows_used"] == 60
    assert triggers[0]["detail"]["as_of_main_net"] == 5000.0
    assert triggers[0]["value"] >= 2.5
    assert report["coverage"]["fund_flow_insufficient_history_count"] == 1
    assert report["coverage"]["fund_flow_insufficient_history_symbols"] == ["C"]
    assert "资金流历史不足 1 支跳过" in render_markdown(report)


def test_build_watchtower_report_flow_anomaly_damped_within_five_trading_days(tmp_path):
    db_path = tmp_path / "watchtower.sqlite"
    with _init_watchtower_db(db_path) as con:
        base = date(2026, 5, 1)
        for idx in range(65):
            day = (base + timedelta(days=idx)).isoformat()
            con.execute(
                "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('A', ?, 10, 10, 10, 10, 1000)",
                (day,),
            )
            main_net = 1000.0 + (idx % 7) * 10.0
            if idx == 64:
                main_net = 5000.0
            con.execute(
                """
                INSERT INTO fund_flows(symbol, trade_date, main_net, provider)
                VALUES ('A', ?, ?, 'unit')
                """,
                (f"{day} 00:00:00", main_net),
            )
        con.execute(
            """
            INSERT INTO m60_watchtower_trigger_history(date, target, trigger_type)
            VALUES ('2026-07-01', 'A', 'flow_anomaly')
            """
        )
    watchlist_dir = _write_watchlist(
        tmp_path,
        {
            "theme_key": "flow_theme",
            "title": "资金流主题",
            "thesis": "test placeholder",
            "symbols": ["A"],
            "validation_conditions": ["x"],
            "invalidation_conditions": ["y"],
            "created_at": "2026-07-03",
            "source_ref": "pending",
        },
    )

    report = build_watchtower_report(db_path=db_path, as_of="2026-07-04", watchlist_dir=watchlist_dir)

    assert all(t["trigger_type"] != "flow_anomaly" for t in report["triggers"])
