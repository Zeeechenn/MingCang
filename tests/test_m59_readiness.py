from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta


def _init_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE prices(symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);
        CREATE TABLE stocks(symbol TEXT PRIMARY KEY, name TEXT, market TEXT, active BOOLEAN);
        CREATE TABLE signals(symbol TEXT, date TEXT, composite_score REAL, recommendation TEXT, stop_loss REAL, take_profit REAL);
        CREATE TABLE long_term_labels(symbol TEXT, date TEXT, label TEXT, score REAL, expires_at TEXT, quality TEXT);
        CREATE TABLE research_states(symbol TEXT, copilot_json TEXT);
        CREATE TABLE forward_theses(symbol TEXT, statement TEXT, status TEXT, updated_at TEXT);
        CREATE TABLE m60_watchtower_trigger_history(date TEXT, target TEXT, trigger_type TEXT);
        """
    )
    return con


def _price_rows(con, symbol="A", start="2026-06-10", n=24):
    base = datetime.fromisoformat(start)
    for idx in range(n):
        close = 100.0 + idx
        day = (base + timedelta(days=idx)).date().isoformat()
        con.execute(
            "INSERT INTO prices(symbol, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, day, close, close + 2, close - 2, close, 1000 + idx),
        )


def test_readiness_scores_dimensions_vetoes_and_missing(tmp_path):
    from backend.tools.m59_readiness import build_readiness

    db_path = tmp_path / "readiness.sqlite"
    with _init_db(db_path) as con:
        _price_rows(con)
        con.execute("INSERT INTO long_term_labels VALUES ('A', '2026-07-01', '值得持有', 0.8, '2026-12-31', 'trusted')")
        con.execute(
            "INSERT INTO research_states VALUES ('A', ?)",
            (json.dumps({"stance": "支持", "summary_opinion": "证据支持"}, ensure_ascii=False),),
        )
        con.execute("INSERT INTO forward_theses VALUES ('A', '单股论点', 'active', '2026-07-01')")
        con.execute("INSERT INTO m60_watchtower_trigger_history VALUES ('2026-07-02', 'A', 'thesis_validation')")
        entry_card = {"status": "ok", "atr14": 2.0}

        report = build_readiness(
            con,
            symbol="A",
            as_of="2026-07-03",
            entry_card=entry_card,
            piotroski={"available": True, "score": 6, "score_denominator": 9},
            market_regime={"value": "up"},
            calibration_path=tmp_path / "missing_calibration.json",
        )

    assert report["score"] == 100
    assert report["dims"] == {"research": 35, "thesis": 30, "environment": 15, "execution": 20}
    assert report["band"]["label"] == "高准备度"
    assert report["band"]["calibration_status"] == "not_loaded"
    assert any("长期标签" in item for item in report["evidence"])
    assert report["missing"] == []
    assert report["vetoes"] == []


def test_readiness_long_term_and_thesis_veto_zero_dimensions(tmp_path):
    from backend.tools.m59_readiness import build_readiness

    db_path = tmp_path / "veto.sqlite"
    with _init_db(db_path) as con:
        _price_rows(con)
        con.execute("INSERT INTO long_term_labels VALUES ('A', '2026-07-01', '规避', 0.1, '2026-12-31', 'trusted')")
        con.execute("INSERT INTO forward_theses VALUES ('A', '单股论点', 'active', '2026-07-01')")
        con.execute("INSERT INTO m60_watchtower_trigger_history VALUES ('2026-07-02', 'A', 'thesis_invalidation')")

        report = build_readiness(
            con,
            symbol="A",
            as_of="2026-07-03",
            entry_card={"status": "missing_data", "missing": ["atr14"]},
            piotroski={"available": False},
            market_regime={"value": "down"},
            calibration_path=tmp_path / "missing_calibration.json",
        )

    assert report["dims"]["research"] == 0
    assert report["dims"]["thesis"] == 0
    assert report["score"] == 8
    assert report["vetoes"][:2] == ["长期标签否决", "论点证伪警报"]
    assert "copilot" in report["missing"]
    assert "ATR风险预算" in report["missing"]


def test_calibration_gate_failures_drive_rendering(tmp_path, monkeypatch):
    from backend.tools.m59_readiness import build_readiness, render_readiness_line

    failed = tmp_path / "readiness_calibration.json"
    failed.write_text(
        json.dumps({"gate_status": "fail", "gates": {"sample": {"pass": False}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.tools.m59_readiness.DEFAULT_CALIBRATION_PATH", failed)

    db_path = tmp_path / "failed.sqlite"
    with _init_db(db_path) as con:
        report = build_readiness(con, symbol="A", as_of="2026-07-03", market_regime={"value": "flat"})

    line = render_readiness_line(report)
    assert "校准:未通过,仅清单" in line
    assert "历史频率" not in line

    passed = tmp_path / "readiness_calibration_pass.json"
    passed.write_text(
        json.dumps(
            {
                "gate_status": "pass",
                "bins": [
                    {"bin": "[50,70)", "sample_count": 40, "win_rate": 0.625},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.tools.m59_readiness.DEFAULT_CALIBRATION_PATH", passed)
    report = {**report, "score": 62, "band": {"range": "50-70", "label": "加强关注", "calibration_status": "pass"}}
    line = render_readiness_line(report)
    assert "历史频率:该分段40笔胜率62.5%" in line


def test_panel_wires_readiness_json_and_strict_render(tmp_path):
    from backend.tools.m59_panel import build_panel, render_markdown
    from backend.tools.m63_render import assert_no_trade_words

    db_path = tmp_path / "panel.sqlite"
    with _init_db(db_path) as con:
        con.execute("INSERT INTO stocks VALUES ('A', 'A股', 'CN', 1)")
        con.execute("INSERT INTO signals VALUES ('A', '2026-07-03', 72, '买入', 90, 130)")
        _price_rows(con, n=15)

    panel = build_panel(db_path=db_path, as_of="2026-07-03", universe_path=tmp_path / "missing.json")
    candidate = panel["buy_candidates"]["items"][0]

    assert candidate["entry_readiness"]["score"] >= 0
    assert "dims" in candidate["entry_readiness"]
    markdown = render_markdown(panel)
    assert "入场准备度" in markdown
    assert_no_trade_words(markdown)


def _calibration_report(counts, rates):
    return {
        "bins": [
            {"bin": f"b{idx}", "sample_count": count, "win_rate": rate}
            for idx, (count, rate) in enumerate(zip(counts, rates, strict=True))
        ]
    }


def test_calibration_gates_report_monotonic_failure():
    from backend.tools.m59_readiness import evaluate_calibration_gates

    gates = evaluate_calibration_gates(
        [
            _calibration_report([35, 35, 35], [0.6, 0.5, 0.7]),
            _calibration_report([35, 35, 35], [0.61, 0.51, 0.71]),
        ]
    )

    assert gates["monotonic"]["pass"] is False
    assert gates["sample"]["pass"] is True
    assert gates["cross_period"]["pass"] is True


def test_calibration_gates_report_sample_failure():
    from backend.tools.m59_readiness import evaluate_calibration_gates

    gates = evaluate_calibration_gates(
        [
            _calibration_report([29, 35, 35], [0.4, 0.5, 0.6]),
            _calibration_report([35, 35, 35], [0.41, 0.51, 0.61]),
        ]
    )

    assert gates["monotonic"]["pass"] is True
    assert gates["sample"]["pass"] is False
    assert gates["cross_period"]["pass"] is True


def test_calibration_gates_report_cross_period_failure():
    from backend.tools.m59_readiness import evaluate_calibration_gates

    gates = evaluate_calibration_gates(
        [
            _calibration_report([35, 35, 35], [0.4, 0.5, 0.6]),
            _calibration_report([35, 35, 35], [0.6, 0.7, 0.8]),
        ]
    )

    assert gates["monotonic"]["pass"] is True
    assert gates["sample"]["pass"] is True
    assert gates["cross_period"]["pass"] is False
