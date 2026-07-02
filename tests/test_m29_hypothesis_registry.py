def test_default_registry_is_read_only_and_preregistered():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry(as_of_date="2026-05-31")

    assert report["run_mode"] == "read_only_hypothesis_registry"
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["saves_model"] is False
    assert report["validation"]["passed"] is True
    assert {item["hypothesis_id"] for item in report["hypotheses"]} == {
        "regime_low_vol_alpha_v1",
        "intra_industry_relative_strength_v1",
        "liquidity_turnover_state_v1",
        "post_event_drift_pure_polarity_v1",
        "top_decile_entry_timing_v1",
    }
    assert all(item["candidate_type"] == "shadow_research_candidate" for item in report["hypotheses"])


def test_promotion_gate_matches_settings():
    from backend.config import settings
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()

    for hypothesis in report["hypotheses"]:
        gate = hypothesis["promotion_gate"]
        assert gate["ic_min"] == settings.qlib_train_ic_floor
        assert gate["icir_min"] == settings.qlib_train_icir_floor
        assert gate["stride_icir_min"] == settings.qlib_train_icir_floor
        assert gate["require_monotonic"] is settings.qlib_train_require_monotonic
        assert gate["requires_fresh_oos_forward"] is True


def test_registry_requires_overfit_guard_for_every_hypothesis():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()

    for hypothesis in report["hypotheses"]:
        guard = hypothesis["overfit_guard"]
        assert guard["requires_deflated_sharpe"] is True
        assert guard["deflated_sharpe_min"] == 0.95
        assert guard["requires_pbo"] is True
        assert guard["pbo_max"] == 0.5
        assert guard["must_report_trial_count"] is True
        assert guard["trial_count_source"] == "declared_candidate_family_and_parameter_grid"
        assert guard["statistics_modules"] == [
            "backend.backtest.statistics.deflated_sharpe.deflated_sharpe",
            "backend.backtest.statistics.probability_overfitting.pbo",
        ]


def test_legacy_m27_sources_are_shadow_only():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()

    wrapped_sources = [
        hypothesis
        for hypothesis in report["hypotheses"]
        if any(
            source in " ".join(hypothesis["source_m27_clues"])
            for source in tool.FORBIDDEN_PRODUCTION_SOURCES
        )
    ]

    assert wrapped_sources
    assert all(item["candidate_type"] == "shadow_research_candidate" for item in wrapped_sources)
    assert all("not a production candidate" in item["forbidden_interpretation"] for item in wrapped_sources)


def test_validation_rejects_missing_multiple_comparison():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()
    report["hypotheses"][0].pop("multiple_comparison")

    errors = tool.validate_registry(report)

    assert any("missing required fields: multiple_comparison" in error for error in errors)


def test_validation_rejects_incomplete_promotion_contract():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()
    gate = report["hypotheses"][0]["promotion_gate"]
    gate["stride_icir_min"] = 0.1
    gate["requires_no_data_quality_blockers"] = False
    gate.pop("requires_human_confirmation")

    errors = tool.validate_registry(report)

    assert "regime_low_vol_alpha_v1 promotion_gate.stride_icir_min must be 0.4" in errors
    assert "regime_low_vol_alpha_v1 promotion_gate.requires_no_data_quality_blockers must be True" in errors
    assert "regime_low_vol_alpha_v1 promotion_gate.requires_human_confirmation must be True" in errors


def test_validation_rejects_incomplete_overfit_guard():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()
    guard = report["hypotheses"][0]["overfit_guard"]
    guard["requires_deflated_sharpe"] = False
    guard["pbo_max"] = 0.8
    guard.pop("must_report_trial_count")

    errors = tool.validate_registry(report)

    assert "regime_low_vol_alpha_v1 overfit_guard.requires_deflated_sharpe must be True" in errors
    assert "regime_low_vol_alpha_v1 overfit_guard.pbo_max must be 0.5" in errors
    assert "regime_low_vol_alpha_v1 overfit_guard.must_report_trial_count must be True" in errors


def test_validation_rejects_side_effect_flags_and_missing_stop_conditions():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()
    report["writes_db"] = True
    report["hypotheses"][0]["stop_conditions"] = []

    errors = tool.validate_registry(report)

    assert "writes_db must be false" in errors
    assert any("must define stop_conditions" in error for error in errors)


def test_markdown_renders_hypothesis_ids_and_stop_conditions():
    from backend.tools import m29_hypothesis_registry as tool

    report = tool.build_registry()
    markdown = tool.report_to_markdown(report)

    assert "# M29 Hypothesis Registry" in markdown
    assert "regime_low_vol_alpha_v1" in markdown
    assert "top_decile_entry_timing_v1" in markdown
    assert "stop_conditions" in markdown
    assert "ic_min: 0.04" in markdown
    assert "overfit_guard" in markdown
    assert "deflated_sharpe_min: 0.95" in markdown
    assert "pbo_max: 0.5" in markdown
    assert "must_report_trial_count: True" in markdown
