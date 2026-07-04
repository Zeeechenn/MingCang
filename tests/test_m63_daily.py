from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.tools import m63_daily
from backend.tools.m63_render import assert_no_trade_words, render_report


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "m63.db"
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE stocks(symbol TEXT PRIMARY KEY, name TEXT, market TEXT, active BOOLEAN);
            CREATE TABLE positions(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                quantity REAL,
                avg_cost REAL,
                opened_at TEXT,
                stop_loss REAL,
                take_profit REAL,
                status TEXT
            );
            CREATE TABLE prices(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                atr14 REAL
            );
            CREATE TABLE signals(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                composite_score REAL,
                recommendation TEXT,
                confidence TEXT,
                stop_loss REAL,
                take_profit REAL
            );
            CREATE TABLE corporate_events(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                event_type TEXT,
                title TEXT,
                event_date TEXT,
                detail TEXT,
                provider TEXT
            );
            CREATE TABLE announcements(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                title TEXT,
                published_at TEXT,
                provider TEXT
            );
            CREATE TABLE news(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                title TEXT,
                url TEXT,
                published_at TEXT,
                source TEXT
            );
            CREATE TABLE overseas_snapshots(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                snap_date TEXT,
                close REAL,
                chg_pct_1d REAL,
                provider TEXT
            );
            CREATE TABLE long_term_labels(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                label TEXT,
                score REAL,
                expires_at TEXT,
                quality TEXT,
                created_at TEXT
            );
            """
        )
        con.execute("INSERT INTO stocks(symbol, name, market, active) VALUES ('300308', '中际旭创', 'CN', 1)")
        con.execute(
            """
            INSERT INTO corporate_events(symbol, event_type, title, event_date, provider)
            VALUES ('300308', '解禁', '限售股上市流通', '2026-07-05', 'unit')
            """
        )
        con.execute(
            """
            INSERT INTO positions(symbol, name, quantity, avg_cost, opened_at, stop_loss, take_profit, status)
            VALUES ('300308', '中际旭创', 10, 100, '2026-07-01', 97, 130, 'open')
            """
        )
        con.execute(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume, atr14)
            VALUES ('300308', '2026-07-04', 99, 101, 98, 100, 10000, 2.5),
                   ('300308', '2026-07-05', 98, 100, 96, 99, 12000, 2.5)
            """
        )
        con.commit()
    finally:
        con.close()
    return path


def test_premarket_renders_today_unlock_and_language_guard(tmp_path):
    db_path = _db(tmp_path)

    report = m63_daily.build_premarket_report(db_path=db_path, as_of="2026-07-05")

    assert "今日解禁" in report["text"]
    assert "300308" in report["text"]
    assert "买入" not in report["text"]
    assert_no_trade_words(report["text"])
    with pytest.raises(ValueError):
        assert_no_trade_words("今天买入并加仓")


def test_intraday_proximity_alert_math(tmp_path):
    db_path = _db(tmp_path)

    report = m63_daily.build_intraday_report(
        db_path=db_path,
        as_of="2026-07-05",
        watchtower_builder=lambda **_: {"summary": {"text": "今日清单内无触发"}, "triggers": []},
    )

    assert "距止损位 2.02%" in report["text"]
    assert "以上仅记录,决断在盘后。" in report["text"]
    assert_no_trade_words(report["text"])


def test_postmarket_continues_past_failing_step(tmp_path):
    db_path = _db(tmp_path)
    queue_path = tmp_path / "queue.json"
    history_path = tmp_path / "history.json"

    report = m63_daily.build_postmarket_report(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=True,
        queue_path=queue_path,
        history_path=history_path,
        step_overrides={
            "m61_backfill_drip": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            "m60_watchtower": lambda: {"summary": {"text": "观察哨完成"}, "triggers": []},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m58_exit_shadow": lambda: {"meta": {"window": {"start": "2026-07-01", "end": "2026-07-05"}}, "no_divergence_yet": True, "open_position_count": 1},
            "m59_panel": lambda: {"summary": {"text": "今日候选0只/持仓1只"}, "position_health": {"items": []}, "risk_warnings": {"event_warnings": {"items": []}}},
            "trigger_router": lambda: {"queue_path": str(queue_path), "history_path": str(history_path), "pending": []},
        },
    )

    assert "⚠️ m61_backfill_drip 失败:RuntimeError: boom" in report["text"]
    assert "m59_panel:OK" in report["text"]


def test_trigger_r1_enqueues_beyond_limit_and_auto_refreshes_first_n(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    # M63 关注面口径 = universe 文件 ∪ 持仓(全库 active 不再入关注面)——测试自带 universe 文件
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(
        json.dumps({"stocks": [{"symbol": f"60000{idx}", "name": f"60000{idx}"} for idx in range(7)]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe_path,))
    con = sqlite3.connect(db_path)
    try:
        for idx in range(7):
            symbol = f"60000{idx}"
            con.execute("INSERT INTO stocks(symbol, name, market, active) VALUES (?, ?, 'CN', 1)", (symbol, symbol))
            con.execute(
                """
                INSERT INTO long_term_labels(symbol, date, label, score, expires_at, quality, created_at)
                VALUES (?, '2026-06-01', '观望', 0, '2026-07-01', 'trusted', '2026-06-01')
                """,
                (symbol,),
            )
        con.commit()
    finally:
        con.close()
    refreshed: list[str] = []

    result = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-05",
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        auto_refresh_limit=5,
        auto_refresh_fn=refreshed.append,
    )

    assert len(refreshed) == 5
    queued = [item for item in result["pending"] if item["trigger_rule"] == "R1_label_expired"]
    assert len(queued) == 2


def test_trigger_r2_enqueues_with_dedup(tmp_path):
    db_path = _db(tmp_path)
    queue_path = tmp_path / "queue.json"

    first = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-05",
        queue_path=queue_path,
        history_path=tmp_path / "history.json",
        auto_refresh_fn=lambda symbol: None,
    )
    second = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-05",
        queue_path=queue_path,
        history_path=tmp_path / "history.json",
        auto_refresh_fn=lambda symbol: None,
    )

    assert len([item for item in first["pending"] if item["trigger_rule"] == "R2_major_event"]) == 1
    assert len([item for item in second["pending"] if item["trigger_rule"] == "R2_major_event"]) == 1


def test_queue_file_round_trip(tmp_path):
    path = tmp_path / "queue.json"
    queue = [
        {
            "id": "2026-07-05:R2_major_event:300308",
            "created_at": "2026-07-05",
            "target": "300308",
            "reason": "今日事件:解禁",
            "trigger_rule": "R2_major_event",
            "status": "pending",
        }
    ]

    m63_daily.save_queue(queue, path)

    assert m63_daily.load_queue(path) == queue


def test_glossary_footnote_only_lists_terms_present():
    text = render_report([("术语", ["ATR 用于止损位计算"])], glossary_terms={"ATR", "EPS"})

    assert "- ATR:" in text
    assert "- 止损位:" in text
    assert "- EPS:" not in text
