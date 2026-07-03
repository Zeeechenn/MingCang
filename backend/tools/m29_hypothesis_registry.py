"""Build a read-only M29 alpha hypothesis registry.

The registry pre-registers research hypotheses before another experiment is
run. It writes only JSON/Markdown artifacts and never opens the MingCang DB,
calls LLM/API services, saves models, or changes production configuration.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings

DEFAULT_JSON_OUTPUT = Path.home() / ".mingcang" / "m29_hypothesis_registry.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".mingcang" / "m29_hypothesis_registry.md"
REQUIRED_HYPOTHESIS_FIELDS = {
    "hypothesis_id",
    "status",
    "motivation",
    "source_m27_clues",
    "candidate_type",
    "forbidden_interpretation",
    "sample_scope",
    "features",
    "horizons",
    "split",
    "sample_gates",
    "promotion_gate",
    "overfit_guard",
    "multiple_comparison",
    "stop_conditions",
    "forbidden_actions",
}
FORBIDDEN_PRODUCTION_SOURCES = {
    "raw_20d_top_decile_classifier",
    "pure_polarity",
    "event_overlay",
    "kronos_checkpoint",
}


def promotion_gate() -> dict[str, Any]:
    return {
        "ic_min": settings.qlib_train_ic_floor,
        "icir_min": settings.qlib_train_icir_floor,
        "require_monotonic": settings.qlib_train_require_monotonic,
        "stride_icir_min": settings.qlib_train_icir_floor,
        "requires_fresh_oos_forward": True,
        "requires_no_data_quality_blockers": True,
        "requires_human_confirmation": True,
    }


def overfit_guard() -> dict[str, Any]:
    return {
        "requires_deflated_sharpe": True,
        "deflated_sharpe_min": 0.95,
        "requires_pbo": True,
        "pbo_max": 0.5,
        "must_report_trial_count": True,
        "trial_count_source": "declared_candidate_family_and_parameter_grid",
        "statistics_modules": [
            "backend.backtest.statistics.deflated_sharpe.deflated_sharpe",
            "backend.backtest.statistics.probability_overfitting.pbo",
        ],
    }


def _base_hypothesis(
    *,
    hypothesis_id: str,
    motivation: str,
    source_m27_clues: list[str],
    candidate_family: str,
    features: list[str],
    segments: list[dict[str, Any]] | None = None,
    sample_scope: dict[str, Any] | None = None,
    stop_conditions: list[str],
    horizons: list[int] | None = None,
    split_override: dict[str, Any] | None = None,
    forbidden_interpretation_suffix: str | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forbidden_interpretation = "not a production candidate and not evidence to restore weight_quant"
    if forbidden_interpretation_suffix:
        forbidden_interpretation = f"{forbidden_interpretation}; {forbidden_interpretation_suffix}"
    split = {
        "train_end_before_oos": True,
        "requires_fresh_oos_forward": True,
        "label_realized_before_target_start": True,
        "requires_non_overlapping_stride_metrics": True,
    }
    if split_override:
        split.update(split_override)
    result = {
        "hypothesis_id": hypothesis_id,
        "status": "preregistered",
        "motivation": motivation,
        "source_m27_clues": source_m27_clues,
        "candidate_family": candidate_family,
        "candidate_type": "shadow_research_candidate",
        "forbidden_interpretation": forbidden_interpretation,
        "sample_scope": sample_scope
        or {
            "universe": "active_or_test3_or_declared_full_universe",
            "min_symbols": 4,
            "min_validation_rows": 50,
            "min_filtered_trades": 50,
        },
        "features": features,
        "segments": segments or [],
        "horizons": horizons or [1, 3, 5, 20],
        "split": split,
        "sample_gates": {
            "min_symbols": 4,
            "min_validation_rows": 50,
            "min_filtered_trades": 50,
            "min_ic_days": 20,
            "min_quantile_buckets": 5,
        },
        "promotion_gate": promotion_gate(),
        "overfit_guard": overfit_guard(),
        "multiple_comparison": {
            "method": "bonferroni_or_explicit_warning_required",
            "n_candidates_declared": 1,
            "must_report_candidate_count": True,
        },
        "stop_conditions": stop_conditions,
        "allowed_next_action": "run read-only validation and append results to the M29 evidence ledger",
        "forbidden_actions": [
            "write_db",
            "call_llm_or_api",
            "change_weight_quant",
            "change_signal_profile",
            "attach_checkpoint",
            "train_model",
            "write_sentiment_cache",
        ],
        "planned_artifacts": [],
    }
    if extra_fields:
        result.update(extra_fields)
    return result


def default_hypotheses() -> list[dict[str, Any]]:
    return [
        _base_hypothesis(
            hypothesis_id="regime_low_vol_alpha_v1",
            motivation=(
                "M27 short-cycle evaluation exposed low-vol regime strength, "
                "but it was not monotonic and must be isolated as a new shadow hypothesis."
            ),
            source_m27_clues=["volatility_regime=low_vol", "m27_label_objective_eval_m27_1d_multi_exit"],
            candidate_family="regime_conditioned_alpha",
            features=["volatility_regime", "volatility_20", "atr_ratio", "sector_rel_strength_20_z"],
            segments=[{"column": "volatility_regime", "values": ["low_vol", "high_vol"]}],
            stop_conditions=[
                "stop if segment quantiles are not monotonic",
                "stop if stride ICIR is below the production floor",
                "stop if a segment only passes because of a tiny symbol count",
            ],
        ),
        _base_hypothesis(
            hypothesis_id="intra_industry_relative_strength_v1",
            motivation=(
                "M27 diagnostics found sector-relative strength among the stronger weak signals; "
                "test it inside industry buckets instead of as a global production factor."
            ),
            source_m27_clues=["sector_rel_strength_20_z", "attach_sector_relative_strength"],
            candidate_family="intra_industry_relative_strength",
            features=["sector_rel_strength_20_z", "industry", "industry_rank_percentile", "momentum_20"],
            segments=[{"column": "industry", "values": ["declared_by_artifact"]}],
            stop_conditions=[
                "stop if industry-neutral validation is weaker than the global baseline",
                "stop if any promoted-looking segment lacks non-overlapping stability",
                "stop if multiple-comparison metadata is missing",
            ],
        ),
        _base_hypothesis(
            hypothesis_id="liquidity_turnover_state_v1",
            motivation=(
                "M27 did not find a promotable raw objective; liquidity and turnover may explain "
                "when existing weak alpha lines are tradable."
            ),
            source_m27_clues=["turnover_anomaly_z", "turnover_proxy_20", "vol_ratio_20", "amihud_20"],
            candidate_family="liquidity_turnover_state",
            features=["turnover_anomaly_z", "turnover_proxy_20", "vol_ratio_20", "amihud_20", "amount"],
            segments=[{"column": "liquidity_state", "values": ["low", "normal", "high"]}],
            stop_conditions=[
                "stop if gains vanish after transaction-cost-aware trade filtering",
                "stop if filtered trades are below the 50-trade sample gate",
                "stop if the state is just a proxy for unavailable or stale volume data",
            ],
        ),
        _base_hypothesis(
            hypothesis_id="post_event_drift_pure_polarity_v1",
            motivation=(
                "M27 lookback=5 pure polarity had positive IC/ICIR after cache closure, "
                "but failed monotonicity; retest only as event-drift shadow research."
            ),
            source_m27_clues=["pure_polarity", "m27_alpha_event_ab_lookback5_after_backfill_20260531_v2"],
            candidate_family="post_event_drift",
            features=["cache_polarity", "event_type", "event_score", "news_age_days", "lookback_days"],
            segments=[{"column": "lookback_days", "values": [1, 5]}],
            sample_scope={
                "universe": "test3_with_closed_sentiment_cache",
                "min_symbols": 4,
                "min_validation_rows": 50,
                "min_filtered_trades": 50,
                "requires_cache_miss_windows": 0,
                "requires_rows_with_fallback_polarity": 0,
            },
            stop_conditions=[
                "stop if cache_miss_windows is not zero",
                "stop if rows_with_fallback_polarity is not zero",
                "stop if top-bottom is positive but quantiles are not monotonic",
            ],
        ),
        _base_hypothesis(
            hypothesis_id="top_decile_entry_timing_v1",
            motivation=(
                "M27 top-decile evidence was positive in some forward windows but sample-limited; "
                "reframe it as entry timing or discrete filtering, not a continuous quant score."
            ),
            source_m27_clues=["raw_20d_top_decile_classifier", "m27_top_decile_forward_shadow"],
            candidate_family="top_decile_entry_timing",
            features=["raw_20d_top_decile_classifier", "target_date_rank", "entry_threshold_context"],
            sample_scope={
                "universe": "test3_or_declared_forward_shadow_universe",
                "min_symbols": 4,
                "min_validation_rows": 50,
                "min_filtered_trades": 50,
                "min_positive_rolling_windows": 2,
            },
            stop_conditions=[
                "stop if filtered trades are below 50 for the evaluated horizon",
                "stop if rolling positive windows do not persist after new price data",
                "stop if it is presented as a continuous production quant score",
            ],
        ),
        _base_hypothesis(
            hypothesis_id="m58_stop_loss_momentum_tail_v1",
            motivation=(
                "M58 decision-formula rebuild diagnostic (2026-07-03): the momentum score "
                "(0.6x5-day return + 0.4x20-day return, the current placeholder_v0 formula) "
                "identifies weak stocks accurately but poorly discriminates strong stocks, so it "
                "is naturally suited to a stop-loss/risk-control functional slot rather than a "
                "stock-selection one. Same-day diagnostics show the bottom-20% cross-sectional "
                "momentum bucket had a mean 5-day net return of -2.05pp, but that number is from a "
                "single in-window computation and is not a cross-regime result; it must clear a "
                "4-6 week forward shadow window before any adjudication."
            ),
            source_m27_clues=[
                "m58_2026-07-03_diagnosis_momentum_placeholder_v0_bottom20_5d_mean_return_-2.05pp_single_window_in_window",
                "m58_current_production_composite_0.6_technical_0.4_headline_sentiment_7week_icir_approx_-0.03_no_discrimination",
            ],
            candidate_family="m58_functional_slot_stop_loss_momentum_tail",
            features=[
                "momentum_score_placeholder_v0",
                "momentum_5d",
                "momentum_20d",
                "cross_sectional_percentile_rank_bottom20",
            ],
            segments=[{"column": "regime_label", "values": ["declared_by_forward_window"]}],
            sample_scope={
                "universe": "active_or_test3_or_declared_full_universe",
                "min_symbols": 4,
                "min_validation_rows": 50,
                "min_filtered_trades": 50,
                "requires_multiple_regimes_covered": True,
                "forward_shadow_weeks_min": 4,
                "forward_shadow_weeks_max": 6,
            },
            horizons=[5],
            stop_conditions=[
                "stop if single-window/single-regime evidence (-2.05pp) is treated as sufficient; "
                "requires cross-regime forward confirmation before adjudication",
                "stop if bottom-20% underperformance disappears or reverses in any covered regime",
                "stop if it is used to trigger an automatic sell/exit instruction rather than a "
                "postmarket panel risk warning",
                "stop if the forward shadow window is below 4 weeks or fewer than 2 distinct "
                "regimes are observed",
            ],
            forbidden_interpretation_suffix=(
                "must not be used as an automated sell/exit instruction; observe-only postmarket "
                "panel risk warning pending cross-regime forward confirmation"
            ),
            extra_fields={
                "functional_slot": "stop_loss_risk_control",
                "validation_mode": "forward_shadow_4_to_6_weeks_cross_regime",
                "requires_cross_regime_adjudication": True,
                "intended_use": "postmarket_panel_risk_warning_only_not_a_sell_instruction",
                "trial_count_ledger": {
                    "declared_at_registration": 1,
                    "note": (
                        "first declared trial for this functional-slot hypothesis; increment "
                        "honestly if additional momentum-tail parameterizations are tested before "
                        "adjudication"
                    ),
                },
            },
        ),
        _base_hypothesis(
            hypothesis_id="m58_stock_selection_technical_head_v1",
            motivation=(
                "M58 decision-formula rebuild diagnostic (2026-07-03): the top-20% cross-sectional "
                "technical-score bucket showed a higher mean 5-day net return than the pool average "
                "(+0.96pp same-day diagnostic), but the edge is weak and drawn from a single "
                "in-window computation and needs forward confirmation. Once M54 news-layer v2 "
                "body-text-triggered signals clear their own adjudication (IC-days > 20), they will "
                "be folded in as an enhancement into version 2 of this hypothesis; this registration "
                "covers only the price-only technical-head signal itself."
            ),
            source_m27_clues=[
                "m58_2026-07-03_diagnosis_technical_score_top20_5d_mean_return_+0.96pp_weak_single_window_in_window",
                "m54_v2_headline_body_news_trigger_pending_own_adjudication_to_be_merged_as_enhancement_v2",
            ],
            candidate_family="m58_functional_slot_stock_selection_technical_head",
            features=[
                "technical_score",
                "cross_sectional_percentile_rank_top20",
                "momentum_5d",
                "momentum_20d",
            ],
            segments=[{"column": "regime_label", "values": ["declared_by_forward_window"]}],
            sample_scope={
                "universe": "active_or_test3_or_declared_full_universe",
                "min_symbols": 4,
                "min_validation_rows": 50,
                "min_filtered_trades": 50,
                "requires_multiple_regimes_covered": True,
                "forward_shadow_weeks_min": 4,
                "forward_shadow_weeks_max": 6,
            },
            horizons=[5],
            stop_conditions=[
                "stop if the single-window +0.96pp edge is treated as confirmed without "
                "cross-regime forward replication",
                "stop if top-20% outperformance disappears or reverses in any covered regime",
                "stop if the M54 v2 news-trigger enhancement is merged before M54 itself completes "
                "its own IC-days > 20 adjudication",
                "stop if the forward shadow window is below 4 weeks or fewer than 2 distinct "
                "regimes are observed",
            ],
            forbidden_interpretation_suffix=(
                "must not be presented as a confirmed buy signal before cross-regime forward "
                "confirmation; the M54 v2 news enhancement must not be merged ahead of its own "
                "adjudication"
            ),
            extra_fields={
                "functional_slot": "stock_selection",
                "validation_mode": "forward_shadow_4_to_6_weeks_cross_regime",
                "requires_cross_regime_adjudication": True,
                "planned_v2_enhancement": "m54_v2_news_trigger_pending_its_own_adjudication_not_yet_merged",
                "trial_count_ledger": {
                    "declared_at_registration": 1,
                    "note": (
                        "first declared trial for this functional-slot hypothesis (v1, price-only "
                        "technical head); a v2 with the M54 news enhancement will be a separate "
                        "declared trial after M54 completes its own adjudication"
                    ),
                },
            },
        ),
        _base_hypothesis(
            hypothesis_id="m58_exit_trailing_atr_sweep_v1",
            motivation=(
                "M58 decision-formula rebuild, Phase 1: the M21.4 post-mortem falsified the "
                "'initial stop too tight' hypothesis (the v1 initial ATR stop at x2.0 was never "
                "triggered; losses came from gap slippage, not initial stop width), so the exit "
                "question narrows to trailing-ATR-multiple sensitivity and the gap-slippage cost "
                "distribution. This hypothesis searches the x2.0-x3.5 trailing-multiple range for a "
                "point that beats the current x2.5 baseline on net-return/max-drawdown ratio (with "
                "a ~20% drawdown constraint); gap-slippage cost must be accounted for and reported "
                "separately from the stop-width effect."
            ),
            source_m27_clues=[
                "m21_4_verdict_initial_stop_too_tight_falsified_gap_slippage_is_the_real_cost_driver",
                "exit_sweep_backtrader_eval_1490_day_large_sample_with_holdout_m21_4_adjudicated_channel",
            ],
            candidate_family="m58_functional_slot_exit_trailing_atr_parameter_grid",
            features=[
                "trailing_atr_multiple",
                "gap_slippage_cost",
                "max_drawdown",
                "net_return_to_drawdown_ratio",
            ],
            segments=[{"column": "trailing_atr_multiple", "values": ["2.0", "2.5", "3.0", "3.5"]}],
            sample_scope={
                "universe": "exit_sweep_backtrader_eval_1490_day_channel_with_holdout",
                "min_symbols": 4,
                "min_validation_rows": 50,
                "min_filtered_trades": 50,
                "drawdown_constraint_max": 0.20,
                "requires_gap_slippage_accounted_separately": True,
            },
            split_override={
                "requires_fresh_oos_forward": False,
                "validation_basis": "historical_large_sample_with_holdout_non_forward",
                "holdout_required": True,
            },
            stop_conditions=[
                "stop if a trailing multiple only wins because of a drawdown-constraint breach or a "
                "thin trade sample (below the 50-filtered-trade gate)",
                "stop if the net-return/drawdown improvement vanishes once gap-slippage cost is "
                "accounted for",
                "stop if the ~20% drawdown constraint is breached by the candidate multiple",
                "stop if it is switched into production before user confirmation and before the "
                "standard promotion_gate fresh forward OOS check required for any production switch",
            ],
            forbidden_interpretation_suffix=(
                "this is a historical large-sample backtest-with-holdout result (M21.4-adjudicated "
                "channel), not a forward validation result, and it still requires the standard "
                "promotion_gate fresh forward OOS check before any production switch"
            ),
            extra_fields={
                "functional_slot": "exit_take_profit_trailing_stop",
                "validation_mode": "historical_large_sample_with_holdout_non_forward",
                "requires_cross_regime_adjudication": True,
                "validation_channel": (
                    "exit_sweep_backtrader_eval_1490_day_incl_holdout_m21_4_adjudicated_channel"
                ),
                "gap_slippage_accounting": "must_be_recorded_and_reported_separately_from_stop_width_effect",
                "trial_count_ledger": {
                    "declared_at_registration": 1,
                    "note": (
                        "first declared trial in the x2.0-x3.5 trailing-ATR grid; each additional "
                        "grid point evaluated (e.g. 2.0/2.5/3.0/3.5) must be counted and reported "
                        "honestly before any promotion decision, per the M51 D1 statistics contract"
                    ),
                },
            },
        ),
    ]


def validate_registry(report: dict[str, Any], *, strict: bool = True) -> list[str]:
    errors: list[str] = []
    for flag in ("writes_db", "calls_llm_or_api", "saves_model"):
        if report.get(flag) is not False:
            errors.append(f"{flag} must be false")
    if report.get("production_unchanged") is not True:
        errors.append("production_unchanged must be true")

    seen: set[str] = set()
    for idx, hypothesis in enumerate(report.get("hypotheses") or []):
        hid = hypothesis.get("hypothesis_id") or f"index_{idx}"
        if hid in seen:
            errors.append(f"duplicate hypothesis_id: {hid}")
        seen.add(hid)
        missing = sorted(REQUIRED_HYPOTHESIS_FIELDS - set(hypothesis))
        if missing:
            errors.append(f"{hid} missing required fields: {', '.join(missing)}")
            if strict:
                continue
        if hypothesis.get("candidate_type") != "shadow_research_candidate":
            errors.append(f"{hid} must remain shadow_research_candidate")
        if hypothesis.get("forbidden_interpretation", "").find("not a production candidate") < 0:
            errors.append(f"{hid} must forbid production interpretation")
        if not hypothesis.get("stop_conditions"):
            errors.append(f"{hid} must define stop_conditions")
        if not hypothesis.get("sample_gates"):
            errors.append(f"{hid} must define sample_gates")
        if not hypothesis.get("multiple_comparison"):
            errors.append(f"{hid} must define multiple_comparison")
        if not hypothesis.get("overfit_guard"):
            errors.append(f"{hid} must define overfit_guard")
        gate = hypothesis.get("promotion_gate") or {}
        expected_gate: dict[str, Any] = {
            "ic_min": settings.qlib_train_ic_floor,
            "icir_min": settings.qlib_train_icir_floor,
            "require_monotonic": settings.qlib_train_require_monotonic,
            "stride_icir_min": settings.qlib_train_icir_floor,
            "requires_fresh_oos_forward": True,
            "requires_no_data_quality_blockers": True,
            "requires_human_confirmation": True,
        }
        for key, expected in expected_gate.items():
            if gate.get(key) != expected:
                errors.append(f"{hid} promotion_gate.{key} must be {expected!r}")
        guard = hypothesis.get("overfit_guard") or {}
        expected_guard: dict[str, Any] = {
            "requires_deflated_sharpe": True,
            "deflated_sharpe_min": 0.95,
            "requires_pbo": True,
            "pbo_max": 0.5,
            "must_report_trial_count": True,
            "trial_count_source": "declared_candidate_family_and_parameter_grid",
        }
        for key, expected in expected_guard.items():
            if guard.get(key) != expected:
                errors.append(f"{hid} overfit_guard.{key} must be {expected!r}")
        source_text = " ".join(hypothesis.get("source_m27_clues") or [])
        if any(source in source_text for source in FORBIDDEN_PRODUCTION_SOURCES):
            if hypothesis.get("candidate_type") != "shadow_research_candidate":
                errors.append(f"{hid} wraps an M27 source but is not shadow-only")
    if not report.get("hypotheses"):
        errors.append("at least one hypothesis is required")
    return errors


def build_registry(*, as_of_date: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "as_of_date": as_of_date,
        "schema_version": "m29_hypothesis_registry.v1",
        "milestone": "M29.2",
        "purpose": "pre-registered alpha hypotheses before experiment execution",
        "run_mode": "read_only_hypothesis_registry",
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "hypotheses": default_hypotheses(),
        "stop_conditions": [
            "stop before writing DB or sentiment_cache",
            "stop before calling LLM/API services",
            "stop before changing weight_quant, signal profile, or checkpoint wiring",
            "stop before training or saving a model",
        ],
    }
    errors = validate_registry(report)
    report["validation"] = {"passed": not errors, "errors": errors}
    return report


def report_to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M29 Hypothesis Registry",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- schema_version: {report['schema_version']}",
        f"- hypotheses: {len(report['hypotheses'])}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- validation_passed: {report['validation']['passed']}",
        "",
        "## Hypotheses",
        "",
    ]
    for hypothesis in report["hypotheses"]:
        lines.extend([
            f"### {hypothesis['hypothesis_id']}",
            "",
            f"- candidate_family: {hypothesis['candidate_family']}",
            f"- candidate_type: {hypothesis['candidate_type']}",
            f"- horizons: {', '.join(str(item) for item in hypothesis['horizons'])}",
            f"- features: {', '.join(hypothesis['features'])}",
            "- stop_conditions:",
        ])
        lines.extend(f"  - {item}" for item in hypothesis["stop_conditions"])
        lines.extend(["", "- promotion_gate:"])
        gate = hypothesis["promotion_gate"]
        lines.extend([
            f"  - ic_min: {gate['ic_min']}",
            f"  - icir_min: {gate['icir_min']}",
            f"  - require_monotonic: {gate['require_monotonic']}",
            "",
            "- overfit_guard:",
        ])
        guard = hypothesis["overfit_guard"]
        lines.extend([
            f"  - deflated_sharpe_min: {guard['deflated_sharpe_min']}",
            f"  - pbo_max: {guard['pbo_max']}",
            f"  - must_report_trial_count: {guard['must_report_trial_count']}",
            "",
        ])
    lines.extend(["## Global Stop Conditions", ""])
    lines.extend(f"- {item}" for item in report["stop_conditions"])
    lines.append("")
    return "\n".join(lines)


def _load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("registry input must be a JSON object")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Validate an existing registry JSON instead of building defaults")
    parser.add_argument("--validate-only", action="store_true", help="Validate and skip output writes")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--as-of-date", help="Optional YYYY-MM-DD date to stamp into the default registry")
    parser.add_argument("--strict", action="store_true", help="Fail if required fields are missing")
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = _load_report(args.input) if args.input else build_registry(as_of_date=args.as_of_date)
    errors = validate_registry(report, strict=args.strict)
    report["validation"] = {"passed": not errors, "errors": errors}
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        return 2
    if not args.validate_only:
        args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        args.markdown_output.expanduser().write_text(report_to_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
