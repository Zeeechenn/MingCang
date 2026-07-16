"""B: 信号 runner fail-closed + AB 回放终版消费——07-16 雅克科技旧 bar 事故根治的回归测试。

覆盖两块：
1. paper_trading.test2_ab_data.load_signals 的终版消费（FINAL_VERSION_CUTOFF）：
   CUTOFF 前同日多行全保留、CUTOFF 起同一 (symbol, day) 只留终版、纯日期行不受影响。
2. paper_trading.test2_signal_runner._refresh_prices_if_needed 的共识基准日 + 陈旧
   收口：consensus = max(池内max, expected_trade_date(db)[0])，helper 异常时回落池内 max。

runner 的 run() 里 fail-closed 剔除逻辑（拿到陈旧列表后从 stocks 剔除、stats
新增 stale_skipped）耦合 backend.scheduler 的分析/落库全链路，接线成本高，本文件
不覆盖；已在 _refresh_prices_if_needed 层面测过它产出的陈旧列表本身正确。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# paper_trading/ 是 gitignored 的本地测试材料，CI checkout 里不存在——照
# test_atlas_test4_stage2b_shadow.py 的惯例整模块跳过。
test2_ab_data = pytest.importorskip(
    "paper_trading.test2_ab_data",
    reason="paper_trading/test2 replay helpers are local-only and not checked into CI",
)
FINAL_VERSION_CUTOFF = test2_ab_data.FINAL_VERSION_CUTOFF
load_signals = test2_ab_data.load_signals

SIGNALS_SCHEMA = """
CREATE TABLE signals (
    id INTEGER NOT NULL,
    symbol VARCHAR,
    date VARCHAR,
    quant_score FLOAT,
    technical_score FLOAT,
    sentiment_score FLOAT,
    composite_score FLOAT,
    recommendation VARCHAR,
    confidence VARCHAR,
    stop_loss FLOAT,
    take_profit FLOAT,
    limit_status VARCHAR,
    llm_rationale TEXT,
    created_at DATETIME,
    rule_version TEXT,
    data_timestamp TEXT,
    asset_key TEXT,
    market TEXT DEFAULT 'CN',
    signal_scope TEXT DEFAULT 'production',
    PRIMARY KEY (id)
);
"""


def _make_db(tmp_path: Path, rows: list[tuple]) -> Path:
    """rows: (id, symbol, date, quant, tech, sent, sl, tp)"""
    db_path = tmp_path / "signals_test.db"
    con = sqlite3.connect(db_path)
    con.execute(SIGNALS_SCHEMA)
    con.executemany(
        "INSERT INTO signals (id, symbol, date, quant_score, technical_score, "
        "sentiment_score, stop_loss, take_profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()
    return db_path


UNIVERSE = {"AAA": "Alpha", "BBB": "Beta"}


def test_cutoff_constant_matches_spec():
    assert FINAL_VERSION_CUTOFF == "2026-07-16"


def test_pre_cutoff_same_day_multi_rows_all_kept(tmp_path):
    # CUTOFF 之前（07-14）同日两批信号——历史冻结，全部保留，不做终版折叠。
    rows = [
        (1, "AAA", "2026-07-14T00:17+08:00", 10.0, 10.0, 0.0, 9.0, 12.0),
        (2, "AAA", "2026-07-14T15:47+08:00", 20.0, 20.0, 0.0, 9.0, 12.0),
    ]
    db_path = _make_db(tmp_path, rows)

    signals = load_signals(db_path, UNIVERSE, start="2026-07-01", end="2026-07-20")

    assert [s.date for s in signals] == [
        "2026-07-14T00:17+08:00",
        "2026-07-14T15:47+08:00",
    ]


def test_post_cutoff_same_day_multi_rows_keep_final_version_only(tmp_path):
    # 07-16 实证：午夜陈旧批(id=1) + 15:47 陈旧批(id=2) + 15:52 补救批(id=3) 同日共存，
    # 回放只应消费 id 最大（终版）的一行。
    rows = [
        (1, "AAA", "2026-07-16T00:17+08:00", 1.0, 1.0, 0.0, 9.0, 12.0),
        (2, "AAA", "2026-07-16T15:47+08:00", 2.0, 2.0, 0.0, 9.0, 12.0),
        (3, "AAA", "2026-07-16T15:52+08:00", 3.0, 3.0, 0.0, 9.0, 12.0),
    ]
    db_path = _make_db(tmp_path, rows)

    signals = load_signals(db_path, UNIVERSE, start="2026-07-01", end="2026-07-20")

    assert len(signals) == 1
    assert signals[0].date == "2026-07-16T15:52+08:00"
    assert signals[0].quant == 3.0


def test_post_cutoff_ties_on_date_break_by_id(tmp_path):
    # 同一时间戳但不同 id（理论上不该发生，但唯一索引是 (asset_key, date)，用 id 兜底）。
    rows = [
        (5, "AAA", "2026-07-16T15:47+08:00", 5.0, 5.0, 0.0, 9.0, 12.0),
        (4, "AAA", "2026-07-16T15:47+08:00", 4.0, 4.0, 0.0, 9.0, 12.0),
    ]
    db_path = _make_db(tmp_path, rows)

    signals = load_signals(db_path, UNIVERSE, start="2026-07-01", end="2026-07-20")

    assert len(signals) == 1
    assert signals[0].quant == 5.0  # id=5 > id=4，终版取更大 id


def test_post_cutoff_groups_independent_per_symbol_and_day(tmp_path):
    rows = [
        (1, "AAA", "2026-07-16T09:30+08:00", 1.0, 0.0, 0.0, 9.0, 12.0),
        (2, "AAA", "2026-07-16T15:47+08:00", 2.0, 0.0, 0.0, 9.0, 12.0),
        (3, "BBB", "2026-07-16T15:47+08:00", 3.0, 0.0, 0.0, 18.0, 30.0),
        (4, "AAA", "2026-07-17T15:47+08:00", 40.0, 0.0, 0.0, 9.0, 12.0),
    ]
    db_path = _make_db(tmp_path, rows)

    signals = load_signals(db_path, UNIVERSE, start="2026-07-01", end="2026-07-20")

    by_key = {(s.symbol, s.date[:10]): s for s in signals}
    assert len(signals) == 3  # AAA 07-16 折叠成 1 行 + BBB 07-16 1 行 + AAA 07-17 1 行
    assert by_key[("AAA", "2026-07-16")].quant == 2.0
    assert by_key[("BBB", "2026-07-16")].quant == 3.0
    assert by_key[("AAA", "2026-07-17")].quant == 40.0


def test_plain_date_rows_unaffected_by_cutoff_logic(tmp_path):
    # 纯日期（无时间戳）信号行，CUTOFF 前后各一条，互不干扰、正常各自保留。
    rows = [
        (1, "AAA", "2026-07-10", 10.0, 0.0, 0.0, 9.0, 12.0),
        (2, "AAA", "2026-07-16", 20.0, 0.0, 0.0, 9.0, 12.0),
    ]
    db_path = _make_db(tmp_path, rows)

    signals = load_signals(db_path, UNIVERSE, start="2026-07-01", end="2026-07-20")

    assert [s.date for s in signals] == ["2026-07-10", "2026-07-16"]
    assert [s.quant for s in signals] == [10.0, 20.0]


def test_order_preserved_as_date_then_symbol(tmp_path):
    rows = [
        (1, "BBB", "2026-07-16T09:00+08:00", 1.0, 0.0, 0.0, None, None),
        (2, "AAA", "2026-07-16T09:00+08:00", 2.0, 0.0, 0.0, None, None),
        (3, "AAA", "2026-07-17T09:00+08:00", 3.0, 0.0, 0.0, None, None),
    ]
    db_path = _make_db(tmp_path, rows)

    signals = load_signals(db_path, UNIVERSE, start="2026-07-01", end="2026-07-20")

    assert [(s.date, s.symbol) for s in signals] == [
        ("2026-07-16T09:00+08:00", "AAA"),
        ("2026-07-16T09:00+08:00", "BBB"),
        ("2026-07-17T09:00+08:00", "AAA"),
    ]


# ---------------------------------------------------------------------------
# runner: _refresh_prices_if_needed 的共识基准日 + fail-closed 陈旧列表
# ---------------------------------------------------------------------------


@pytest.fixture
def price_db(test_db):
    """写入两支股票的最新 bar 日，供共识基准日计算使用。"""
    from backend.data.database import Price

    test_db.add_all(
        [
            Price(symbol="AAA", market="CN", date="2026-07-14", open=1, high=1, low=1, close=1, volume=1),
            Price(symbol="BBB", market="CN", date="2026-07-15", open=1, high=1, low=1, close=1, volume=1),
        ]
    )
    test_db.commit()
    return test_db


def test_refresh_prices_uses_expected_trade_date_as_consensus_floor(price_db, monkeypatch):
    """池内 max=07-15，但 expected_trade_date 探到 07-16——两支都应判陈旧（全池统一
    陈旧场景的原始 bug：只看池内 max 会把 07-15 误判成新鲜基准）。"""
    import backend.data.freshness as freshness_mod
    import backend.data.market as market_mod
    from paper_trading import test2_signal_runner as runner

    monkeypatch.setattr(market_mod, "backfill_if_needed", lambda *a, **k: 0)
    monkeypatch.setattr(freshness_mod, "expected_trade_date", lambda db, **k: ("2026-07-16", "probe"))
    monkeypatch.setattr(runner.time, "sleep", lambda *_a: None)

    stale = runner._refresh_prices_if_needed(price_db, {"AAA": "Alpha", "BBB": "Beta"})

    assert stale == ["AAA", "BBB"]


def test_refresh_prices_falls_back_to_pool_max_on_helper_exception(price_db, monkeypatch, capsys):
    """expected_trade_date 抛异常时回落池内 max=07-15；此时 BBB(07-15) 新鲜，AAA(07-14) 陈旧。"""
    import backend.data.market as market_mod
    from paper_trading import test2_signal_runner as runner

    def _boom(db, **kwargs):
        raise RuntimeError("probe network down")

    monkeypatch.setattr(market_mod, "backfill_if_needed", lambda *a, **k: 0)
    monkeypatch.setattr("backend.data.freshness.expected_trade_date", _boom)
    monkeypatch.setattr(runner.time, "sleep", lambda *_a: None)

    stale = runner._refresh_prices_if_needed(price_db, {"AAA": "Alpha", "BBB": "Beta"})

    assert stale == ["AAA"]
    err = capsys.readouterr().err
    assert "expected_trade_date 探测异常" in err


def test_refresh_prices_returns_empty_when_pool_fully_fresh(price_db, monkeypatch):
    """expected_trade_date 与池内 max 一致（07-15）时全池新鲜，返回空列表。"""
    import backend.data.market as market_mod
    from paper_trading import test2_signal_runner as runner

    monkeypatch.setattr(market_mod, "backfill_if_needed", lambda *a, **k: 0)
    monkeypatch.setattr("backend.data.freshness.expected_trade_date", lambda db, **k: ("2026-07-14", "anchor"))
    monkeypatch.setattr(runner.time, "sleep", lambda *_a: None)

    # 把 AAA 也刷到 07-15，让全池都在 07-15，与 consensus=max(07-15, 07-14)=07-15 一致
    from backend.data.database import Price

    price_db.add(Price(symbol="AAA", market="CN", date="2026-07-15", open=1, high=1, low=1, close=1, volume=1))
    price_db.commit()

    stale = runner._refresh_prices_if_needed(price_db, {"AAA": "Alpha", "BBB": "Beta"})

    assert stale == []
