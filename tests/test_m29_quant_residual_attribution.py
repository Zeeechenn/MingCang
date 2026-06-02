from backend.backtest.compare_paths import SignalInput


def _input(symbol, date, *, quant, technical, sentiment, returns=None):
    return SignalInput(
        symbol=symbol,
        date=date,
        technical_result={"score": technical, "latest": {"close": 10.0, "atr14": 0.5}},
        qlib_result={"score": quant, "model": "unit_quant"},
        sentiment_result={"sentiment": sentiment / 100.0, "key_events": ["event"] if sentiment > 50 else []},
        close=10.0,
        atr=0.5,
        forward_returns=returns if returns is not None else [quant / 1000.0 + i * 0.001 for i in range(10)],
    )


def _inputs():
    rows = [
        ("A", -100, 30, 20),
        ("B", 100, 20, 10),
        ("C", 10, 60, 20),
        ("D", 0, 0, 0),
        ("E", 40, 40, -10),
        ("F", -40, 10, 20),
    ]
    return [
        _input(symbol, date, quant=quant, technical=technical, sentiment=sentiment)
        for date in ("2026-01-01", "2026-01-02")
        for symbol, quant, technical, sentiment in rows
    ]


def _bench(inputs, horizons=(1, 3, 5, 10)):
    return {(inp.date, horizon): 0.0 for inp in inputs for horizon in horizons}


def _report(inputs=None, **kwargs):
    from backend.tools import m29_quant_residual_attribution as tool

    inputs = _inputs() if inputs is None else inputs
    return tool.build_report(
        inputs,
        start="2026-01-01",
        end="2026-01-02",
        horizons=kwargs.pop("horizons", (1, 3, 5, 10)),
        benchmark_returns=kwargs.pop("benchmark_returns", _bench(inputs)),
        universe_symbols=6,
        **kwargs,
    )


def test_build_report_is_read_only_non_promoting_shadow_artifact():
    report = _report()
    markdown = __import__(
        "backend.tools.m29_quant_residual_attribution",
        fromlist=["report_to_markdown"],
    ).report_to_markdown(report)

    assert report["schema_version"] == "m29_quant_residual_attribution.v1"
    assert report["milestone"] == "M29.5"
    assert report["run_mode"] == "read_only_quant_residual_attribution"
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["trains_model"] is False
    assert report["non_promoting"] is True
    assert report["signal_profile_unchanged"] is True
    assert report["decision"]["promotable"] is False
    assert "M29.5 Quant Residual Attribution" in markdown
    assert "non_promoting: True" in markdown
    assert "promotable: False" in markdown


def test_fixed_threshold_quant_sweep_only_changes_quant_weight():
    report = _report()
    sweep = report["quant_sweep"]
    arms = sweep["arms"]

    assert sweep["entry_threshold_fixed"] == 25.0
    assert sweep["tech_sent_ratio_fixed"] == "60:40 of non-quant weight"
    assert set(arms) == {"q_0_0", "q_0_225", "q_0_45"}
    assert arms["q_0_0"]["weights"]["quant"] == 0.0
    assert arms["q_0_225"]["weights"]["quant"] == 0.225
    assert arms["q_0_45"]["weights"]["quant"] == 0.45
    assert arms["q_0_45"]["marginal_entries_vs_q_0"]["added_count"] > 0
    assert arms["q_0_45"]["marginal_entries_vs_q_0"]["dropped_count"] > 0
    assert "max_open_positions" in arms["q_0_45"]["metrics"]


def test_trade_attribution_records_threshold_crossers_and_forward_excess_returns():
    report = _report()
    attribution = report["trade_attribution"]
    crossers = attribution["largest_threshold_crossers"]

    assert attribution["crossed_entry_threshold_count"] > 0
    assert attribution["direction_counts"]["added_by_quant"] > 0
    assert attribution["direction_counts"]["dropped_by_quant"] > 0
    first = crossers[0]
    assert "composite_without_quant" in first
    assert "composite_with_quant" in first
    assert "composite_delta" in first
    assert first["crossed_entry_threshold"] is True
    for horizon in (1, 3, 5, 10):
        assert f"forward_return_{horizon}d" in first
        assert f"excess_return_{horizon}d" in first


def test_residual_ic_and_interaction_buckets_are_sample_gated():
    report = _report()
    residual = report["residual_ic"]["5"]

    assert set(residual["score_ic"]) == {
        "technical_only_score",
        "sentiment_event_only_score",
        "technical_sentiment_score",
        "quant_only_score",
        "composite_q_0_45",
    }
    assert "quant_residual_to_technical_sentiment" in residual
    buckets = report["interaction_buckets"]
    assert set(buckets) == {"technical_bucket", "sentiment_bucket", "event_bucket", "volatility_bucket"}
    for rows in buckets.values():
        assert rows
        first = rows[0]
        assert {"bucket", "rows", "n_dates", "ic_mean", "icir", "top_bottom", "monotonic"} <= set(first)


def test_gate_blocks_on_missing_forward_or_excess_returns():
    inputs = [
        _input(inp.symbol, inp.date, quant=inp.qlib_result["score"], technical=inp.technical_result["score"],
               sentiment=inp.sentiment_result["sentiment"] * 100, returns=inp.forward_returns[:5])
        for inp in _inputs()
    ]
    report = _report(inputs, benchmark_returns=_bench(inputs, horizons=(1, 3, 5)), horizons=(1, 3, 5, 10))

    assert report["decision"]["promotable"] is False
    assert "future_return_10d_missing" in report["data_quality_blockers"]
    assert "excess_return_10d_missing" in report["data_quality_blockers"]
    assert "post_registration_fresh_forward_missing" in report["blockers"]


def test_ledger_accepts_quant_residual_attribution_artifact(tmp_path):
    import json

    from backend.tools import m29_evidence_ledger as ledger

    path = tmp_path / "m29_quant_residual_attribution_v1.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")

    report = ledger.build_ledger([path])
    entry = report["entries"][0]

    assert entry["artifact_kind"] == "m29_quant_residual_attribution"
    assert entry["candidate"] == "quant_residual_attribution"
    assert entry["variant"] == "quant_residual_attribution_v1"
    assert entry["gate_pass"] is False
    assert "shadow_validation_non_promoting" in entry["blockers"]
    assert "m29_5_attribution_audit_non_promoting" in entry["blockers"]
    assert "lookahead_quant_warning" in entry["data_quality_blockers"]


def test_ledger_overrides_unsafe_quant_residual_next_action(tmp_path):
    import json

    from backend.tools import m29_evidence_ledger as ledger

    report = _report()
    report["trains_model"] = True
    report["decision"]["recommended_next_action"] = "restore_weight_quant"
    path = tmp_path / "hostile_m29_quant_residual_attribution_v1.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    ledger_report = ledger.build_ledger([path])
    entry = ledger_report["entries"][0]

    assert entry["next_action"] == ledger.QUANT_RESIDUAL_NEXT_ACTION
    assert "source_artifact_trains_model" in entry["blockers"]
    assert "quant_residual_recommended_next_action_ignored" in entry["blockers"]
    assert "quant_residual_recommended_next_action_ignored" in entry["data_quality_blockers"]
