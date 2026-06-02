import hashlib
import json


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _rolling_artifact_payload(*, start="2026-04-01", end="2026-06-05", exit_days=1):
    return {
        "generated_at": "2026-06-05T00:00:00Z",
        "run_mode": "offline_read_only_forward_shadow_rolling",
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "start": start,
        "end": end,
        "exit_days": exit_days,
        "sample_adequacy": {
            "baseline_trades": 100,
            "filtered_trades": 60,
            "min_trades_for_sharpe": 50,
            "insufficient_for_sharpe": False,
        },
        "aggregate_profile_summary": {
            "positive_avg_net_return_delta_windows": 3,
            "trade_weighted_avg_net_return_delta": 0.02,
        },
        "rolling": {"window_count": 3},
        "filter": {"status": "ok"},
    }


def test_build_ledger_normalizes_m27_artifacts_and_stays_read_only(tmp_path):
    from backend.tools import m29_evidence_ledger as tool

    top_decile = _write_json(
        tmp_path / "m27_top_decile_forward_shadow_1d.json",
        {
            "generated_at": "2026-05-31T00:00:00Z",
            "run_mode": "offline_read_only_forward_shadow",
            "production_unchanged": True,
            "writes_db": False,
            "calls_llm_or_api": False,
            "saves_model": False,
            "start": "2026-05-15",
            "end": "2026-05-22",
            "exit_days": 1,
            "sample_adequacy": {
                "baseline_trades": 100,
                "filtered_trades": 19,
                "min_trades_for_sharpe": 50,
                "insufficient_for_sharpe": True,
            },
            "profile_ab": {"delta_filtered_minus_baseline": {"avg_net_return": 0.02}},
            "filter": {"status": "ok"},
        },
    )
    event_ab = _write_json(
        tmp_path / "m27_alpha_event_ab_v2.json",
        {
            "generated_at": "2026-05-31T00:00:00Z",
            "production_unchanged": True,
            "writes_db": False,
            "calls_llm_or_api": False,
            "saves_model": False,
            "event_ab_5d": {
                "coverage": {
                    "rows_with_polarity": 1010,
                    "rows_with_news": 1010,
                    "rows_with_cache_polarity": 1010,
                    "rows_with_fallback_polarity": 0,
                    "cache_miss_windows": 0,
                },
                "event_ab_gate": {
                    "ic_floor": 0.04,
                    "icir_floor": 0.4,
                    "multiple_comparison_warning": "2 candidates tested",
                },
                "polarity": {"ic_mean": 0.18, "icir": 0.55, "ic_days": 29},
                "pure_polarity_validation": {
                    "top_bottom_oriented": 0.018,
                    "monotonic_oriented": False,
                    "passes_event_ab_gate": False,
                    "gate_blockers": ["not_monotonic"],
                    "data_quality_blockers": [],
                },
                "polarity_event": {"ic_mean": 0.13, "icir": 0.41, "ic_days": 29},
                "polarity_event_validation": {
                    "top_bottom_oriented": 0.015,
                    "monotonic_oriented": False,
                    "passes_event_ab_gate": False,
                    "gate_blockers": ["not_monotonic"],
                    "data_quality_blockers": [],
                },
                "variant_comparison": {"production_unchanged": True},
            },
        },
    )
    label_objective = _write_json(
        tmp_path / "m27_label_objective_eval.json",
        {
            "generated_at": "2026-05-31T00:00:00Z",
            "production_unchanged": True,
            "panel": {
                "start": "2025-01-01",
                "end": "2026-05-29",
                "n_rows": 1000,
                "price_provenance": {
                    "price_rows_total": 1000,
                    "price_rows_with_source": 900,
                    "price_rows_with_fetched_at": 900,
                    "price_rows_with_adjustment": 1000,
                    "missing_price_provenance_rows": 100,
                    "source_counts": {"unit_provider": 900},
                    "adjustment_counts": {"qfq": 1000},
                    "fetched_at_min": "2026-05-31T00:00:00",
                    "fetched_at_max": "2026-05-31T00:00:00",
                },
            },
            "gate": {"ic_min": 0.04, "icir_min": 0.4},
            "candidates": [{"name": "raw_20d_top_decile_classifier"}],
            "multi_exit_summary": [{"candidate": "raw_20d_top_decile_classifier"}],
            "short_horizon_candidates": {
                "non_promoting": True,
                "candidates": [{"name": "raw_1d_regression_short_cycle"}],
                "decision": {"decision": "short_cycle_candidate_ready_for_non_promoting_validation"},
            },
            "sector_industry_specific_candidates": {
                "non_promoting": True,
                "segment_cols": ["volatility_regime"],
                "promotion_blocker": "offline validation only",
                "candidates": [{"name": "raw_20d_regression_segment_specific"}],
            },
            "decision": {
                "decision": "keep_quant_disabled",
                "best_raw_candidate": "raw_20d_top_decile_classifier",
                "best_raw_ic": 0.109,
                "best_raw_icir": 0.394,
                "best_raw_stride_icir": 0.3,
                "best_raw_stride_icir_gate_passed": False,
                "raw_gate_pass_count": 0,
                "raw_stride_gate_pass_count": 0,
                "multiple_comparison_warning": "candidate count reported",
            },
        },
    )

    report = tool.build_ledger([top_decile, event_ab, label_objective, tmp_path / "missing.json"])
    markdown = tool.report_to_markdown(report)

    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["production_unchanged"] is True
    assert report["promotion_contract"]["ic_floor"] == 0.04
    assert report["summary"]["entries"] == 4
    assert report["summary"]["promotable_count"] == 0
    assert report["summary"]["entries_with_missing_provenance"] == 4
    assert report["summary"]["skipped_artifacts"] == 1
    assert report["provenance_contract"]["required_fields"] == [
        "artifact_sha256",
        "source_generated_at",
        "data_source",
        "fetched_at",
        "adjustment",
        "universe_hash",
        "train_label_realized_end",
    ]
    assert len(report["next_forward_commands"]) == 3
    assert "--exit-days 1" in report["next_forward_commands"][0]
    assert all(entry["non_promoting"] is True for entry in report["entries"])
    first_entry = report["entries"][0]
    expected_hash = hashlib.sha256(top_decile.read_bytes()).hexdigest()
    assert first_entry["provenance"]["artifact_sha256"] == expected_hash
    assert "data_source" in first_entry["provenance"]["missing_provenance_fields"]
    assert "missing_provenance_data_source" in first_entry["data_quality_blockers"]
    blockers = {blocker for entry in report["entries"] for blocker in entry["blockers"]}
    assert "insufficient_filtered_trades_for_sharpe" in blockers
    assert "not_monotonic" in blockers
    assert "decision_keep_quant_disabled" in blockers
    assert "stride_icir_gate_not_passed" in blockers
    event_entries = [entry for entry in report["entries"] if entry["candidate"] == "sentiment_event_alpha"]
    assert event_entries[0]["sample_size"]["cache_miss_windows"] == 0
    assert event_entries[0]["sample_size"]["rows_with_fallback_polarity"] == 0
    label_entry = [entry for entry in report["entries"] if entry["candidate"] == "label_objective_search"][0]
    assert label_entry["provenance"]["panel_price_provenance_missing_rows"] == 100
    assert "panel_price_provenance_incomplete" in label_entry["data_quality_blockers"]
    assert label_entry["sub_evidence_summary"]["multi_exit_candidate_count"] == 1
    assert label_entry["sub_evidence_summary"]["short_horizon_candidate_count"] == 1
    assert label_entry["sub_evidence_summary"]["sector_segment_candidate_count"] == 1
    assert "M29 Evidence Ledger" in markdown
    assert "Promotion Contract" in markdown
    assert "entries_with_missing_provenance" in markdown
    assert "requires_human_confirmation: True" in markdown
    assert "requires_no_data_quality_blockers: True" in markdown
    assert "Next Forward Commands" in markdown
    assert "do not restore weight_quant" in markdown


def test_default_artifacts_discovers_latest_m29_forward_artifacts(tmp_path):
    from backend.tools import m29_evidence_ledger as tool

    _write_json(
        tmp_path / "m29_forward_shadow_rolling_20260401_20260601_1d.json",
        _rolling_artifact_payload(end="2026-06-01", exit_days=1),
    )
    latest_1d = _write_json(
        tmp_path / "m29_forward_shadow_rolling_20260401_20260605_1d.json",
        _rolling_artifact_payload(end="2026-06-05", exit_days=1),
    )
    latest_3d = _write_json(
        tmp_path / "m29_forward_shadow_rolling_20260401_20260604_3d.json",
        _rolling_artifact_payload(end="2026-06-04", exit_days=3),
    )
    _write_json(
        tmp_path / "m29_forward_shadow_rolling_20260401_latest_5d.json",
        _rolling_artifact_payload(end="2026-06-05", exit_days=5),
    )

    paths = tool.default_artifacts(static_artifacts=[], artifact_dir=tmp_path)
    report = tool.build_ledger(paths)

    assert paths == [latest_1d, latest_3d]
    assert report["summary"]["entries"] == 2
    assert {entry["variant"] for entry in report["entries"]} == {"rolling_1d", "rolling_3d"}


def test_discovered_malformed_m29_forward_artifact_is_skipped(tmp_path):
    from backend.tools import m29_evidence_ledger as tool

    bad = tmp_path / "m29_forward_shadow_rolling_20260401_20260605_5d.json"
    bad.write_text("{bad json", encoding="utf-8")

    report = tool.build_ledger(tool.default_artifacts(static_artifacts=[], artifact_dir=tmp_path))

    assert report["summary"]["entries"] == 0
    assert report["summary"]["skipped_artifacts"] == 1
    assert report["skipped_artifacts"][0]["path"] == str(bad)
    assert report["skipped_artifacts"][0]["reason"].startswith("load_or_parse_error")


def test_next_forward_commands_can_render_concrete_forward_end():
    from backend.tools import m29_evidence_ledger as tool

    commands = tool.next_forward_commands(forward_end="2026-06-05")

    assert len(commands) == 3
    assert all("<LATEST_TRADING_DAY_AFTER_2026-05-29>" not in command for command in commands)
    assert all("--end 2026-06-05" in command for command in commands)
    assert "/private/tmp/m29_forward_shadow_rolling_20260401_20260605_1d.json" in commands[0]


def test_build_ledger_flags_source_side_effects(tmp_path):
    from backend.tools import m29_evidence_ledger as tool

    artifact = _write_json(
        tmp_path / "unsafe_forward_shadow.json",
        {
            "run_mode": "offline_read_only_forward_shadow",
            "production_unchanged": False,
            "writes_db": True,
            "calls_llm_or_api": True,
            "saves_model": False,
            "trains_model": True,
            "exit_days": 5,
            "sample_adequacy": {"filtered_trades": 60},
        },
    )

    report = tool.build_ledger([artifact])
    entry = report["entries"][0]

    assert entry["production_unchanged"] is False
    assert "source_artifact_writes_db" in entry["blockers"]
    assert "source_artifact_calls_llm_or_api" in entry["data_quality_blockers"]
    assert "source_artifact_trains_model" in entry["blockers"]
    assert "source_artifact_production_changed" in entry["blockers"]


def test_build_ledger_treats_missing_boundary_flags_as_unknown(tmp_path):
    from backend.tools import m29_evidence_ledger as tool

    artifact = _write_json(
        tmp_path / "legacy_label_objective.json",
        {
            "panel": {"n_rows": 10},
            "gate": {"ic_min": 0.04},
            "candidates": [{"name": "candidate"}],
            "decision": {"best_raw_candidate": "candidate"},
        },
    )

    report = tool.build_ledger([artifact])
    entry = report["entries"][0]

    assert entry["production_unchanged"] is None
    assert entry["unknown_boundary_flags"] == [
        "production_unchanged",
        "writes_db",
        "calls_llm_or_api",
        "saves_model",
        "trains_model",
    ]
    assert "unknown_source_production_unchanged" in entry["blockers"]
    assert "unknown_source_writes_db" in entry["data_quality_blockers"]


def test_build_ledger_accepts_m29_shadow_validation_artifact(tmp_path):
    from backend.tools import m29_evidence_ledger as tool

    artifact = _write_json(
        tmp_path / "m29_shadow_validation_top_decile.json",
        {
            "generated_at": "2026-05-31T00:00:00Z",
            "schema_version": "m29_shadow_validation.v1",
            "run_mode": "read_only_shadow_validation",
            "hypothesis_id": "top_decile_entry_timing_v1",
            "candidate_family": "top_decile_entry_timing",
            "production_unchanged": True,
            "writes_db": False,
            "calls_llm_or_api": False,
            "saves_model": False,
            "start": "2026-04-01",
            "end": "2026-05-29",
            "exit_days": 1,
            "multiple_comparison": {"n_candidates_tested": 1, "warning": None},
            "promotion_gate": {"ic_min": 0.04, "icir_min": 0.4, "require_monotonic": True},
            "candidate_summary": {
                "candidate_count": 1,
                "best_candidate": {
                    "sample": {
                        "baseline_trades": 691,
                        "filtered_trades": 99,
                        "positive_windows": 7,
                        "window_count": 9,
                    },
                    "raw_top_bottom": 0.047711,
                    "raw_pass_monotonic": None,
                },
            },
            "shadow_validation": {
                "decision": "sample_gate_passed_keep_collecting_fresh_forward",
                "gate_pass": False,
                "raw_stride_gate_pass": False,
                "blockers": [
                    "post_registration_fresh_forward_missing",
                    "not_continuous_quant_score",
                ],
            },
            "data_quality_blockers": ["missing_source_data_source"],
        },
    )

    report = tool.build_ledger([artifact])
    entry = report["entries"][0]

    assert report["summary"]["entries"] == 1
    assert entry["artifact_kind"] == "m29_shadow_validation"
    assert entry["candidate"] == "top_decile_entry_timing"
    assert entry["variant"] == "top_decile_entry_timing_v1"
    assert entry["gate_pass"] is False
    assert entry["sample_size"]["filtered_trades"] == 99
    assert entry["sample_size"]["positive_windows"] == 7
    assert entry["metrics"]["top_bottom"] == 0.047711
    assert "shadow_validation_non_promoting" in entry["blockers"]
    assert "missing_source_data_source" in entry["data_quality_blockers"]
