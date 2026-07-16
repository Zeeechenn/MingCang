from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _init_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE prices (id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, close REAL);
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                data_timestamp TEXT,
                composite_score REAL
            );
            """
        )


def test_build_live_subset_selects_threshold_candidates_and_json_holdings(tmp_path: Path) -> None:
    from live_trading.live_funnel import build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.executemany(
            "INSERT INTO prices(symbol, date, close) VALUES (?, '2026-07-14', 10)",
            [("600001",), ("600002",), ("600003",)],
        )
        con.executemany(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES (?, '2026-07-14', '2026-07-14', ?)",
            [("600001", 30.0), ("600002", 10.0), ("600003", 5.0)],
        )

    live_universe = tmp_path / "live_universe.json"
    _write_json(
        live_universe,
        {
            "version": "test",
            "source": "fixture",
            "stocks": [
                {"symbol": "600001", "name": "候选", "sector": "A", "origin": "live"},
                {"symbol": "600002", "name": "普通", "sector": "B", "origin": "live"},
                {"symbol": "600003", "name": "持仓", "sector": "C", "origin": "live"},
            ],
        },
    )
    test2_universe = tmp_path / "test2_universe.json"
    _write_json(test2_universe, {"version": "test", "source": "fixture", "stocks": []})
    state = tmp_path / "live_state.json"
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": 100_000,
            "positions": [{"symbol": "600003", "market_value": 20_000}],
        },
    )
    output = tmp_path / "subset.json"

    result = build_live_subset(
        db_path=db_path,
        live_universe_path=live_universe,
        test2_universe_path=test2_universe,
        state_path=state,
        trade_date="2026-07-14",
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [stock["symbol"] for stock in payload["stocks"]] == ["600001", "600003"]
    assert result["holding_symbols"] == ["600003"]
    assert result["total_exposure"] == 0.2


def test_live_and_test2_overlap_fails_closed_before_output(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    stock = {"symbol": "600001", "name": "重叠", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": [stock]})
    _write_json(
        state,
        {"version": 1, "as_of": "2026-07-14", "portfolio_value": 100_000, "positions": []},
    )

    with pytest.raises(SafetyViolation, match="test2.*600001"):
        build_live_subset(
            db_path=tmp_path / "must-not-be-opened.sqlite",
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


def test_holding_without_trade_date_bar_fails_closed(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, close) VALUES ('600001', '2026-07-11', 10)"
        )
        con.execute(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES ('600001', '2026-07-14', '2026-07-14', 30)"
        )
    stock = {"symbol": "600001", "name": "持仓", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": 100_000,
            "positions": [{"symbol": "600001", "market_value": 20_000}],
        },
    )

    with pytest.raises(SafetyViolation, match="holding.*bar.*600001"):
        build_live_subset(
            db_path=db_path,
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


def test_holding_without_trade_date_signal_fails_closed(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, close) VALUES ('600001', '2026-07-14', 10)"
        )
        con.execute(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES ('600001', '2026-07-14', '2026-07-14', NULL)"
        )
    stock = {"symbol": "600001", "name": "持仓", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": 100_000,
            "positions": [{"symbol": "600001", "market_value": 20_000}],
        },
    )

    with pytest.raises(SafetyViolation, match="holding.*signal.*600001"):
        build_live_subset(
            db_path=db_path,
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


def test_total_exposure_above_eighty_percent_fails_closed(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    stock = {"symbol": "600001", "name": "持仓", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": 100_000,
            "positions": [{"symbol": "600001", "market_value": 81_000}],
        },
    )

    with pytest.raises(SafetyViolation, match="total exposure.*81.00%.*80.00%"):
        build_live_subset(
            db_path=tmp_path / "must-not-be-opened.sqlite",
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


def test_stale_non_holding_is_excluded_with_warning(tmp_path: Path) -> None:
    from live_trading.live_funnel import build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.executemany(
            "INSERT INTO prices(symbol, date, close) VALUES (?, ?, 10)",
            [
                ("600001", "2026-07-11"),
                ("600002", "2026-07-14"),
                ("600003", "2026-07-14"),
            ],
        )
        con.executemany(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES (?, '2026-07-14', '2026-07-14', ?)",
            [("600001", 40.0), ("600002", 5.0)],
        )
    stocks = [
        {"symbol": "600001", "name": "陈旧候选", "sector": "A", "origin": "fixture"},
        {"symbol": "600002", "name": "持仓", "sector": "B", "origin": "fixture"},
        {"symbol": "600003", "name": "缺信号候选", "sector": "C", "origin": "fixture"},
    ]
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": stocks})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": 100_000,
            "positions": [{"symbol": "600002", "market_value": 20_000}],
        },
    )

    result = build_live_subset(
        db_path=db_path,
        live_universe_path=live_universe,
        test2_universe_path=test2_universe,
        state_path=state,
        trade_date="2026-07-14",
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [stock["symbol"] for stock in payload["stocks"]] == ["600002"]
    assert result["excluded_symbols"] == ["600001", "600003"]
    assert result["warnings"] == [
        "non-holding 600001 missing trade-date bar; excluded",
        "non-holding 600003 missing trade-date signal; excluded",
    ]


def test_cli_requires_explicit_output_path() -> None:
    from live_trading.live_funnel import main

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--trade-date",
                "2026-07-14",
                "--db",
                "source.sqlite",
                "--live-universe",
                "live.json",
                "--test2-universe",
                "test2.json",
                "--state",
                "state.json",
            ]
        )

    assert exc_info.value.code == 2


def test_cli_rejects_attempt_to_relax_eighty_percent_limit() -> None:
    from live_trading.live_funnel import main

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--trade-date",
                "2026-07-14",
                "--db",
                "source.sqlite",
                "--live-universe",
                "live.json",
                "--test2-universe",
                "test2.json",
                "--state",
                "state.json",
                "--output",
                "subset.json",
                "--max-total-exposure",
                "0.9",
            ]
        )

    assert exc_info.value.code == 2


def test_state_snapshot_date_must_match_trade_date(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": []})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {"version": 1, "as_of": "2026-07-11", "portfolio_value": 100_000, "positions": []},
    )

    with pytest.raises(SafetyViolation, match="state as_of.*2026-07-11.*2026-07-14"):
        build_live_subset(
            db_path=tmp_path / "must-not-be-opened.sqlite",
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


def test_holding_outside_live_universe_fails_closed(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": []})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": 100_000,
            "positions": [{"symbol": "600001", "market_value": 20_000}],
        },
    )

    with pytest.raises(SafetyViolation, match="holding outside live universe.*600001"):
        build_live_subset(
            db_path=tmp_path / "must-not-be-opened.sqlite",
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("portfolio_value", "market_value", "message"),
    [(0, 0, "portfolio_value must be positive"), (100_000, -1, "market_value must be non-negative")],
)
def test_invalid_money_state_fails_closed(
    tmp_path: Path, portfolio_value: int, market_value: int, message: str
) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    stock = {"symbol": "600001", "name": "持仓", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {
            "version": 1,
            "as_of": "2026-07-14",
            "portfolio_value": portfolio_value,
            "positions": [{"symbol": "600001", "market_value": market_value}],
        },
    )

    with pytest.raises(SafetyViolation, match=message):
        build_live_subset(
            db_path=tmp_path / "must-not-be-opened.sqlite",
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=output,
        )

    assert not output.exists()


def test_output_must_not_overwrite_an_input(tmp_path: Path) -> None:
    from live_trading.live_funnel import SafetyViolation, build_live_subset

    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    original_state = {
        "version": 1,
        "as_of": "2026-07-14",
        "portfolio_value": 100_000,
        "positions": [],
    }
    _write_json(live_universe, {"version": "test", "stocks": []})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(state, original_state)

    with pytest.raises(SafetyViolation, match="output path must differ from every input"):
        build_live_subset(
            db_path=tmp_path / "must-not-be-opened.sqlite",
            live_universe_path=live_universe,
            test2_universe_path=test2_universe,
            state_path=state,
            trade_date="2026-07-14",
            output_path=state,
        )

    assert json.loads(state.read_text(encoding="utf-8")) == original_state


def test_latest_same_day_signal_is_used(tmp_path: Path) -> None:
    from live_trading.live_funnel import build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, close) VALUES ('600001', '2026-07-14', 10)"
        )
        con.executemany(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES ('600001', '2026-07-14', '2026-07-14', ?)",
            [(40.0,), (10.0,)],
        )
        con.execute("CREATE INDEX idx_signals_date_id_desc ON signals(date, id DESC)")
    stock = {"symbol": "600001", "name": "候选", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {"version": 1, "as_of": "2026-07-14", "portfolio_value": 100_000, "positions": []},
    )

    build_live_subset(
        db_path=db_path,
        live_universe_path=live_universe,
        test2_universe_path=test2_universe,
        state_path=state,
        trade_date="2026-07-14",
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["stocks"] == []


def test_timestamp_batch_signal_is_consumed(tmp_path: Path) -> None:
    """test2/live 批次 Signal.date 形如 '2026-07-14T16:25+08:00'（非纯日期）；
    只要 data_timestamp 等于当日交易日，就应正常被漏斗消费。"""
    from live_trading.live_funnel import build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, close) VALUES ('600001', '2026-07-14', 10)"
        )
        con.execute(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES ('600001', '2026-07-14T16:25+08:00', '2026-07-14', 40.0)"
        )
    stock = {"symbol": "600001", "name": "候选", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {"version": 1, "as_of": "2026-07-14", "portfolio_value": 100_000, "positions": []},
    )

    build_live_subset(
        db_path=db_path,
        live_universe_path=live_universe,
        test2_universe_path=test2_universe,
        state_path=state,
        trade_date="2026-07-14",
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [stock["symbol"] for stock in payload["stocks"]] == ["600001"]


def test_stale_data_timestamp_signal_is_excluded_even_if_signal_day_matches(tmp_path: Path) -> None:
    """信号日前缀等于交易日，但 data_timestamp 是前一日（429/代理故障回退旧bar）——
    必须 fail-closed 排除，而不是被当作当日新鲜信号消费。"""
    from live_trading.live_funnel import build_live_subset

    db_path = tmp_path / "source.sqlite"
    _init_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO prices(symbol, date, close) VALUES ('600001', '2026-07-14', 10)"
        )
        con.execute(
            "INSERT INTO signals(symbol, date, data_timestamp, composite_score) "
            "VALUES ('600001', '2026-07-14T09:05+08:00', '2026-07-11', 40.0)"
        )
    stock = {"symbol": "600001", "name": "候选", "sector": "A", "origin": "fixture"}
    live_universe = tmp_path / "live_universe.json"
    test2_universe = tmp_path / "test2_universe.json"
    state = tmp_path / "live_state.json"
    output = tmp_path / "subset.json"
    _write_json(live_universe, {"version": "test", "stocks": [stock]})
    _write_json(test2_universe, {"version": "test", "stocks": []})
    _write_json(
        state,
        {"version": 1, "as_of": "2026-07-14", "portfolio_value": 100_000, "positions": []},
    )

    result = build_live_subset(
        db_path=db_path,
        live_universe_path=live_universe,
        test2_universe_path=test2_universe,
        state_path=state,
        trade_date="2026-07-14",
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["stocks"] == []
    assert result["excluded_symbols"] == ["600001"]
    assert result["warnings"] == ["non-holding 600001 missing trade-date signal; excluded"]
