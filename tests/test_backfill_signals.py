import pandas as pd


class _Weights:
    def __init__(self, quant: float, profile: str) -> None:
        self.quant = quant
        self.profile = profile


def test_backfill_quant_skips_qlib_when_weight_zero(monkeypatch):
    from backend.backtest import backfill_signals

    called = False

    def fake_qlib_score(*args, **kwargs):
        nonlocal called
        called = True
        return {"score": 99.0, "model": "lgbm_alpha_v1"}

    monkeypatch.setattr("backend.config.active_signal_weights", lambda _date: _Weights(0.0, "new_framework"))
    monkeypatch.setattr("backend.analysis.qlib_engine.qlib_score", fake_qlib_score)

    result = backfill_signals._quant_result_for_backfill(
        pd.DataFrame({"close": [1, 2, 3]}),
        "300308",
        "2026-05-21",
        db=None,
    )

    assert called is False
    assert result["score"] == 0.0
    assert result["model"] == "disabled_quant_weight_zero"
    assert result["profile"] == "new_framework"


def test_backfill_quant_blocks_current_model_when_quant_weight_positive(monkeypatch):
    from backend.backtest import backfill_signals

    called = False

    def fake_qlib_score(*args, **kwargs):
        nonlocal called
        called = True
        return {"score": 99.0, "model": "lgbm_alpha_v1"}

    monkeypatch.setattr("backend.config.active_signal_weights", lambda _date: _Weights(0.45, "test1_legacy_qlib"))
    monkeypatch.setattr("backend.analysis.qlib_engine.qlib_score", fake_qlib_score)

    result = backfill_signals._quant_result_for_backfill(
        pd.DataFrame({"close": [1, 2, 3]}),
        "300308",
        "2026-05-15",
        db=None,
    )

    assert called is False
    assert result["score"] == 0.0
    assert result["model"] == "disabled_lookahead_guard"
    assert result["quant_weight"] == 0.45
    assert result["as_of"] == "2026-05-15"


def test_backfill_quant_allows_explicit_lookahead_experiment(monkeypatch):
    from backend.backtest import backfill_signals

    monkeypatch.setattr("backend.config.active_signal_weights", lambda _date: _Weights(0.45, "test1_legacy_qlib"))
    monkeypatch.setattr(
        "backend.analysis.qlib_engine.qlib_score",
        lambda *args, **kwargs: {"score": 12.3, "model": "lgbm_alpha_v1"},
    )

    result = backfill_signals._quant_result_for_backfill(
        pd.DataFrame({"close": [1, 2, 3]}),
        "300308",
        "2026-05-15",
        db=None,
        allow_lookahead_quant=True,
    )

    assert result["score"] == 12.3
    assert result["model"] == "lgbm_alpha_v1"
    assert result["lookahead_warning"] is True
    assert result["as_of"] == "2026-05-15"
