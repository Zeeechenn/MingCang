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


def test_allowed_filter_keys_keeps_target_top_decile_by_date():
    import pandas as pd

    from backend.tools.m27_top_decile_forward_shadow import _allowed_filter_keys

    predictions = pd.DataFrame({
        "date": ["2026-05-15"] * 10 + ["2026-05-18"] * 11,
        "symbol": [str(i) for i in range(21)],
        "pred": list(range(10)) + list(range(11)),
    })

    allowed, info = _allowed_filter_keys(predictions, top_pct=0.10)

    assert len(allowed) == 3
    assert ("2026-05-15", "9") in allowed
    assert ("2026-05-18", "20") in allowed
    assert info["allowed_by_date"] == {"2026-05-15": 1, "2026-05-18": 2}


def test_label_realized_date_identifies_forward_overlap():
    import pandas as pd

    from backend.tools.m27_top_decile_forward_shadow import _with_label_realized_date

    frame = pd.DataFrame({
        "symbol": ["A"] * 5,
        "date": pd.date_range("2026-05-11", periods=5, freq="D"),
    })

    out = _with_label_realized_date(frame, horizon=2)

    realized = out.set_index("date")["_label_realized_date"]
    assert realized[pd.Timestamp("2026-05-12")] == pd.Timestamp("2026-05-14")
    assert realized[pd.Timestamp("2026-05-13")] == pd.Timestamp("2026-05-15")
    start = pd.Timestamp("2026-05-15")
    eligible_train_dates = out[(out["date"] < start) & (out["_label_realized_date"] < start)]["date"].tolist()
    assert eligible_train_dates == [pd.Timestamp("2026-05-11"), pd.Timestamp("2026-05-12")]


def test_default_output_paths_include_exit_days(tmp_path, monkeypatch):
    from backend.tools import m27_top_decile_forward_shadow as tool

    monkeypatch.setattr(tool, "DEFAULT_OUTPUT_DIR", tmp_path)

    json_output, markdown_output = tool.default_output_paths(3)
    rolling_json_output, rolling_markdown_output = tool.default_output_paths(
        3,
        rolling=True,
        start="2026-04-01",
        end="2026-05-22",
    )

    assert json_output == tmp_path / "m27_top_decile_forward_shadow_3d.json"
    assert markdown_output == tmp_path / "m27_top_decile_forward_shadow_3d.md"
    assert rolling_json_output == tmp_path / "m27_top_decile_forward_shadow_rolling_20260401_20260522_3d.json"
    assert rolling_markdown_output == tmp_path / "m27_top_decile_forward_shadow_rolling_20260401_20260522_3d.md"


def test_rolling_windows_generate_weekly_calendar_windows():
    from backend.tools.m27_top_decile_forward_shadow import rolling_windows

    windows = rolling_windows("2026-04-01", "2026-04-15", window_days=7, stride_days=7)

    assert windows == [
        {"start": "2026-04-01", "end": "2026-04-07"},
        {"start": "2026-04-08", "end": "2026-04-14"},
        {"start": "2026-04-15", "end": "2026-04-15"},
    ]


def _window_report(start, end, *, baseline_trades, filtered_trades):
    return {
        "start": start,
        "end": end,
        "sample_adequacy": {
            "baseline_trades": baseline_trades,
            "filtered_trades": filtered_trades,
            "min_trades_for_sharpe": 50,
            "insufficient_for_sharpe": filtered_trades < 50,
        },
        "profile_ab": {
            "baseline_arm": {"metrics": {"trades": baseline_trades}},
            "filtered_arm": {"metrics": {"trades": filtered_trades}},
            "delta_filtered_minus_baseline": {"avg_net_return": 0.01},
        },
        "filter": {"status": "ok"},
    }


def test_build_rolling_report_is_read_only_and_sums_sample_adequacy():
    from backend.tools import m27_top_decile_forward_shadow as tool

    report = tool.build_rolling_report(
        [
            _window_report("2026-04-01", "2026-04-07", baseline_trades=10, filtered_trades=4),
            _window_report("2026-04-08", "2026-04-14", baseline_trades=8, filtered_trades=3),
        ],
        start="2026-04-01",
        end="2026-04-14",
        horizon=20,
        exit_days=5,
        top_pct=0.10,
        window_days=7,
        stride_days=7,
        panel_meta={"n_rows": 100, "n_symbols": 5},
        universe_symbols={"A", "B"},
    )
    markdown = tool.report_to_markdown(report)

    assert report["run_mode"] == "offline_read_only_forward_shadow_rolling"
    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["sample_adequacy"]["baseline_trades"] == 18
    assert report["sample_adequacy"]["filtered_trades"] == 7
    assert report["sample_adequacy"]["insufficient_for_sharpe"] is True
    assert report["rolling"]["window_count"] == 2
    assert report["rolling"]["windows_with_filtered_trades"] == 2
    assert report["aggregate_profile_summary"]["ok_windows"] == 2
    assert report["aggregate_profile_summary"]["positive_avg_net_return_delta_windows"] == 2
    assert report["aggregate_profile_summary"]["trade_weighted_avg_net_return_delta"] == 0.01
    assert "M27.1c Top-Decile Forward Shadow Rolling" in markdown
    assert "| 2026-04-01 | 2026-04-07 | 10 | 4 | True |" in markdown


def test_build_report_is_read_only_and_uses_target_filter(monkeypatch):
    import pandas as pd

    from backend.tools import m27_top_decile_forward_shadow as tool

    monkeypatch.setattr(
        tool,
        "_target_predictions",
        lambda *args, **kwargs: (
            pd.DataFrame({
                "date": ["2026-05-15", "2026-05-15"],
                "symbol": ["A", "B"],
                "pred": [0.9, 0.1],
            }),
            {
                "status": "ok",
                "sample": {
                    "target_rows": 2,
                    "train_label_realized_end": "2026-05-14",
                },
            },
        ),
    )
    monkeypatch.setattr(
        tool,
        "active_signal_weights",
        lambda: type("Weights", (), {"entry_threshold": 25.0})(),
    )
    monkeypatch.setattr(
        tool,
        "_score_input",
        lambda inp: {"composite_score": inp.technical_result["score"], "recommendation": "可小仓试错"},
        raising=False,
    )

    # Patch the imported scorer in the delegated profile builder module.
    from backend.tools import m27_test3_production_profile_ab as profile_tool

    monkeypatch.setattr(
        profile_tool,
        "_score_input",
        lambda inp: {"composite_score": inp.technical_result["score"], "recommendation": "可小仓试错"},
    )

    report = tool.build_report(
        pd.DataFrame({"symbol": ["A", "B"], "date": ["2026-05-15", "2026-05-15"]}),
        panel_meta={"n_rows": 2, "n_symbols": 2},
        inputs=[
            _input("A", "2026-05-15", 60, [0.01, 0.02, 0.03, 0.04, 0.10]),
            _input("B", "2026-05-15", 60, [0.01, 0.02, 0.03, 0.04, -0.05]),
        ],
        universe_symbols={"A", "B"},
        start="2026-05-15",
        end="2026-05-15",
    )
    markdown = tool.report_to_markdown(report)

    assert report["milestone"] == "M27.1c"
    assert report["run_mode"] == "offline_read_only_forward_shadow"
    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["signal_profile_unchanged"] is True
    assert report["universe_hash"] == tool._universe_hash({"A", "B"})
    assert report["train_label_realized_end"] == "2026-05-14"
    assert "data_source" in report
    assert report["data_source"] is None
    assert report["sample_adequacy"]["filtered_trades"] == 1
    assert report["sample_adequacy"]["baseline_trades"] == 2
    assert report["sample_adequacy"]["min_trades_for_sharpe"] == 50
    assert report["sample_adequacy"]["insufficient_for_sharpe"] is True
    assert report["profile_ab"]["baseline_arm"]["metrics"]["trades"] == 2
    assert report["profile_ab"]["filtered_arm"]["metrics"]["trades"] == 1
    assert "M27.1c Top-Decile Forward Shadow" in markdown
    assert "insufficient_for_sharpe: True" in markdown


def test_build_rolling_report_summarizes_forward_provenance():
    from backend.tools import m27_top_decile_forward_shadow as tool

    first = _window_report("2026-04-01", "2026-04-07", baseline_trades=10, filtered_trades=4)
    first["filter"] = {
        "status": "ok",
        "classifier": {"sample": {"train_label_realized_end": "2026-03-31"}},
    }
    second = _window_report("2026-04-08", "2026-04-14", baseline_trades=8, filtered_trades=3)
    second["filter"] = {
        "status": "ok",
        "classifier": {"sample": {"train_label_realized_end": "2026-04-07"}},
    }

    report = tool.build_rolling_report(
        [first, second],
        start="2026-04-01",
        end="2026-04-14",
        horizon=20,
        exit_days=5,
        top_pct=0.10,
        window_days=7,
        stride_days=7,
        panel_meta={"n_rows": 100, "n_symbols": 5},
        universe_symbols={"A", "B"},
    )

    assert report["universe_hash"] == tool._universe_hash({"A", "B"})
    assert report["train_label_realized_end"] == "2026-04-07"
    assert report["train_label_realized_end_range"] == {
        "min": "2026-03-31",
        "max": "2026-04-07",
    }
