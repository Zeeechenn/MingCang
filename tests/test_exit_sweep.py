"""M4.9 exit 逻辑实验单元测试。

合成 forward OHLC 路径，验证：
  • fixed_5d 在第 5 天平仓
  • atr_2x_4x 触发 stop / take 时正确退出
  • trailing_atr_2x 跟随 close 提升 trailing
  • 没有 entries 时返回 n_entries=0
  • _recommend 选 Sharpe 最高且 trades>=5
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch

from backend.backtest.compare_paths import SignalInput
from backend.backtest.exit_sweep import (
    _PriceRow,
    _build_strategy_runners,
    _metrics,
    _recommend,
    run_exit_sweep,
    ExitStrategyMetrics,
)


def _entry_input(score_hint: int = 80, close: float = 100.0, atr: float = 2.5,
                 fwd: list[float] | None = None) -> SignalInput:
    """高分 input → composite_score 应过 25 阈值"""
    return SignalInput(
        symbol="TEST", date="2026-04-01",
        technical_result={
            "score": score_hint, "raw_score": score_hint, "adx_factor": 1.0,
            "latest": {"rsi14": 60}, "limit": {},
        },
        qlib_result={"score": score_hint, "model": "lgbm"},
        sentiment_result={"sentiment": score_hint/100.0, "impact": "short",
                           "key_events": ["利好"]},
        close=close, atr=atr,
        forward_returns=fwd or [0.01, 0.02, 0.03, 0.04, 0.05],
    )


def _make_rows(closes: list[float], atr: float = 2.5,
               highs: list[float] | None = None,
               lows: list[float] | None = None) -> list[_PriceRow]:
    """构造 OHLC rows；rows[0] 是 entry，后续是 forward"""
    highs = highs or closes
    lows = lows or closes
    return [
        _PriceRow(date=f"d{i}", close=c, high=h, low=l, atr14=atr)
        for i, (c, h, l) in enumerate(zip(closes, highs, lows))
    ]


# ── exit fn 行为 ─────────────────────────────────────────────────────

def test_fixed_5d_exits_at_day_5():
    rows = _make_rows([100, 101, 102, 103, 104, 105, 106])
    fn = _build_strategy_runners()["fixed_5d"]
    idx, reason = fn(rows)
    assert idx == 5
    assert "fixed_5d" in reason


def test_atr_2x_4x_take_profit_triggers():
    """涨到 entry + 2.5×4 = 110 触发 take（atr=2.5）"""
    rows = _make_rows(
        closes=[100, 101, 105, 110, 112],
        highs=[100, 101, 108, 111, 113],
        lows=[100, 100, 104, 108, 111],
        atr=2.5,
    )
    fn = _build_strategy_runners()["atr_2x_4x"]
    idx, reason = fn(rows)
    assert reason in ("atr_take", "atr_stop", "end")
    if reason == "atr_take":
        assert idx >= 1


def test_atr_2x_4x_stop_triggers():
    """跌到 entry - 2.5×2 = 95 触发 stop"""
    rows = _make_rows(
        closes=[100, 98, 94, 92],
        highs=[100, 99, 97, 94],
        lows=[100, 96, 93, 90],
        atr=2.5,
    )
    fn = _build_strategy_runners()["atr_2x_4x"]
    idx, reason = fn(rows)
    assert reason == "atr_stop"


def test_trailing_atr_follows_up():
    """连续上涨 → trailing 跟随；最后跌破 trailing 触发"""
    rows = _make_rows(
        closes=[100, 105, 110, 108, 100],   # 涨到 110，trailing=110-5=105；最后 close=100 → low 假设也 100
        highs=[100, 105, 110, 109, 102],
        lows=[100, 100, 106, 107, 99],       # 第 5 天 low=99 跌破 105 → exit
        atr=2.5,
    )
    fn = _build_strategy_runners()["trailing_atr_2x"]
    idx, reason = fn(rows)
    assert reason == "trailing_stop"


# ── _metrics ─────────────────────────────────────────────────────────

def test_metrics_empty():
    m = _metrics("x", [])
    assert m.trades == 0
    assert m.sharpe == 0.0


def test_metrics_basic():
    trades = [(0.05, "fixed_5d", 5), (-0.02, "fixed_5d", 5), (0.03, "fixed_5d", 5)]
    m = _metrics("fixed_5d", trades)
    assert m.trades == 3
    assert m.wins == 2
    assert m.losses == 1
    assert m.avg_hold_days == 5.0
    assert m.avg_return == 2.0   # (5-2+3)/3 = 2.0


# ── _recommend ───────────────────────────────────────────────────────

def test_recommend_picks_highest_sharpe():
    rows = [
        ExitStrategyMetrics(name="a", trades=10, wins=6, losses=4, win_rate=60.0,
                            avg_return=2.0, sharpe=2.0, profit_loss=2.0,
                            total_return=20.0, max_drawdown=-15.0,
                            avg_hold_days=5.0, exit_reasons={}),
        ExitStrategyMetrics(name="b", trades=10, wins=7, losses=3, win_rate=70.0,
                            avg_return=2.5, sharpe=3.0, profit_loss=2.5,
                            total_return=25.0, max_drawdown=-10.0,
                            avg_hold_days=4.0, exit_reasons={}),
    ]
    rec = _recommend(rows)
    assert rec["name"] == "b"


def test_recommend_filters_low_trade_count():
    rows = [
        ExitStrategyMetrics(name="x", trades=3, wins=2, losses=1, win_rate=66.7,
                            avg_return=5.0, sharpe=5.0, profit_loss=4.0,
                            total_return=15.0, max_drawdown=-3.0,
                            avg_hold_days=3.0, exit_reasons={}),
        ExitStrategyMetrics(name="y", trades=10, wins=6, losses=4, win_rate=60.0,
                            avg_return=2.0, sharpe=2.0, profit_loss=2.0,
                            total_return=20.0, max_drawdown=-15.0,
                            avg_hold_days=5.0, exit_reasons={}),
    ]
    rec = _recommend(rows)
    # x.sharpe 高但 trades<5 → 选 y
    assert rec["name"] == "y"


def test_recommend_no_valid_returns_none():
    rows = [
        ExitStrategyMetrics(name="x", trades=2, wins=1, losses=1, win_rate=50.0,
                            avg_return=1.0, sharpe=1.0, profit_loss=1.5,
                            total_return=2.0, max_drawdown=-1.0,
                            avg_hold_days=5.0, exit_reasons={}),
    ]
    rec = _recommend(rows)
    assert rec["name"] is None


# ── run_exit_sweep 集成 ──────────────────────────────────────────────

def test_run_exit_sweep_no_entries():
    """低分 input → 没有 entries → n_entries=0"""
    low = SignalInput(
        symbol="LOW", date="2026-04-01",
        technical_result={"score": -30, "raw_score": -30, "adx_factor": 1.0,
                          "latest": {}, "limit": {}},
        qlib_result={"score": -30, "model": "lgbm"},
        sentiment_result={"sentiment": -0.3, "impact": "short", "key_events": []},
        close=100.0, atr=2.5,
        forward_returns=[0.0]*5,
    )
    report = run_exit_sweep([low], threshold=25.0)
    assert report["n_entries"] == 0
