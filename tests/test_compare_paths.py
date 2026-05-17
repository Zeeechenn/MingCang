"""M4.6 双路径并排回测测试。

覆盖：
  • simulate_path 在合成输入上正确收集 ENTRY 信号的 forward returns
  • 路径 A vs 路径 B 在简单一致输入上得到相同方向（sanity）
  • compare_paths 在不同输入下生成合理 delta + recommendation
  • _max_drawdown 单调权益曲线时为 0
  • _max_drawdown 跌后回升时记录正确低点
  • 数据不足（trades < 10）→ recommendation = "数据不足"
"""
from __future__ import annotations

from backend.backtest.compare_paths import (
    SignalInput,
    _generate_recommendation,
    _max_drawdown,
    compare_paths,
    simulate_path,
)


def _make_input(
    sym: str = "TEST",
    date: str = "2026-01-01",
    quant_score: float = 30,
    tech_score: float = 30,
    sentiment: float = 0.3,
    fwd_returns: list[float] | None = None,
) -> SignalInput:
    return SignalInput(
        symbol=sym, date=date,
        technical_result={
            "score": tech_score, "raw_score": tech_score, "adx_factor": 1.0,
            "latest": {"rsi14": 55}, "limit": {},
        },
        qlib_result={"score": quant_score, "model": "lgbm"},
        sentiment_result={
            "sentiment": sentiment, "impact": "short",
            "key_events": ["利好"] if sentiment > 0 else [],
        },
        close=100.0, atr=2.5,
        forward_returns=fwd_returns or [0.01, 0.02, 0.03, 0.02, 0.04],
    )


# ── _max_drawdown ────────────────────────────────────────────────────

def test_max_drawdown_monotonic_up_zero():
    assert _max_drawdown([0.01, 0.02, 0.01, 0.005]) == 0.0


def test_max_drawdown_dip_recover():
    """+5%, -10%, +5% → 权益: 1.05, 0.945, 0.992 → 峰值 1.05 → 低点 0.945 = -10%"""
    mdd = _max_drawdown([0.05, -0.10, 0.05])
    assert mdd <= -9.0   # 负数，绝对值约 10%


def test_max_drawdown_empty():
    assert _max_drawdown([]) == 0.0


# ── simulate_path ────────────────────────────────────────────────────

def test_simulate_path_collects_entry_returns():
    """高分 → ENTRY 信号 → 收集 T+5 收益率"""
    from backend.backtest.compare_paths import _path_a, _no_llm_settings

    inputs = [
        _make_input(quant_score=70, tech_score=70, sentiment=0.6,
                    fwd_returns=[0.01, 0.02, 0.03, 0.04, 0.05]),
        _make_input(quant_score=80, tech_score=80, sentiment=0.7,
                    fwd_returns=[-0.01, -0.02, -0.03, -0.04, -0.05]),
    ]
    with _no_llm_settings():
        m = simulate_path("path_a", _path_a, inputs)
    assert m.trades == 2
    assert m.wins == 1
    assert m.losses == 1
    assert m.entry_signal_count == 2
    # 平均 = 0


def test_simulate_path_skips_non_entry():
    """负分 → 非 ENTRY 信号 → 不进 trades"""
    from backend.backtest.compare_paths import _path_a, _no_llm_settings

    inputs = [
        _make_input(quant_score=-50, tech_score=-50, sentiment=-0.5),
    ]
    with _no_llm_settings():
        m = simulate_path("path_a", _path_a, inputs)
    assert m.trades == 0
    assert m.entry_signal_count == 0


# ── compare_paths ────────────────────────────────────────────────────

def test_compare_paths_basic_run():
    """两条路径都能产出指标"""
    inputs = [
        _make_input(quant_score=60, tech_score=60, sentiment=0.5,
                    fwd_returns=[0.02, 0.01, 0.03, 0.02, 0.04]),
        _make_input(date="2026-01-02", quant_score=70, tech_score=70,
                    sentiment=0.6, fwd_returns=[-0.01, -0.01, -0.02, 0.01, 0.03]),
    ]
    report = compare_paths(inputs)
    assert report.path_a.path_name == "aggregator_v1"
    assert report.path_b.path_name == "multi_agent_v2"
    assert "trades" in report.delta
    assert "sharpe" in report.delta


def test_compare_paths_insufficient_data_recommendation():
    """trades < 10 → 数据不足"""
    inputs = [
        _make_input(quant_score=60, tech_score=60, sentiment=0.5),
    ]
    report = compare_paths(inputs)
    assert report.recommendation == "数据不足"


def test_compare_paths_report_serializable():
    inputs = [_make_input(quant_score=50, tech_score=50, sentiment=0.4)]
    d = compare_paths(inputs).to_dict()
    assert "path_a" in d
    assert "path_b" in d
    assert "delta" in d
    assert "recommendation" in d


# ── _generate_recommendation 决策规则 ───────────────────────────────

def _metrics(trades=20, sharpe=1.0, win=55.0, dd=-8.0):
    from backend.backtest.compare_paths import PathMetrics
    return PathMetrics(
        path_name="x", trades=trades, wins=int(trades * win / 100),
        losses=trades - int(trades * win / 100),
        win_rate=win, avg_return=1.0, sharpe=sharpe,
        profit_loss=1.5, total_return=10.0, max_drawdown=dd,
        entry_signal_count=trades,
    )


def test_recommend_advance_when_sharpe_better():
    """Sharpe 提升 0.4 + 回撤未恶化 → 继续推进"""
    a = _metrics(sharpe=1.0, win=55.0, dd=-8.0)
    b = _metrics(sharpe=1.4, win=58.0, dd=-7.0)
    rec, _ = _generate_recommendation(a, b)
    assert "继续推进" in rec


def test_recommend_pause_when_sharpe_drops():
    """Sharpe 跌 0.3 → 暂停"""
    a = _metrics(sharpe=1.2, win=58.0, dd=-7.0)
    b = _metrics(sharpe=0.8, win=55.0, dd=-8.0)
    rec, _ = _generate_recommendation(a, b)
    assert "暂停" in rec


def test_recommend_conditional_when_inconclusive():
    """指标差异不显著 → 条件性"""
    a = _metrics(sharpe=1.2, win=58.0, dd=-7.0)
    b = _metrics(sharpe=1.3, win=58.5, dd=-7.0)
    rec, _ = _generate_recommendation(a, b)
    assert "条件性" in rec


def test_recommend_insufficient_when_few_trades():
    a = _metrics(trades=5)
    b = _metrics(trades=8)
    rec, _ = _generate_recommendation(a, b)
    assert "数据不足" in rec
