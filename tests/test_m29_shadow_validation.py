import json


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _event_ab_payload(*, cache_miss_windows=0, rows_with_fallback_polarity=0):
    return {
        "generated_at": "2026-05-31T13:35:29+00:00",
        "sample": {
            "n_rows": 113509,
            "n_symbols": 100,
            "n_dates": 1772,
            "start": "2019-01-25",
            "end": "2026-05-22",
        },
        "event_ab_5d": {
            "coverage": {
                "universe_symbols": 100,
                "rows_with_news": 1010,
                "rows_with_polarity": 1010,
                "rows_with_cache_polarity": 1010,
                "rows_with_fallback_polarity": rows_with_fallback_polarity,
                "cache_miss_windows": cache_miss_windows,
                "lookback_days": 5,
                "rows_with_event_override": 373,
                "event_type_hits": 659,
            },
            "event_ab_gate": {
                "ic_floor": 0.04,
                "icir_floor": 0.4,
                "require_monotonic": True,
                "multiple_comparison_warning": (
                    "event lookback and pure/event variants are exploratory; require fresh OOS"
                ),
            },
            "polarity": {
                "ic_days": 29,
                "ic_mean": 0.180828,
                "icir": 0.549296,
                "ic_positive_rate": 0.724138,
            },
            "pure_polarity_validation": {
                "top_bottom_oriented": 0.018281,
                "monotonic_oriented": False,
                "passes_min_ic_days": True,
                "passes_quantile_sample": True,
                "passes_sample_gate": True,
                "passes_ic_floor": True,
                "passes_icir_floor": True,
                "passes_quantile_monotonic_gate": False,
                "data_quality_blockers": [],
                "passes_event_ab_gate": False,
                "gate_blockers": ["not_monotonic"],
            },
            "polarity_event": {
                "ic_days": 29,
                "ic_mean": 0.131126,
                "icir": 0.410776,
                "ic_positive_rate": 0.689655,
            },
            "polarity_event_validation": {
                "top_bottom_oriented": 0.014853,
                "monotonic_oriented": False,
                "passes_min_ic_days": True,
                "passes_quantile_sample": True,
                "passes_sample_gate": True,
                "passes_ic_floor": True,
                "passes_icir_floor": True,
                "passes_quantile_monotonic_gate": False,
                "data_quality_blockers": [],
                "passes_event_ab_gate": False,
                "gate_blockers": ["not_monotonic"],
            },
            "variant_comparison": {
                "event_beats_pure_ic": False,
                "event_beats_pure_icir": False,
                "recommended_variant": "none",
                "production_unchanged": True,
            },
        },
    }


def test_top_decile_shadow_validation_wraps_1d_rolling_artifact(tmp_path):
    from backend.tools import m29_shadow_validation as tool

    source = _write_json(
        tmp_path / "m27_forward_shadow_rolling_1d.json",
        {
            "generated_at": "2026-05-31T00:00:00Z",
            "run_mode": "offline_read_only_forward_shadow_rolling",
            "production_unchanged": True,
            "writes_db": False,
            "calls_llm_or_api": False,
            "saves_model": False,
            "start": "2026-04-01",
            "end": "2026-05-29",
            "horizon": 20,
            "exit_days": 1,
            "panel": {"start": "2019-01-25", "end": "2026-05-29", "n_rows": 1000},
            "rolling": {
                "window_count": 9,
                "windows_with_filtered_trades": 8,
            },
            "aggregate_profile_summary": {
                "positive_avg_net_return_delta_windows": 7,
                "baseline_trades_total": 691,
                "filtered_trades_total": 99,
                "trade_weighted_avg_net_return_delta": 0.047711,
            },
            "sample_adequacy": {
                "filtered_trades": 99,
                "baseline_trades": 691,
                "min_trades_for_sharpe": 50,
                "insufficient_for_sharpe": False,
            },
        },
    )

    report = tool.build_report(source)
    markdown = tool.report_to_markdown(report)

    assert report["run_mode"] == "read_only_shadow_validation"
    assert report["hypothesis_id"] == "top_decile_entry_timing_v1"
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["candidate_type"] == "shadow_research_candidate"
    assert report["shadow_validation"]["sample_gate_pass"] is True
    assert report["shadow_validation"]["gate_pass"] is False
    assert report["decision"]["promotable"] is False
    assert report["candidate_summary"]["sample_gate"]["filtered_trades"] == 99
    assert report["candidate_summary"]["sample_gate"]["positive_rolling_windows"] == 7
    assert "post_registration_fresh_forward_missing" in report["blockers"]
    assert "not_continuous_quant_score" in report["blockers"]
    assert "missing_source_data_source" in report["data_quality_blockers"]
    assert "M29 Shadow Validation" in markdown
    assert "passes_min_filtered_trades: True" in markdown


def test_top_decile_shadow_validation_flags_bad_source_shape(tmp_path):
    from backend.tools import m29_shadow_validation as tool

    source = _write_json(
        tmp_path / "m27_forward_shadow_rolling_3d.json",
        {
            "run_mode": "offline_read_only_forward_shadow_rolling",
            "production_unchanged": True,
            "writes_db": False,
            "calls_llm_or_api": False,
            "saves_model": False,
            "exit_days": 3,
            "aggregate_profile_summary": {
                "positive_avg_net_return_delta_windows": 1,
                "filtered_trades_total": 42,
            },
            "sample_adequacy": {"filtered_trades": 42},
        },
    )

    report = tool.build_report(source)

    assert report["shadow_validation"]["sample_gate_pass"] is False
    assert "source_exit_days_not_1" in report["blockers"]
    assert "filtered_trades_below_sample_gate" in report["blockers"]
    assert "positive_rolling_windows_below_sample_gate" in report["blockers"]


def test_post_event_shadow_validation_wraps_event_ab_artifact(tmp_path):
    from backend.tools import m29_shadow_validation as tool

    source = _write_json(tmp_path / "m27_alpha_event_ab_v2.json", _event_ab_payload())

    report = tool.build_report(source, hypothesis_id="post_event_drift_pure_polarity_v1")
    markdown = tool.report_to_markdown(report)

    assert report["run_mode"] == "read_only_shadow_validation"
    assert report["hypothesis_id"] == "post_event_drift_pure_polarity_v1"
    assert report["candidate_family"] == "post_event_drift"
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["horizon"] == 5
    assert report["panel"]["n_rows"] == 113509
    assert report["multiple_comparison"]["n_candidates_tested"] == 2
    assert "require fresh OOS" in report["multiple_comparison"]["warning"]
    assert report["candidate_summary"]["candidate_count"] == 2
    assert report["candidate_summary"]["best_candidate"]["name"] == "pure_polarity_lookback5"
    assert report["candidate_summary"]["best_candidate"]["raw_ic"] == 0.180828
    assert report["candidate_summary"]["best_candidate"]["raw_icir"] == 0.549296
    assert report["candidate_summary"]["best_candidate"]["raw_ic_days"] == 29
    assert report["candidate_summary"]["best_candidate"]["raw_pass_monotonic"] is False
    assert report["candidate_summary"]["sample_gate"]["passes_min_symbols"] is True
    assert report["candidate_summary"]["sample_gate"]["passes_min_validation_rows"] is True
    assert report["candidate_summary"]["sample_gate"]["passes_cache_miss_windows"] is True
    assert report["candidate_summary"]["sample_gate"]["passes_rows_with_fallback_polarity"] is True
    assert report["shadow_validation"]["sample_gate_pass"] is True
    assert report["shadow_validation"]["gate_pass"] is False
    assert report["decision"]["promotable"] is False
    assert "pure_polarity_not_monotonic" in report["blockers"]
    assert "polarity_event_not_monotonic" in report["blockers"]
    assert "post_registration_fresh_forward_missing" in report["blockers"]
    assert "missing_source_data_source" in report["data_quality_blockers"]
    assert "M29 Shadow Validation" in markdown
    assert "hypothesis_id: post_event_drift_pure_polarity_v1" in markdown
    assert "raw_icir: 0.549296" in markdown


def test_post_event_shadow_validation_flags_cache_and_fallback_gaps(tmp_path):
    from backend.tools import m29_shadow_validation as tool

    source = _write_json(
        tmp_path / "m27_alpha_event_ab_v2.json",
        _event_ab_payload(cache_miss_windows=1, rows_with_fallback_polarity=2),
    )

    report = tool.build_report(source, hypothesis_id="post_event_drift_pure_polarity_v1")

    assert report["shadow_validation"]["sample_gate_pass"] is False
    assert report["candidate_summary"]["sample_gate"]["passes_cache_miss_windows"] is False
    assert report["candidate_summary"]["sample_gate"]["passes_rows_with_fallback_polarity"] is False
    assert "cache_miss_windows_not_zero" in report["blockers"]
    assert "rows_with_fallback_polarity_not_zero" in report["blockers"]
