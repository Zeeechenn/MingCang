"""Quant baseline compatibility and report tests."""


def test_m26_temporary_settings_allows_atomic_quant_profile():
    from backend.config import settings
    from backend.tools.m26_quant_baseline import _temporary_settings

    original = (
        settings.weight_quant,
        settings.weight_technical,
        settings.weight_sentiment,
    )
    with _temporary_settings(
        weight_quant=0.45,
        weight_technical=0.40,
        weight_sentiment=0.15,
    ):
        assert settings.weight_quant == 0.45
        assert settings.weight_technical == 0.40
        assert settings.weight_sentiment == 0.15

    assert (
        settings.weight_quant,
        settings.weight_technical,
        settings.weight_sentiment,
    ) == original


def test_m26_decision_keeps_quant_disabled_without_gate_and_backtest_edge():
    from backend.tools.m26_quant_baseline import decide_quant_weight

    decision = decide_quant_weight(
        {"promotion_gate_settings": {"pass": False}},
        {
            "quant_on": {"trades": 20},
            "quant_off": {"trades": 20},
            "delta_quant_on_minus_off": {
                "total_return_pct": 10.0,
                "sharpe": 1.0,
                "max_drawdown_pct": -1.0,
            },
        },
    )

    assert decision["decision"] == "keep_quant_disabled"
    assert decision["weight_action"] == "keep weight_quant=0.0"


def test_m26_markdown_report_includes_gate_backtest_and_kronos_sections():
    from backend.tools.m26_quant_baseline import report_to_markdown

    report = {
        "generated_at": "2026-05-30T00:00:00+00:00",
        "symbols": ["300001", "300002"],
        "current_model_validation": {
            "status": "ok",
            "model": {"path": "/tmp/lgbm_alpha.pkl", "mtime_utc": "2026-05-18T12:00:00+00:00"},
            "metrics": {"ic_mean": 0.01, "icir": 0.2},
            "gates": {"pass_monotonic": False},
            "promotion_gate_settings": {"pass": False, "ic_floor": 0.02, "icir_floor": 0.3},
        },
        "historical_profile_backtest": {
            "start": "2026-01-01",
            "end": "2026-02-01",
            "every_n_days": 5,
            "signal_inputs": 12,
            "lookahead_quant_warning": "diagnostic only",
            "quant_off": {
                "trades": 3,
                "win_rate_pct": 33.33,
                "total_return_pct": -1.0,
                "sharpe": -0.5,
                "max_drawdown_pct": 2.0,
            },
            "quant_on": {
                "trades": 4,
                "win_rate_pct": 50.0,
                "total_return_pct": 2.0,
                "sharpe": 0.4,
                "max_drawdown_pct": 1.5,
            },
            "delta_quant_on_minus_off": {
                "trades": 1,
                "win_rate_pct": 16.67,
                "total_return_pct": 3.0,
                "sharpe": 0.9,
                "max_drawdown_pct": -0.5,
            },
            "benchmarks": {
                "equal_weight_test2": {"n_symbols": 2, "total_return_pct": 1.2},
                "hs300": {"status": "unavailable_in_local_price_table"},
            },
        },
        "kronos_feasibility": {
            "decision": "defer_production_integration",
            "minimum_interface": {"integration_point": "backend.decision.aggregator._blend_quant"},
        },
        "decision": {
            "decision": "keep_quant_disabled",
            "weight_action": "keep weight_quant=0.0",
            "rationale": "not enough evidence",
        },
    }

    markdown = report_to_markdown(report)

    assert "M26 量化基线报告" in markdown
    assert "当前 LightGBM 模型验证" in markdown
    assert "quant_on" in markdown
    assert "Kronos 可行性结论" in markdown
    assert "keep weight_quant=0.0" in markdown


def test_m26_load_test2_symbols_accepts_dict_payload(tmp_path):
    from backend.tools.m26_quant_baseline import load_test2_symbols

    path = tmp_path / "universe.json"
    path.write_text('{"stocks": [{"symbol": "300001"}, {"symbol": "300002"}]}', encoding="utf-8")

    assert load_test2_symbols(path) == ["300001", "300002"]


def test_blend_quant_clamps_kronos_and_ignores_invalid(monkeypatch):
    from backend.config import settings
    from backend.decision.aggregator import _blend_quant

    monkeypatch.setattr(settings, "kronos_enabled", True)
    monkeypatch.setattr(settings, "kronos_weight_in_quant", 0.5)

    blended, info = _blend_quant(20.0, {"score": 500.0})

    assert blended == 60.0
    assert info["kronos_score"] == 100.0

    blended, info = _blend_quant(20.0, {"score": "bad"})

    assert blended == 20.0
    assert info["kronos_ignored"] == "missing_or_invalid_score"
