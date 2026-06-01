"""Build a read-only M29 alpha hypothesis registry.

The registry pre-registers research hypotheses before another experiment is
run. It writes only JSON/Markdown artifacts and never opens the StockSage DB,
calls LLM/API services, saves models, or changes production configuration.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings

DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m29_hypothesis_registry.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m29_hypothesis_registry.md"
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
) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis_id,
        "status": "preregistered",
        "motivation": motivation,
        "source_m27_clues": source_m27_clues,
        "candidate_family": candidate_family,
        "candidate_type": "shadow_research_candidate",
        "forbidden_interpretation": "not a production candidate and not evidence to restore weight_quant",
        "sample_scope": sample_scope
        or {
            "universe": "active_or_test3_or_declared_full_universe",
            "min_symbols": 4,
            "min_validation_rows": 50,
            "min_filtered_trades": 50,
        },
        "features": features,
        "segments": segments or [],
        "horizons": [1, 3, 5, 20],
        "split": {
            "train_end_before_oos": True,
            "requires_fresh_oos_forward": True,
            "label_realized_before_target_start": True,
            "requires_non_overlapping_stride_metrics": True,
        },
        "sample_gates": {
            "min_symbols": 4,
            "min_validation_rows": 50,
            "min_filtered_trades": 50,
            "min_ic_days": 20,
            "min_quantile_buckets": 5,
        },
        "promotion_gate": promotion_gate(),
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
        gate = hypothesis.get("promotion_gate") or {}
        expected_gate = {
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
        source_text = " ".join(hypothesis.get("source_m27_clues") or [])
        if any(source in source_text for source in FORBIDDEN_PRODUCTION_SOURCES):
            if hypothesis.get("candidate_type") != "shadow_research_candidate":
                errors.append(f"{hid} wraps an M27 source but is not shadow-only")
    if not report.get("hypotheses"):
        errors.append("at least one hypothesis is required")
    return errors


def build_registry(*, as_of_date: str | None = None) -> dict[str, Any]:
    report = {
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
