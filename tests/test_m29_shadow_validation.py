import json


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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
