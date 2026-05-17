"""M4.8 阈值扫描单元测试。

不调真实 LLM，用合成 SignalInput。
"""
from __future__ import annotations

from backend.backtest.compare_paths import SignalInput
from backend.backtest.sweep_threshold import sweep, _metrics, _recommend, ThresholdMetrics


def _make(score_hint: int, fwd: list[float]) -> SignalInput:
    """构造一个合成 input：score 大致由 tech_score 控制（因为 tech 权重 0.4）"""
    return SignalInput(
        symbol="TEST",
        date="2026-01-01",
        technical_result={
            "score": score_hint, "raw_score": score_hint, "adx_factor": 1.0,
            "latest": {"rsi14": 55}, "limit": {},
        },
        qlib_result={"score": score_hint, "model": "lgbm"},
        sentiment_result={"sentiment": score_hint / 100.0, "impact": "short", "key_events": []},
        close=100.0, atr=2.5,
        forward_returns=fwd,
    )


def test_metrics_empty_returns_zero():
    m = _metrics(20, [])
    assert m.trades == 0
    assert m.sharpe == 0.0


def test_metrics_basic_stats():
    """+5%, +3%, -2%, +1% → 3W 1L"""
    m = _metrics(20, [0.05, 0.03, -0.02, 0.01])
    assert m.trades == 4
    assert m.wins == 3
    assert m.losses == 1
    assert m.win_rate == 75.0
    assert m.avg_return == 1.75   # 1.75% 平均
    assert m.sharpe > 0


def test_sweep_threshold_filters_correctly():
    """阈值越高，trades 越少"""
    inputs = [
        _make(80, [0.02, 0.03, 0.04, 0.05, 0.06]),     # high score
        _make(40, [0.01, 0.01, 0.01, 0.01, 0.01]),     # mid
        _make(10, [0.00, -0.01, -0.02, -0.01, 0.00]),  # low
        _make(-50, [-0.05, -0.04, -0.03, -0.02, -0.01]),  # very low
    ]
    report = sweep(inputs, thresholds=[5, 25, 50, 75], exit_days=5)
    # 5: 应过 high+mid+low = 3
    # 25: 应过 high+mid = 2
    # 50: 应过 high = 1
    # 75: 可能过 high = 1 或 0（依赖 composite 计算）
    rows = {r["threshold"]: r for r in report["thresholds"]}
    assert rows[5]["trades"] >= rows[25]["trades"] >= rows[50]["trades"] >= rows[75]["trades"]


def test_sweep_recommends_high_sharpe():
    """所有阈值都给至少 5 trades 时，应选 Sharpe 最高"""
    rows = [
        ThresholdMetrics(threshold=10, trades=20, wins=10, losses=10, win_rate=50.0,
                         avg_return=1.0, sharpe=0.5, profit_loss=1.2,
                         total_return=20.0, max_drawdown=-15.0, expectancy=1.0),
        ThresholdMetrics(threshold=20, trades=10, wins=7, losses=3, win_rate=70.0,
                         avg_return=2.0, sharpe=2.0, profit_loss=2.5,
                         total_return=21.0, max_drawdown=-5.0, expectancy=2.0),
        ThresholdMetrics(threshold=30, trades=3, wins=2, losses=1, win_rate=66.7,
                         avg_return=3.0, sharpe=3.0, profit_loss=3.0,
                         total_return=10.0, max_drawdown=-2.0, expectancy=3.0),
    ]
    rec = _recommend(rows)
    # threshold=30 的 sharpe 最高但 trades<5，应被排除；选 20
    assert rec["threshold"] == 20


def test_sweep_recommends_none_when_all_too_few():
    rows = [
        ThresholdMetrics(threshold=20, trades=2, wins=1, losses=1, win_rate=50.0,
                         avg_return=1.0, sharpe=1.0, profit_loss=1.5,
                         total_return=2.0, max_drawdown=-1.0, expectancy=1.0),
    ]
    rec = _recommend(rows)
    assert rec["threshold"] is None
    assert "样本不足" in rec["reason"]


def test_sweep_tie_breaks_by_drawdown():
    """两档 Sharpe 相同时，选 drawdown 更小（更接近 0）的"""
    rows = [
        ThresholdMetrics(threshold=15, trades=10, wins=6, losses=4, win_rate=60.0,
                         avg_return=2.0, sharpe=1.5, profit_loss=1.5,
                         total_return=20.0, max_drawdown=-20.0, expectancy=2.0),
        ThresholdMetrics(threshold=25, trades=8, wins=5, losses=3, win_rate=62.5,
                         avg_return=2.5, sharpe=1.5, profit_loss=2.0,
                         total_return=20.0, max_drawdown=-5.0, expectancy=2.5),
    ]
    rec = _recommend(rows)
    # 都 sharpe=1.5，threshold=25 drawdown -5 < -20 → 选 25
    assert rec["threshold"] == 25


def test_sweep_report_structure():
    inputs = [_make(50, [0.01, 0.02, 0.03, 0.04, 0.05])]
    report = sweep(inputs, thresholds=[10, 20], exit_days=5)
    assert "n_inputs" in report
    assert "exit_days" in report
    assert "thresholds" in report
    assert "recommended" in report
    assert len(report["thresholds"]) == 2
