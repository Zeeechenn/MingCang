from __future__ import annotations

import sqlite3


def _init_minimal_db(path):
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
            volume REAL,
            atr14 REAL,
            fetched_at DATETIME
        );
        CREATE TABLE stocks (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            market TEXT,
            active BOOLEAN,
            industry TEXT,
            added_at DATETIME
        );
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            composite_score REAL,
            recommendation TEXT,
            confidence TEXT,
            stop_loss REAL,
            take_profit REAL,
            quant_score REAL,
            technical_score REAL,
            sentiment_score REAL,
            data_timestamp TEXT,
            created_at DATETIME
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
            closed_at TEXT,
            close_price REAL,
            realized_pnl REAL,
            realized_pnl_pct REAL,
            note TEXT,
            status TEXT,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            title TEXT,
            url TEXT,
            published_at DATETIME,
            source TEXT,
            fetched_at DATETIME
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
        """
    )
    return con


def test_m59_panel_schema_has_required_sections(tmp_path):
    from backend.tools.m59_panel import build_panel, render_markdown

    db_path = tmp_path / "m59.sqlite"
    with _init_minimal_db(db_path) as con:
        con.execute(
            "INSERT INTO stocks(symbol, name, market, active) VALUES ('300308', '中际旭创', 'CN', 1)"
        )
        con.execute(
            """
            INSERT INTO signals(symbol, date, composite_score, recommendation, confidence, stop_loss, take_profit)
            VALUES ('300308', '2026-07-03', 72.5, '买入', '高', 100, 130)
            """
        )
        con.execute(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume)
            VALUES ('300308', '2026-07-03', 110, 112, 108, 111, 1000)
            """
        )

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=tmp_path / "missing.json")

    assert panel["schema_version"] == "postmarket_panel.v1"
    assert set(panel) >= {
        "schema_version",
        "header",
        "buy_candidates",
        "position_health",
        "risk_warnings",
        "review_attribution",
    }
    assert panel["buy_candidates"]["items"][0]["llm_discretion"] is None
    assert panel["buy_candidates"]["items"][0]["llm_layer"] == "not_implemented"
    assert "买入候选" in render_markdown(panel)


def test_m59_panel_empty_database_does_not_crash(tmp_path):
    from backend.tools.m59_panel import build_panel

    db_path = tmp_path / "empty.sqlite"
    sqlite3.connect(db_path).close()

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=tmp_path / "missing.json")

    assert panel["header"]["as_of"] == "2026-07-03"
    assert panel["buy_candidates"]["items"] == []
    assert panel["position_health"]["items"] == []
    assert panel["risk_warnings"]["items"] == []
    assert panel["review_attribution"]["items"] == []
    assert "missing:table:signals" in panel["buy_candidates"]["flags"]
    assert "missing:table:prices" in panel["header"]["freshness"]["prices"]["status"]


def test_m59_panel_bottom_20_momentum_cross_section(tmp_path):
    from backend.tools.m59_panel import build_panel

    db_path = tmp_path / "momentum.sqlite"
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(
        """
        {"stocks": [
          {"symbol": "A", "name": "A股"},
          {"symbol": "B", "name": "B股"},
          {"symbol": "C", "name": "C股"},
          {"symbol": "D", "name": "D股"},
          {"symbol": "E", "name": "E股"}
        ]}
        """,
        encoding="utf-8",
    )
    dates = [f"2026-06-{day:02d}" for day in range(3, 31)] + ["2026-07-03"]
    final_close = {"A": 101, "B": 95, "C": 110, "D": 120, "E": 130}
    with _init_minimal_db(db_path) as con:
        for symbol in final_close:
            for i, day in enumerate(dates):
                close = 100.0
                if i == len(dates) - 6:
                    close = 100.0
                if i == len(dates) - 21:
                    close = 100.0
                if day == "2026-07-03":
                    close = float(final_close[symbol])
                con.execute(
                    "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (symbol, day, close, close, close, close, 1000),
                )
        con.execute(
            """
            INSERT INTO positions(symbol, name, market, quantity, avg_cost, opened_at, status)
            VALUES ('B', 'B股', 'CN', 100, 100, '2026-06-01', 'open')
            """
        )

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=universe_path)

    warnings = panel["risk_warnings"]["items"]
    assert [item["symbol"] for item in warnings] == ["B"]
    assert warnings[0]["warning_note"] == "预警≠卖出指令"
    assert warnings[0]["in_position"] is True
    assert warnings[0]["momentum_score"] == -0.05


def test_m59_panel_marks_missing_data_explicitly(tmp_path):
    from backend.tools.m59_panel import build_panel

    db_path = tmp_path / "missing.sqlite"
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(
        '{"stocks": [{"symbol": "A", "name": "A股"}, {"symbol": "B", "name": "B股"}]}',
        encoding="utf-8",
    )
    with _init_minimal_db(db_path) as con:
        con.execute(
            """
            INSERT INTO positions(symbol, name, market, quantity, avg_cost, opened_at, stop_loss, take_profit, status)
            VALUES ('A', 'A股', 'CN', 100, 10, '2026-06-01', 9, 12, 'open')
            """
        )
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('B', '2026-07-03', 1, 1, 1, 1, 1)"
        )

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=universe_path)

    assert panel["position_health"]["items"][0]["current_price"] is None
    assert "missing:price" in panel["position_health"]["items"][0]["missing"]
    assert panel["risk_warnings"]["missing_symbols"] == ["A", "B"]
