import json
import sqlite3

from backend.tools.m60_thesis_conditions import compile_condition, evaluate_condition_spec, historical_condition_backscan


def test_event_condition_extracts_conservative_keywords_and_reads_news():
    spec = compile_condition("公司层面订单、产能利用率、收入或毛利率体现 AI PCB/CCL 增量落地。", condition_type="validation")

    assert spec["kind"] == "event_keyword"
    assert spec["params"]["tables"] == ["announcements", "research_reports", "corporate_events", "news"]
    assert "订单" in spec["params"]["keywords"]
    assert "毛利率" in spec["params"]["keywords"]

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE news(symbol TEXT, title TEXT, published_at TEXT)")
    con.execute("INSERT INTO news VALUES ('A', 'A公司AI PCB订单增长且毛利率改善', '2026-07-05 09:00:00')")

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert result["matches"][0]["table"] == "news"


def test_financial_metric_condition_does_not_compile_as_price_move():
    spec = compile_condition("H1 财报增速滑落至 10% 以下或毛利率跌破 45% → 基本面驱动力证伪", condition_type="invalidation")

    assert spec["kind"] == "financial_metric_threshold"
    assert spec["params"]["join"] == "any"

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE financial_metrics(
            symbol TEXT,
            report_date TEXT,
            disclosure_date TEXT,
            revenue_yoy REAL,
            net_profit_yoy REAL,
            gross_margin REAL
        )
        """
    )
    con.execute("INSERT INTO financial_metrics VALUES ('A', '2026-06-30', '2026-07-05', 12, 11, 44)")

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert any(check["field"] == "gross_margin" and check["hit"] for check in result["checks"])


def test_long_term_label_condition_matches_latest_label_text():
    spec = compile_condition("长期标签继续显示规避、观望或估值偏高,且公司一手证据未补强。", condition_type="invalidation")

    assert spec["kind"] == "long_term_label_state"
    assert spec["params"]["labels"] == ["规避", "观望", "估值偏高"]

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE long_term_labels(symbol TEXT, date TEXT, label TEXT, key_findings_json TEXT)")
    con.execute("INSERT INTO long_term_labels VALUES ('A', '2026-07-05', '观望', '[]')")

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert result["hits"] == ["观望"]


def test_relative_benchmark_condition_uses_index_prices():
    spec = compile_condition("[持续验证] 此后30交易日跑赢沪深300 5pp+", condition_type="validation")

    assert spec["kind"] == "relative_benchmark_move"
    assert spec["params"]["window_days"] == 30
    assert spec["params"]["threshold_pp"] == 5

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE prices(symbol TEXT, date TEXT, close REAL)")
    con.execute("CREATE TABLE index_prices(symbol TEXT, date TEXT, close REAL)")
    con.executemany("INSERT INTO prices VALUES ('A', ?, ?)", [("2026-06-05", 100), ("2026-07-05", 115)])
    con.executemany("INSERT INTO index_prices VALUES ('000300', ?, ?)", [("2026-06-05", 100), ("2026-07-05", 105)])

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert round(result["excess_pp"], 2) == 10.0


def test_research_report_density_condition_counts_recent_reports():
    spec = compile_condition("研报密度拐点: AI PCB 覆盖提升", condition_type="validation")

    assert spec["kind"] == "research_report_density"
    assert spec["params"]["min_count"] == 2

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE research_reports(symbol TEXT, title TEXT, publish_date TEXT)")
    con.executemany(
        "INSERT INTO research_reports VALUES ('A', ?, ?)",
        [("AI PCB订单改善点评", "2026-07-01"), ("AI PCB毛利率改善跟踪", "2026-07-05")],
    )

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert result["count"] == 2


def test_overseas_indicator_condition_reads_snapshot_notes():
    spec = compile_condition("ASML backlog、AI capex 或设备需求指标回落,行业景气证据转弱。", condition_type="invalidation")

    assert spec["kind"] == "overseas_indicator_keyword"
    assert "ASML" in spec["params"]["keywords"]

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE overseas_snapshots(symbol TEXT, name TEXT, snap_date TEXT, note TEXT)")
    con.execute("INSERT INTO overseas_snapshots VALUES ('ASML', 'ASML', '2026-07-05', 'backlog 指标回落')")

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert result["matches"][0]["symbol"] == "ASML"


def test_fund_flow_ma_break_requires_outflow_and_broken_average():
    spec = compile_condition("医药生物资金流持续净流出且个股跌破20日均线(以观察哨读数为准)", condition_type="invalidation")

    assert spec["kind"] == "fund_flow_ma_break"
    assert spec["params"]["ma_window"] == 20

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE fund_flows(symbol TEXT, trade_date TEXT, main_net REAL)")
    con.execute("CREATE TABLE prices(symbol TEXT, date TEXT, close REAL)")
    con.executemany(
        "INSERT INTO fund_flows VALUES ('A', ?, ?)",
        [("2026-07-03", -1), ("2026-07-04", -2), ("2026-07-05", -3)],
    )
    con.executemany(
        "INSERT INTO prices VALUES ('A', ?, ?)",
        [(f"2026-06-{day:02d}", 100.0) for day in range(16, 31)] + [(f"2026-07-{day:02d}", 100.0) for day in range(1, 5)] + [("2026-07-05", 90.0)],
    )

    result = evaluate_condition_spec(con, symbol="A", as_of="2026-07-05", spec=spec)

    assert result["triggered"] is True
    assert result["latest_close"] < result["ma_value"]


def test_historical_backscan_matches_single_day_evaluator_for_price_spec():
    spec = {"kind": "price_pct_move", "params": {"threshold_pct": 5, "direction": "up"}, "raw_text": "涨幅5%"}
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE prices(symbol TEXT, date TEXT, close REAL)")
    con.execute(
        """
        CREATE TABLE forward_theses(
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            statement TEXT,
            status TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE thesis_condition_specs(
            id INTEGER PRIMARY KEY,
            forward_thesis_id INTEGER,
            condition_type TEXT,
            spec_json TEXT,
            compiled_by TEXT,
            created_at TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO prices VALUES ('A', ?, ?)",
        [("2026-01-01", 100.0), ("2026-01-02", 106.0), ("2026-01-03", 105.0)],
    )
    con.execute("INSERT INTO forward_theses VALUES (1, NULL, '[theme:unit] test', 'active')")
    con.execute(
        "INSERT INTO thesis_condition_specs VALUES (1, 1, 'validation', ?, 'rule', '2026-07-05')",
        (json.dumps(spec),),
    )

    batch = historical_condition_backscan(
        con,
        symbols_by_theme={"unit": ["A"]},
        start="2026-01-01",
        end="2026-01-03",
        condition_type="validation",
    )
    daily_hits = []
    for as_of in ("2026-01-01", "2026-01-02", "2026-01-03"):
        result = evaluate_condition_spec(con, symbol="A", as_of=as_of, spec=spec)
        if result["triggered"]:
            daily_hits.append(as_of)

    assert [hit["as_of"] for hit in batch["hits"]] == daily_hits == ["2026-01-02"]
    assert batch["stats"]["evaluated_points"] == 3
