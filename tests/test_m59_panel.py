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
        CREATE TABLE stock_memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            memory_type TEXT,
            summary TEXT NOT NULL,
            evidence_json TEXT,
            source_type TEXT,
            source_ref TEXT,
            importance INTEGER DEFAULT 3,
            confidence REAL DEFAULT 0.5,
            status TEXT DEFAULT 'active',
            ttl_days INTEGER,
            created_at DATETIME,
            updated_at DATETIME,
            last_used_at DATETIME
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

    # M59.1 plain-language summary: top-level JSON field + markdown header line.
    assert "summary" in panel
    assert panel["summary"]["candidates_count"] == 1
    assert panel["summary"]["position_count"] == 0
    assert panel["summary"]["near_stop_loss_count"] == 0
    assert "今日候选1只" in panel["summary"]["text"]
    markdown = render_markdown(panel)
    assert markdown.splitlines()[0] == panel["summary"]["text"]


def test_m59_panel_empty_database_does_not_crash(tmp_path):
    from backend.tools.m59_panel import build_panel

    db_path = tmp_path / "empty.sqlite"
    sqlite3.connect(db_path).close()

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=tmp_path / "missing.json")

    assert panel["header"]["as_of"] == "2026-07-03"
    assert panel["buy_candidates"]["items"] == []
    assert panel["position_health"]["items"] == []
    assert panel["risk_warnings"]["momentum_tail"]["items"] == []
    assert panel["risk_warnings"]["concentration"]["items"] == []
    assert panel["risk_warnings"]["concentration"]["flags"] == ["no_open_positions"]
    assert panel["risk_warnings"]["stop_loss_buffer_ranking"]["items"] == []
    assert panel["review_attribution"]["items"] == []
    assert "missing:table:signals" in panel["buy_candidates"]["flags"]
    assert "missing:table:prices" in panel["header"]["freshness"]["prices"]["status"]
    assert panel["header"]["market_reference"]["status"] == "missing:no_theme_level_record"
    assert panel["summary"] == {
        "candidates_count": 0,
        "position_count": 0,
        "near_stop_loss_count": 0,
        "near_stop_loss_symbols": [],
        "risk_warning_count": 0,
        "text": "今日候选0只/持仓0只其中0只贴近止损/风险提示0条",
    }


def test_m59_panel_summary_counts_positions_near_stop_loss(tmp_path):
    from backend.tools.m59_panel import build_panel

    db_path = tmp_path / "near-stop.sqlite"
    with _init_minimal_db(db_path) as con:
        con.execute(
            """
            INSERT INTO positions(symbol, name, market, quantity, avg_cost, opened_at, stop_loss, take_profit, status)
            VALUES ('300308', '中际旭创', 'CN', 100, 100, '2026-06-01', 98, 130, 'open')
            """
        )
        # current price 100 vs stop_loss 98 -> distance_to_stop_loss_pct == 2.0, within 5% proximity band.
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('300308', '2026-07-03', 100, 100, 100, 100, 1000)"
        )

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=tmp_path / "missing.json")

    assert panel["position_health"]["items"][0]["distance_to_stop_loss_pct"] == 2.0
    assert panel["summary"]["position_count"] == 1
    assert panel["summary"]["near_stop_loss_count"] == 1
    assert panel["summary"]["near_stop_loss_symbols"] == ["300308"]
    assert "持仓1只其中1只贴近止损" in panel["summary"]["text"]


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

    risk = panel["risk_warnings"]
    assert risk["section_name"] == "风险工程区"
    warnings = risk["momentum_tail"]["items"]
    assert [item["symbol"] for item in warnings] == ["B"]
    assert warnings[0]["warning_note"] == "预警≠卖出指令"
    assert warnings[0]["in_position"] is True
    assert warnings[0]["momentum_score"] == -0.05

    # Regime downgrade: the momentum tail must self-report whether it applies today.
    assert risk["market_regime"]["value"] in {"up", "down", "flat", "unknown"}
    assert "pool_equal_weight_ma" in risk["market_regime"]["method"]
    assert risk["momentum_tail"]["regime_reliable"] in {True, False, None}
    assert "下行市失效" in risk["momentum_tail"]["note"]

    # Concentration: the single open position (B) is 100% of exposure (test1/test2 单点教训).
    concentration = risk["concentration"]
    assert concentration["position_count"] == 1
    assert concentration["max_position_symbol"] == "B"
    assert concentration["max_position_weight_pct"] == 100.0
    assert concentration["top3_weight_pct"] == 100.0

    # Stop-loss buffer ranking: B has no stop_loss on this position, so it is explicitly missing.
    buffer_ranking = risk["stop_loss_buffer_ranking"]
    assert buffer_ranking["items"] == []
    assert buffer_ranking["missing_symbols"] == ["B"]


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

    position_item = panel["position_health"]["items"][0]
    assert position_item["current_price"] is None
    assert "missing:price" in position_item["missing"]
    assert panel["risk_warnings"]["momentum_tail"]["missing_symbols"] == ["A", "B"]

    # Research reference block: explicit "missing" statuses, never silently defaulted, never scored.
    research_reference = position_item["research_reference"]
    assert research_reference["long_term_label"]["status"] == "missing:no_valid_label"
    assert research_reference["research_pointer"]["status"] == "missing:no_research_pointer"

    # Position A has no price, so concentration falls back to avg_cost and flags the fallback.
    concentration = panel["risk_warnings"]["concentration"]
    assert concentration["max_position_symbol"] == "A"
    assert concentration["max_position_weight_pct"] == 100.0
    assert "used_avg_cost_fallback:A" in concentration["flags"]

    # No current price means no stop-loss distance either; buffer ranking marks it missing.
    buffer_ranking = panel["risk_warnings"]["stop_loss_buffer_ranking"]
    assert buffer_ranking["items"] == []
    assert buffer_ranking["missing_symbols"] == ["A"]


def test_m59_panel_research_reference_ok_path_never_scored(tmp_path):
    """Deep-research/long-term labels attach as reference-only display fields.

    Owner 2026-07-03 ruling: research surfaces as LLM-discretion context, never
    feeds scoring (soft linkage, not ATLAS-style hard linkage). This asserts the
    _reference blocks populate correctly and that no scoring field consumes them.
    """
    from backend.tools.m59_panel import build_panel

    db_path = tmp_path / "research_ref.sqlite"
    with _init_minimal_db(db_path) as con:
        con.execute("INSERT INTO stocks(symbol, name, market, active) VALUES ('300308', '中际旭创', 'CN', 1)")
        con.execute(
            """
            INSERT INTO signals(symbol, date, composite_score, recommendation, confidence, stop_loss, take_profit)
            VALUES ('300308', '2026-07-03', 72.5, '买入', '高', 100, 130)
            """
        )
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES ('300308', '2026-07-03', 110, 112, 108, 111, 1000)"
        )
        con.execute(
            """
            INSERT INTO long_term_labels(symbol, date, label, score, expires_at, quality, created_at)
            VALUES ('300308', '2026-07-01', '光通信瓶颈层', 0.8, '2026-12-31', 'high', '2026-07-01')
            """
        )
        con.execute(
            """
            INSERT INTO stock_memory_items(symbol, memory_type, summary, created_at, updated_at)
            VALUES ('300308', 'research_pointer', 'CPO 供应链瓶颈研究要点', '2026-07-02', '2026-07-02')
            """
        )
        con.execute(
            """
            INSERT INTO stock_memory_items(symbol, memory_type, summary, created_at, updated_at)
            VALUES (NULL, 'thesis', '光通信主题深研:CPO 渗透率跟踪', '2026-07-02', '2026-07-02')
            """
        )

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=tmp_path / "missing.json")

    candidate = panel["buy_candidates"]["items"][0]
    reference = candidate["research_reference"]
    assert reference["long_term_label"] == {
        "label": "光通信瓶颈层",
        "quality": "high",
        "expires_at": "2026-12-31",
        "status": "ok",
    }
    assert reference["research_pointer"]["status"] == "ok"
    assert reference["research_pointer"]["summary"] == "CPO 供应链瓶颈研究要点"

    market_reference = panel["header"]["market_reference"]
    assert market_reference["status"] == "ok"
    assert market_reference["title"] == "光通信主题深研:CPO 渗透率跟踪"
    assert market_reference["source_table"] == "stock_memory_items"

    # Reference-only: none of these fields feed composite_score or recommendation.
    assert candidate["composite_score"] == 72.5
    assert candidate["recommendation"] == "买入"
