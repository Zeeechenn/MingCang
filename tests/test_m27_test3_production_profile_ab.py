from backend.backtest.compare_paths import SignalInput


def _input(symbol, date, score, returns):
    return SignalInput(
        symbol=symbol,
        date=date,
        technical_result={"score": score},
        qlib_result={"score": 0.0},
        sentiment_result={"sentiment": 0.0, "key_events": []},
        close=10.0,
        atr=0.5,
        forward_returns=returns,
    )


def test_build_profile_ab_applies_top_decile_filter(monkeypatch):
    from backend.tools import m27_test3_production_profile_ab as tool

    inputs = [
        _input("A", "2026-01-01", 60, [0.01, 0.02, 0.03, 0.04, 0.10]),
        _input("B", "2026-01-01", 55, [0.01, 0.02, 0.03, 0.04, -0.05]),
        _input("C", "2026-01-01", 10, [0.01, 0.02, 0.03, 0.04, 0.30]),
    ]

    monkeypatch.setattr(
        tool,
        "_score_input",
        lambda inp: {"composite_score": inp.technical_result["score"], "recommendation": "可小仓试错"},
    )

    result = tool.build_profile_ab(
        inputs,
        allowed_filter_keys={("2026-01-01", "A")},
        exit_days=5,
        entry_threshold=25,
    )

    assert result["baseline_arm"]["metrics"]["trades"] == 2
    assert result["filtered_arm"]["metrics"]["trades"] == 1
    assert result["baseline_arm"]["metrics"]["wins"] == 1
    assert result["filtered_arm"]["metrics"]["wins"] == 1
    assert result["delta_filtered_minus_baseline"]["trades"] == -1


def test_build_report_is_non_promoting_and_read_only(monkeypatch):
    import pandas as pd

    from backend.tools import m27_test3_production_profile_ab as tool

    monkeypatch.setattr(
        tool,
        "_allowed_filter_keys",
        lambda *args, **kwargs: ({("2026-01-01", "A")}, {"status": "ok", "allowed_filter_keys": 1}),
    )
    monkeypatch.setattr(
        tool,
        "_score_input",
        lambda inp: {"composite_score": inp.technical_result["score"], "recommendation": "可小仓试错"},
    )
    monkeypatch.setattr(
        tool,
        "active_signal_weights",
        lambda: type("Weights", (), {"entry_threshold": 25.0})(),
    )

    report = tool.build_report(
        pd.DataFrame({"symbol": ["A"], "date": ["2026-01-01"]}),
        panel_meta={"n_rows": 1, "n_symbols": 1, "cache_hit": True},
        inputs=[
            _input("A", "2026-01-01", 60, [0.01, 0.02, 0.03, 0.04, 0.10]),
            _input("B", "2026-01-01", 60, [0.01, 0.02, 0.03, 0.04, -0.05]),
        ],
        universe_symbols={"A", "B"},
    )
    markdown = tool.report_to_markdown(report)

    assert report["milestone"] == "M27.1c"
    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["signal_profile_unchanged"] is True
    assert report["profile_ab"]["baseline_arm"]["metrics"]["trades"] == 2
    assert report["profile_ab"]["filtered_arm"]["metrics"]["trades"] == 1
    assert report["decision"]["decision"] == "production_unchanged"
    assert "M27.1c Test3 Production-Profile A/B" in markdown
    assert "non_promoting: True" in markdown
    assert "production_unchanged: True" in markdown
