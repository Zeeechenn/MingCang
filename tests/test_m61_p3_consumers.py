from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta


def test_stock_context_includes_unified_context_pack_and_text(test_db, sample_stocks, monkeypatch):
    import backend.agent.context as agent_context

    captured = {}

    def fake_build(symbol, *, sections, db):
        captured["symbol"] = symbol
        captured["sections"] = sections
        captured["db"] = db
        return {
            "symbol": symbol,
            "as_of": "2026-07-04T15:00:00",
            "price": {"last_close": 100},
            "financials": {"empty": True},
            "research_reports": {"empty": True},
            "announcements": {"empty": True},
            "corporate_events": {"empty": True},
            "holders": {"empty": True},
            "fund_flow": {"empty": True},
            "lhb": {"empty": True},
            "data_health": {"empty": True},
        }

    monkeypatch.setattr(agent_context, "build_stock_context_pack", fake_build)
    monkeypatch.setattr(
        agent_context,
        "render_context_text",
        lambda pack, max_chars: f"text:{pack['symbol']}:{max_chars}",
    )

    payload = agent_context.mingcang_stock_context(test_db, "603986")

    assert captured == {
        "symbol": "603986",
        "sections": [
            "price",
            "financials",
            "research_reports",
            "announcements",
            "corporate_events",
            "holders",
            "fund_flow",
            "lhb",
            "data_health",
        ],
        "db": test_db,
    }
    assert "news" not in payload["context_pack"]
    assert payload["context_pack"]["price"]["last_close"] == 100
    assert payload["context_text"] == "text:603986:3000"
    assert payload["latest_signal"] is None


def test_stock_context_pack_failure_keeps_payload_valid(test_db, monkeypatch):
    import backend.agent.context as agent_context

    def boom(*args, **kwargs):
        raise RuntimeError("pack unavailable")

    monkeypatch.setattr(agent_context, "build_stock_context_pack", boom)

    payload = agent_context.mingcang_stock_context(test_db, "999999")

    assert payload["symbol"] == "999999"
    assert payload["stock"] is None
    assert payload["context_pack"] == {"error": "pack unavailable"}
    assert payload["context_text"] == ""


def _init_panel_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE stocks (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            market TEXT,
            active BOOLEAN,
            industry TEXT
        );
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
        );
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            composite_score REAL,
            recommendation TEXT,
            confidence TEXT,
            stop_loss REAL,
            take_profit REAL
        );
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            name TEXT,
            market TEXT,
            quantity REAL,
            avg_cost REAL,
            opened_at TEXT,
            stop_loss REAL,
            take_profit REAL,
            status TEXT
        );
        CREATE TABLE long_term_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            label TEXT,
            score REAL,
            expires_at TEXT,
            quality TEXT,
            created_at DATETIME
        );
        CREATE TABLE stock_memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            memory_type TEXT,
            summary TEXT NOT NULL,
            created_at DATETIME
        );
        CREATE TABLE financial_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            report_date TEXT,
            disclosure_date TEXT,
            period_type TEXT,
            revenue REAL,
            revenue_yoy REAL,
            net_profit REAL,
            net_profit_yoy REAL,
            total_assets REAL,
            total_equity REAL,
            long_term_debt REAL,
            current_ratio REAL,
            operating_cf REAL,
            shares_outstanding REAL,
            gross_margin REAL,
            roe REAL,
            asset_turnover REAL,
            raw_json TEXT,
            fetched_at DATETIME
        );
        CREATE TABLE holder_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            report_date DATETIME,
            total_shares REAL,
            float_shares REAL,
            top10_json TEXT,
            holder_count INTEGER,
            provider TEXT,
            fetched_at DATETIME
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
        CREATE TABLE corporate_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            event_type TEXT,
            title TEXT,
            event_date DATETIME,
            detail TEXT,
            provider TEXT
        );
        CREATE TABLE degradation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME,
            component TEXT,
            category TEXT,
            provider TEXT,
            error TEXT,
            context_json TEXT
        );
        """
    )
    return con


def _seed_panel_rows(con):
    as_of = datetime(2026, 7, 4)
    con.execute("INSERT INTO stocks(symbol, name, market, active) VALUES ('603986', '兆易创新', 'CN', 1)")
    con.execute(
        """
        INSERT INTO positions(symbol, name, market, quantity, avg_cost, opened_at, stop_loss, take_profit, status)
        VALUES ('603986', '兆易创新', 'CN', 100, 100, '2026-06-01', 95, 130, 'open')
        """
    )
    for idx in range(30):
        day = as_of - timedelta(days=29 - idx)
        close = 100 + idx
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("603986", day.strftime("%Y-%m-%d"), close, close, close, close, 1000),
        )
        con.execute(
            "INSERT INTO fund_flows(symbol, trade_date, main_net, provider) VALUES (?, ?, ?, ?)",
            ("603986", day.isoformat(), float((idx + 1) * 100), "unit"),
        )
    con.execute(
        """
        INSERT INTO signals(symbol, date, composite_score, recommendation, confidence, stop_loss, take_profit)
        VALUES ('603986', '2026-07-04', 70, '买入', '高', 95, 130)
        """
    )
    for report_date, total_assets, long_debt, current_ratio, gross_margin, asset_turnover in (
        ("2025-03-31", 2000, 120, 1.4, 30, 0.45),
        ("2026-03-31", 2100, 100, 1.8, 35, 0.50),
    ):
        con.execute(
            """
            INSERT INTO financial_metrics(
              symbol, report_date, disclosure_date, period_type, revenue, revenue_yoy,
              net_profit, net_profit_yoy, total_assets, total_equity, long_term_debt,
              current_ratio, operating_cf, shares_outstanding, gross_margin, roe, asset_turnover
            )
            VALUES ('603986', ?, '2026-04-30', 'Q1', 1000, 10, 120, 15, ?, 1000, ?, ?, 150, 100, ?, 12, ?)
            """,
            (report_date, total_assets, long_debt, current_ratio, gross_margin, asset_turnover),
        )
        con.execute(
            """
            INSERT INTO holder_snapshots(symbol, report_date, total_shares, float_shares, holder_count, provider)
            VALUES ('603986', ?, 100, 80, 50000, 'unit')
            """,
            (report_date,),
        )
    con.execute(
        """
        INSERT INTO corporate_events(symbol, event_type, title, event_date, detail, provider)
        VALUES ('603986', '解禁', '限售股解禁', '2026-07-20', '解禁测试详情', 'unit')
        """
    )
    con.execute(
        """
        INSERT INTO corporate_events(symbol, event_type, title, event_date, detail, provider)
        VALUES ('603986', '回购', '回购提示', '2026-07-10', '不应进入避雷', 'unit')
        """
    )
    con.execute(
        """
        INSERT INTO degradation_events(ts, component, category, provider, error, context_json)
        VALUES ('2026-07-04 10:00:00', 'm52_flow_floor', 'fund_flow', 'db', 'no_pit_data', '{"symbol":"603986"}')
        """
    )
    con.commit()


def test_m59_panel_adds_event_warning_position_fields_and_data_health(tmp_path, monkeypatch):
    import backend.tools.m59_panel as m59_panel

    db_path = tmp_path / "m61-panel.sqlite"
    universe_path = tmp_path / "universe.json"
    universe_path.write_text('{"stocks":[{"symbol":"603986","name":"兆易创新"}]}', encoding="utf-8")
    with _init_panel_db(db_path) as con:
        _seed_panel_rows(con)
    monkeypatch.setattr(m59_panel.flow_floor, "compute_s_flow_data", lambda raw: 0.42)

    panel = m59_panel.build_panel(
        db_path=db_path,
        as_of="2026-07-04",
        universe_path=universe_path,
        watchtower_output_dir=tmp_path,
    )
    markdown = m59_panel.render_markdown(panel)

    assert panel["risk_warnings"]["event_warnings"]["items"] == [
        {
            "symbol": "603986",
            "name": "兆易创新",
            "event_type": "解禁",
            "event_date": "2026-07-20",
            "detail": "解禁测试详情",
            "line": "⚠️ 603986 兆易创新 解禁 2026-07-20 (解禁测试详情)",
        }
    ]
    health = panel["position_health"]["items"][0]
    assert health["piotroski"] == "8/9"
    assert health["s_flow"] == 0.42
    assert health["next_event"] == "回购 2026-07-10"
    assert panel["data_health"]["recent_degradations_by_component"] == {"m52_flow_floor": 1}
    assert "north_net_buy" in panel["data_health"]["active_fake_feature_flags"]
    assert "⚠️ 603986 兆易创新 解禁 2026-07-20 (解禁测试详情)" in markdown
    assert "## 数据健康区" in markdown
    assert "m52_flow_floor | 1" in markdown
