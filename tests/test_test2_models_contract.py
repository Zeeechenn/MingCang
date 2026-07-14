from __future__ import annotations


def test_tracked_test2_models_expose_replay_contract():
    from backend.backtest.test2_models import FRAMEWORKS, Signal, composite_for

    signal = Signal(
        symbol="000001.SZ",
        name="示例",
        date="2026-07-14",
        quant=10.0,
        tech=20.0,
        sent=30.0,
        stop_loss=None,
        take_profit=None,
    )

    assert composite_for(signal, FRAMEWORKS["B_quant_off"]) == 24.0
