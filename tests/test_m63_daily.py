from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.tools import m63_daily
from backend.tools.m63_render import assert_no_trade_words, enforce_language_guard, render_report


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


def test_language_guard_sanitize_replaces_and_counts_hits():
    text = enforce_language_guard("强烈推荐，buy now，目标价 12", mode="sanitize")

    assert "强烈推荐" not in text
    assert "buy now" not in text
    assert "目标价" not in text
    assert text.count("[操作词已屏蔽]") == 3
    assert "⚠️ 语言守卫：已屏蔽 3 处操作性表述(合规设计,系统不输出买卖指令,非错误)" in text


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
            "m60_second_entry": lambda: {"summary": {"entries": 0}},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m58_exit_shadow": lambda: {"meta": {"window": {"start": "2026-07-01", "end": "2026-07-05"}}, "no_divergence_yet": True, "open_position_count": 1},
            "m59_panel": lambda: {"summary": {"text": "今日候选0只/持仓1只"}, "position_health": {"items": []}, "risk_warnings": {"event_warnings": {"items": []}}},
            "trigger_router": lambda: {"queue_path": str(queue_path), "history_path": str(history_path), "pending": []},
        },
    )

    assert "⚠️ m61_backfill_drip 失败:RuntimeError: boom" in report["text"]
    assert "m59_panel:OK" in report["text"]


def test_postmarket_runs_second_entry_after_watchtower(tmp_path):
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
            "m61_backfill_drip": lambda: {},
            "m60_watchtower": lambda: {"summary": {"text": "观察哨完成"}, "triggers": []},
            "m60_second_entry": lambda: {"summary": {"entries": 0}},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m58_exit_shadow": lambda: {"meta": {"window": {}}, "no_divergence_yet": True, "open_position_count": 1},
            "m59_panel": lambda: {"summary": {"text": "面板"}, "position_health": {"items": []}, "risk_warnings": {"event_warnings": {"items": []}}},
            "trigger_router": lambda: {"queue_path": str(queue_path), "history_path": str(history_path), "pending": []},
        },
    )

    names = [step["name"] for step in report["steps"]]
    assert names.index("m60_watchtower") < names.index("m60_second_entry")
    assert "m60_second_entry:OK" in report["text"]


def test_postmarket_final_text_uses_sanitize_language_guard(tmp_path):
    db_path = _db(tmp_path)
    result = m63_daily.build_postmarket_report(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=True,
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        step_overrides={
            "m61_backfill_drip": lambda: {},
            "m60_watchtower": lambda: {"summary": {"text": "观察哨强烈推荐"}, "triggers": []},
            "m60_second_entry": lambda: {},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m58_exit_shadow": lambda: {"meta": {"window": {}}, "no_divergence_yet": True, "open_position_count": 1},
            "m59_panel": lambda: {"summary": {"text": "面板"}, "position_health": {"items": []}, "risk_warnings": {"event_warnings": {"items": []}}},
            "trigger_router": lambda: {"queue_path": str(tmp_path / "queue.json"), "history_path": str(tmp_path / "history.json"), "pending": []},
        },
    )

    assert "强烈推荐" not in result["text"]
    assert "[操作词已屏蔽]" in result["text"]
    assert "语言守卫" in result["text"]


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


def _write_universe(path: Path, symbols: list[str]) -> None:
    path.write_text(
        json.dumps({"stocks": [{"symbol": symbol, "name": symbol} for symbol in symbols]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _replace_prices(db_path: Path, symbol: str, closes: list[tuple[str, float]]) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute("DELETE FROM prices WHERE symbol = ?", (symbol,))
        con.executemany(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume, atr14)
            VALUES (?, ?, ?, ?, ?, ?, 10000, 2.5)
            """,
            [(symbol, day, close, close, close, close) for day, close in closes],
        )
        con.commit()
    finally:
        con.close()


def test_trigger_r6_enqueues_5d_mover_and_records_history(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, ["300308"])
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe_path,))
    _replace_prices(
        db_path,
        "300308",
        [
            ("2026-06-29", 100),
            ("2026-06-30", 99),
            ("2026-07-01", 97),
            ("2026-07-02", 94),
            ("2026-07-03", 91),
            ("2026-07-06", 88),
        ],
    )
    queue_path = tmp_path / "queue.json"
    history_path = tmp_path / "history.json"

    result = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-06",
        queue_path=queue_path,
        history_path=history_path,
        allow_auto_refresh=False,
    )

    r6_items = [item for item in result["pending"] if item["trigger_rule"] == "R6_price_move"]
    assert len(r6_items) == 1
    assert r6_items[0]["target"] == "300308"
    assert "价格异动 1日-3.3%/5日-12.0%" in r6_items[0]["reason"]
    assert "急跌(考虑持仓决断/避雷复核)" in r6_items[0]["reason"]
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert any(item["target"] == "300308" and item["trigger_type"] == "R6_price_move" for item in history)


def test_trigger_r6_damper_blocks_duplicate_after_done_next_day(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, ["300308"])
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe_path,))
    _replace_prices(
        db_path,
        "300308",
        [
            ("2026-06-29", 100),
            ("2026-06-30", 99),
            ("2026-07-01", 97),
            ("2026-07-02", 94),
            ("2026-07-03", 91),
            ("2026-07-06", 88),
            ("2026-07-07", 86),
        ],
    )
    queue_path = tmp_path / "queue.json"
    history_path = tmp_path / "history.json"

    first = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-06",
        queue_path=queue_path,
        history_path=history_path,
        allow_auto_refresh=False,
    )
    queue = m63_daily.load_queue(queue_path)
    queue[0]["status"] = "done"
    queue[0]["done_at"] = "2026-07-06"
    m63_daily.save_queue(queue, queue_path)
    second = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-07",
        queue_path=queue_path,
        history_path=history_path,
        allow_auto_refresh=False,
    )

    assert sum(item["trigger_rule"] == "R6_price_move" for item in first["pending"]) == 1
    assert sum(item["trigger_rule"] == "R6_price_move" for item in m63_daily.load_queue(queue_path)) == 1
    assert not [item for item in second["enqueued"] if item["trigger_rule"] == "R6_price_move"]


def test_trigger_r6_below_threshold_does_not_fire(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, ["300308"])
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe_path,))
    _replace_prices(
        db_path,
        "300308",
        [
            ("2026-06-29", 100),
            ("2026-06-30", 100),
            ("2026-07-01", 99),
            ("2026-07-02", 98),
            ("2026-07-03", 97),
            ("2026-07-06", 96),
        ],
    )

    result = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-06",
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        allow_auto_refresh=False,
    )

    assert not [item for item in result["pending"] if item["trigger_rule"] == "R6_price_move"]


def test_trigger_r6_fires_on_1d_branch(tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    universe_path = tmp_path / "universe.json"
    _write_universe(universe_path, ["300308"])
    monkeypatch.setattr(m63_daily, "DEFAULT_UNIVERSE_PATHS", (universe_path,))
    _replace_prices(
        db_path,
        "300308",
        [
            ("2026-06-29", 100),
            ("2026-06-30", 101),
            ("2026-07-01", 99),
            ("2026-07-02", 100),
            ("2026-07-03", 99),
            ("2026-07-06", 107),
        ],
    )

    result = m63_daily.run_trigger_router(
        db_path=db_path,
        as_of="2026-07-06",
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        allow_auto_refresh=False,
    )

    r6_items = [item for item in result["pending"] if item["trigger_rule"] == "R6_price_move"]
    assert len(r6_items) == 1
    assert "1日+8.1%/5日+7.0%" in r6_items[0]["reason"]
    assert "急涨(考虑观察哨确认/第二时间评估)" in r6_items[0]["reason"]


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


def test_queue_compaction_keeps_pending_and_recent_done_only_latest(tmp_path):
    path = tmp_path / "queue.json"
    queue = [
        {
            "id": "old",
            "created_at": "2026-05-01",
            "target": "300308",
            "trigger_rule": "R2_major_event",
            "status": "done",
            "done_at": "2026-05-01",
        },
        {
            "id": "recent-older",
            "created_at": "2026-06-20",
            "target": "300308",
            "trigger_rule": "R2_major_event",
            "status": "done",
            "done_at": "2026-06-20",
        },
        {
            "id": "recent-newer",
            "created_at": "2026-07-01",
            "target": "300308",
            "trigger_rule": "R2_major_event",
            "status": "done",
            "done_at": "2026-07-01",
        },
        {
            "id": "pending",
            "created_at": "2026-05-01",
            "target": "300394",
            "trigger_rule": "R5_weekly_sweep",
            "status": "pending",
        },
    ]

    m63_daily.save_queue(queue, path)

    saved = m63_daily.load_queue(path)
    assert [item["id"] for item in saved] == ["pending", "recent-newer"]


def test_panel_lines_surface_hard_rule_fields():
    lines = m63_daily._panel_lines(
        {
            "summary": {"text": "面板"},
            "buy_candidates": {
                "items": [
                    {
                        "symbol": "300308",
                        "quality_flags": ["missing:piotroski"],
                        "research_reference": {"copilot": {"trigger_quality": "degraded"}},
                    },
                ]
            },
            "position_health": {
                "items": [
                    {
                        "symbol": "300394",
                        "current_price": 10,
                        "distance_to_stop_loss_pct": 1.2,
                        "research_reference": {"long_term_label": {"label": "观望"}},
                        "protective_action": "集中度超限:建议降到15%以内",
                        "stop_flags": ["止损贴身(<1.5×ATR,易被正常波动洗出)"],
                    }
                ]
            },
            "risk_warnings": {
                "event_warnings": {
                    "items": [
                        {
                            "symbol": "603986",
                            "name": "兆易创新",
                            "event_type": "解禁",
                            "event_date": "2026-07-08",
                            "protective_action": "解禁临近:建议临时压缩该仓位敞口",
                        }
                    ]
                },
                "momentum_tail": {
                    "items": [
                        {"symbol": "300476", "protective_action": "数据不足:无法给出动作"},
                    ]
                },
                "concentration": {
                    "items": [
                        {"symbol": "300394", "protective_action": "集中度未超15%单仓阈值,维持观察"},
                    ]
                },
            },
        }
    )

    text = "\n".join(lines)
    # 1 持仓保护动作 + 1 event_warnings 真动作;数据不足与"维持观察"不计数
    assert "保护动作 2 条 / 止损贴身旗 1 条 / 质量旗 1 条 / 触发降级 1 条" in text
    assert "保护动作: 集中度超限" in text
    assert "风险警示 603986 → 保护动作: 解禁临近" in text
    assert "风险警示 300476" not in text
    assert "风险警示 300394" not in text
    assert "旗标: 止损贴身" in text
    assert "质量旗标: missing:piotroski(建议仓位上限减半)" in text


def test_postmarket_report_keeps_protective_action_lines_readable_after_guard():
    report = m63_daily.build_postmarket_report(
        no_llm=True,
        step_overrides={
            "m61_backfill_drip": lambda: {"skipped": True, "reason": "unit"},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m60_watchtower": lambda: {"triggered": [], "pending": []},
            "m60_second_entry": lambda: {"skipped": True, "reason": "unit"},
            "m58_exit_shadow": lambda: {"open_position_count": 0, "no_divergence_yet": True, "meta": {"window": "unit"}},
            "m59_panel": lambda: {
                "summary": {"text": "面板"},
                "buy_candidates": {"items": []},
                "position_health": {"items": []},
                "risk_warnings": {
                    "event_warnings": {
                        "items": [
                            {
                                "symbol": "603986",
                                "name": "兆易创新",
                                "protective_action": "事件日前评估降仓;若持仓,止损上移至 85.0(=现价-1.5×ATR14)",
                            }
                        ]
                    },
                    "momentum_tail": {"items": []},
                    "concentration": {"items": []},
                },
            },
            "m59_discretion": lambda: {"skipped": True, "reason": "--no-llm"},
            "trigger_router": lambda: {"pending": [], "queue_path": "unit", "history_path": "unit"},
            "task_capsule": lambda: {"skipped": True, "reason": "unit"},
        },
    )

    protective_lines = [line for line in report["text"].splitlines() if "保护动作:" in line]
    assert protective_lines
    assert all("[操作词已屏蔽]" not in line for line in protective_lines)
    assert any("事件日前评估降仓" in line for line in protective_lines)


def test_panel_lines_explain_missing_stop_distance_and_avoid_holding():
    lines = m63_daily._panel_lines(
        {
            "summary": {"text": "面板"},
            "buy_candidates": {"items": []},
            "position_health": {
                "items": [
                    {
                        "symbol": "688111",
                        "current_price": 211.35,
                        "distance_to_stop_loss_pct": None,
                        "research_reference": {"long_term_label": {"label": "规避"}},
                    }
                ]
            },
            "risk_warnings": {"event_warnings": {"items": []}},
        }
    )

    text = "\n".join(lines)
    assert "持仓 688111 现价211.35 距止损- (止损数据缺失) 长期标签规避" in text
    assert "None%" not in text
    assert "长期标签(规避)与当前持仓并存" in text
    assert "持仓处置以止损纪律与保护动作为准" in text


def test_glossary_footnote_only_lists_terms_present():
    text = render_report(
        [("术语", ["ATR 用于止损位计算,观察哨触发 sector_resonance,1.5×ATR 进入影子出场 accrual"])],
        glossary_terms={"ATR", "EPS", "观察哨", "sector_resonance", "1.5×ATR", "影子出场", "accrual"},
    )

    assert "- ATR:" in text
    assert "- 止损位:" in text
    assert "- 观察哨:" in text
    assert "- sector_resonance:" in text
    assert "- 1.5×ATR:" in text
    assert "- 影子出场:" in text
    assert "- accrual:" in text
    assert "- EPS:" not in text
