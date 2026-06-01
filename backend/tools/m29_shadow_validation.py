"""Wrap pre-registered M29 hypotheses in read-only shadow validation.

Supported hypotheses read existing M27/M29 artifacts, check them against the
M29 registry sample gates, and emit non-promoting M29 artifacts that can be
added to the evidence ledger. The wrapper never writes the DB, calls LLM/API
services, saves a model, trains a model, or changes production configuration.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.tools.m29_hypothesis_registry import default_hypotheses

TOP_DECILE_HYPOTHESIS_ID = "top_decile_entry_timing_v1"
POST_EVENT_HYPOTHESIS_ID = "post_event_drift_pure_polarity_v1"
DEFAULT_HYPOTHESIS_ID = TOP_DECILE_HYPOTHESIS_ID
DEFAULT_SOURCE_ARTIFACTS = {
    TOP_DECILE_HYPOTHESIS_ID: Path("/private/tmp/m27_forward_shadow_rolling_20260401_20260529_1d.json"),
    POST_EVENT_HYPOTHESIS_ID: Path("/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.json"),
}
DEFAULT_JSON_OUTPUTS = {
    TOP_DECILE_HYPOTHESIS_ID: Path("/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.json"),
    POST_EVENT_HYPOTHESIS_ID: Path("/private/tmp/m29_shadow_validation_post_event_drift_pure_polarity_v1.json"),
}
DEFAULT_MARKDOWN_OUTPUTS = {
    TOP_DECILE_HYPOTHESIS_ID: Path("/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.md"),
    POST_EVENT_HYPOTHESIS_ID: Path("/private/tmp/m29_shadow_validation_post_event_drift_pure_polarity_v1.md"),
}
DEFAULT_SOURCE_ARTIFACT = DEFAULT_SOURCE_ARTIFACTS[DEFAULT_HYPOTHESIS_ID]
DEFAULT_JSON_OUTPUT = DEFAULT_JSON_OUTPUTS[DEFAULT_HYPOTHESIS_ID]
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_MARKDOWN_OUTPUTS[DEFAULT_HYPOTHESIS_ID]
SUPPORTED_HYPOTHESES = set(DEFAULT_SOURCE_ARTIFACTS)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return payload


def _hypothesis_by_id(hypothesis_id: str) -> dict[str, Any]:
    for hypothesis in default_hypotheses():
        if hypothesis.get("hypothesis_id") == hypothesis_id:
            return hypothesis
    raise ValueError(f"unknown M29 hypothesis_id: {hypothesis_id}")


def _source_read_only_blockers(source: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if source.get("production_unchanged") is not True:
        blockers.append("source_artifact_production_not_proven_unchanged")
    for flag in ("writes_db", "calls_llm_or_api", "saves_model"):
        if source.get(flag) is not False:
            blockers.append(f"source_artifact_{flag}_not_false")
    return blockers


def _source_provenance_blockers(source: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field in ("data_source", "fetched_at", "adjustment", "universe_hash", "train_label_realized_end"):
        if source.get(field) in (None, ""):
            blockers.append(f"missing_source_{field}")
    return blockers


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _top_decile_candidate_summary(source: dict[str, Any], hypothesis: dict[str, Any]) -> dict[str, Any]:
    sample = source.get("sample_adequacy") or {}
    aggregate = source.get("aggregate_profile_summary") or {}
    rolling = source.get("rolling") or {}
    min_filtered_trades = int((hypothesis.get("sample_scope") or {}).get("min_filtered_trades") or 50)
    min_positive_windows = int((hypothesis.get("sample_scope") or {}).get("min_positive_rolling_windows") or 2)
    filtered_trades = int(sample.get("filtered_trades") or aggregate.get("filtered_trades_total") or 0)
    positive_windows = int(aggregate.get("positive_avg_net_return_delta_windows") or 0)
    window_count = int(rolling.get("window_count") or 0)
    best_candidate = {
        "name": "top_decile_entry_timing_1d_rolling",
        "segment_col": None,
        "segment": "1d_rolling",
        "status": "ok" if source.get("run_mode") == "offline_read_only_forward_shadow_rolling" else "invalid_source",
        "sample": {
            "baseline_trades": sample.get("baseline_trades") or aggregate.get("baseline_trades_total"),
            "filtered_trades": filtered_trades,
            "min_filtered_trades": min_filtered_trades,
            "positive_windows": positive_windows,
            "min_positive_windows": min_positive_windows,
            "window_count": window_count,
            "windows_with_filtered_trades": rolling.get("windows_with_filtered_trades"),
        },
        "raw_ic": None,
        "raw_icir": None,
        "raw_ic_days": None,
        "raw_top_bottom": aggregate.get("trade_weighted_avg_net_return_delta"),
        "raw_gate_pass": None,
        "raw_pass_ic": None,
        "raw_pass_icir": None,
        "raw_pass_monotonic": None,
        "stride_ic": None,
        "stride_icir": None,
        "stride_ic_days": None,
        "stride_gate_pass": None,
        "top_decile_lift": None,
        "top_decile_precision": None,
    }
    return {
        "candidate_count": 1,
        "best_candidate": best_candidate,
        "candidates": [best_candidate],
        "sample_gate": {
            "min_filtered_trades": min_filtered_trades,
            "filtered_trades": filtered_trades,
            "passes_min_filtered_trades": filtered_trades >= min_filtered_trades,
            "min_positive_rolling_windows": min_positive_windows,
            "positive_rolling_windows": positive_windows,
            "passes_positive_rolling_windows": positive_windows >= min_positive_windows,
        },
    }


def _top_decile_validation_decision(source: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    sample_gate = summary.get("sample_gate") or {}
    blockers = []
    if source.get("run_mode") != "offline_read_only_forward_shadow_rolling":
        blockers.append("source_not_rolling_forward_shadow")
    if int(source.get("exit_days") or 0) != 1:
        blockers.append("source_exit_days_not_1")
    if sample_gate.get("passes_min_filtered_trades") is not True:
        blockers.append("filtered_trades_below_sample_gate")
    if sample_gate.get("passes_positive_rolling_windows") is not True:
        blockers.append("positive_rolling_windows_below_sample_gate")
    blockers.extend(_source_read_only_blockers(source))
    blockers.extend(_source_provenance_blockers(source))
    blockers.extend([
        "post_registration_fresh_forward_missing",
        "not_continuous_quant_score",
        "shadow_validation_non_promoting",
    ])
    sample_gate_pass = not any(
        blocker
        in {
            "source_not_rolling_forward_shadow",
            "source_exit_days_not_1",
            "filtered_trades_below_sample_gate",
            "positive_rolling_windows_below_sample_gate",
        }
        for blocker in blockers
    )
    return {
        "decision": (
            "sample_gate_passed_keep_collecting_fresh_forward"
            if sample_gate_pass
            else "non_promoting_keep_collecting_evidence"
        ),
        "gate_pass": False,
        "sample_gate_pass": sample_gate_pass,
        "raw_stride_gate_pass": False,
        "promotable": False,
        "non_promoting": True,
        "blockers": list(dict.fromkeys(blockers)),
        "recommended_next_action": "rerun 1d rolling shadow after new price data and append to ledger",
    }


def _event_candidate(
    *,
    name: str,
    segment: str,
    metrics: dict[str, Any],
    validation: dict[str, Any],
    coverage: dict[str, Any],
    sample: dict[str, Any],
    sample_scope: dict[str, Any],
) -> dict[str, Any]:
    min_symbols = int(sample_scope.get("min_symbols") or 4)
    min_validation_rows = int(sample_scope.get("min_validation_rows") or 50)
    return {
        "name": name,
        "segment_col": "lookback_days",
        "segment": segment,
        "status": "ok",
        "sample": {
            "n_rows": sample.get("n_rows"),
            "n_symbols": coverage.get("universe_symbols") or sample.get("n_symbols"),
            "validation_rows": coverage.get("rows_with_polarity"),
            "min_symbols": min_symbols,
            "min_validation_rows": min_validation_rows,
            "rows_with_news": coverage.get("rows_with_news"),
            "rows_with_cache_polarity": coverage.get("rows_with_cache_polarity"),
            "rows_with_fallback_polarity": coverage.get("rows_with_fallback_polarity"),
            "cache_miss_windows": coverage.get("cache_miss_windows"),
            "lookback_days": coverage.get("lookback_days"),
            "rows_with_event_override": coverage.get("rows_with_event_override"),
            "event_type_hits": coverage.get("event_type_hits"),
        },
        "raw_ic": metrics.get("ic_mean"),
        "raw_icir": metrics.get("icir"),
        "raw_ic_days": metrics.get("ic_days"),
        "raw_top_bottom": validation.get("top_bottom_oriented"),
        "raw_gate_pass": validation.get("passes_event_ab_gate"),
        "raw_pass_ic": validation.get("passes_ic_floor"),
        "raw_pass_icir": validation.get("passes_icir_floor"),
        "raw_pass_monotonic": validation.get("monotonic_oriented"),
        "raw_pass_quantile_monotonic_gate": validation.get("passes_quantile_monotonic_gate"),
        "stride_ic": None,
        "stride_icir": None,
        "stride_ic_days": None,
        "stride_gate_pass": None,
        "top_decile_lift": None,
        "top_decile_precision": None,
    }


def _event_candidate_summary(source: dict[str, Any], hypothesis: dict[str, Any]) -> dict[str, Any]:
    event_ab = source.get("event_ab_5d") or {}
    sample = source.get("sample") or {}
    coverage = event_ab.get("coverage") or {}
    sample_scope = hypothesis.get("sample_scope") or {}
    min_symbols = int(sample_scope.get("min_symbols") or 4)
    min_validation_rows = int(sample_scope.get("min_validation_rows") or 50)
    required_cache_miss_windows = int(sample_scope.get("requires_cache_miss_windows") or 0)
    required_fallback_rows = int(sample_scope.get("requires_rows_with_fallback_polarity") or 0)
    universe_symbols = _as_int(coverage.get("universe_symbols") or sample.get("n_symbols"))
    validation_rows = _as_int(coverage.get("rows_with_polarity"))
    cache_miss_windows = _as_int(coverage.get("cache_miss_windows"))
    fallback_rows = _as_int(coverage.get("rows_with_fallback_polarity"))
    candidates = [
        _event_candidate(
            name="pure_polarity_lookback5",
            segment="pure_polarity",
            metrics=event_ab.get("polarity") or {},
            validation=event_ab.get("pure_polarity_validation") or {},
            coverage=coverage,
            sample=sample,
            sample_scope=sample_scope,
        ),
        _event_candidate(
            name="polarity_plus_event_lookback5",
            segment="polarity_plus_event",
            metrics=event_ab.get("polarity_event") or {},
            validation=event_ab.get("polarity_event_validation") or {},
            coverage=coverage,
            sample=sample,
            sample_scope=sample_scope,
        ),
    ]
    best_candidate = max(
        candidates,
        key=lambda candidate: (
            candidate.get("raw_icir") if isinstance(candidate.get("raw_icir"), (int, float)) else float("-inf"),
            candidate.get("raw_ic") if isinstance(candidate.get("raw_ic"), (int, float)) else float("-inf"),
        ),
    )
    return {
        "candidate_count": len(candidates),
        "best_candidate": best_candidate,
        "candidates": candidates,
        "sample_gate": {
            "min_symbols": min_symbols,
            "universe_symbols": universe_symbols,
            "passes_min_symbols": universe_symbols >= min_symbols,
            "min_validation_rows": min_validation_rows,
            "validation_rows": validation_rows,
            "passes_min_validation_rows": validation_rows >= min_validation_rows,
            "requires_cache_miss_windows": required_cache_miss_windows,
            "cache_miss_windows": cache_miss_windows,
            "passes_cache_miss_windows": cache_miss_windows == required_cache_miss_windows,
            "requires_rows_with_fallback_polarity": required_fallback_rows,
            "rows_with_fallback_polarity": fallback_rows,
            "passes_rows_with_fallback_polarity": fallback_rows == required_fallback_rows,
        },
    }


def _event_validation_decision(source: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    event_ab = source.get("event_ab_5d") or {}
    sample_gate = summary.get("sample_gate") or {}
    blockers = []
    if not event_ab:
        blockers.append("source_not_event_ab_5d")
    if sample_gate.get("passes_min_symbols") is not True:
        blockers.append("symbols_below_sample_gate")
    if sample_gate.get("passes_min_validation_rows") is not True:
        blockers.append("validation_rows_below_sample_gate")
    if sample_gate.get("passes_cache_miss_windows") is not True:
        blockers.append("cache_miss_windows_not_zero")
    if sample_gate.get("passes_rows_with_fallback_polarity") is not True:
        blockers.append("rows_with_fallback_polarity_not_zero")

    pure_validation = event_ab.get("pure_polarity_validation") or {}
    event_validation = event_ab.get("polarity_event_validation") or {}
    if pure_validation.get("monotonic_oriented") is False:
        blockers.append("pure_polarity_not_monotonic")
    if event_validation.get("monotonic_oriented") is False:
        blockers.append("polarity_event_not_monotonic")
    for blocker in pure_validation.get("data_quality_blockers") or []:
        blockers.append(blocker)
    for blocker in event_validation.get("data_quality_blockers") or []:
        blockers.append(blocker)

    blockers.extend(_source_read_only_blockers(source))
    blockers.extend(_source_provenance_blockers(source))
    blockers.extend([
        "post_registration_fresh_forward_missing",
        "event_ab_shadow_validation_non_promoting",
        "shadow_validation_non_promoting",
    ])
    sample_gate_pass = not any(
        blocker
        in {
            "source_not_event_ab_5d",
            "symbols_below_sample_gate",
            "validation_rows_below_sample_gate",
            "cache_miss_windows_not_zero",
            "rows_with_fallback_polarity_not_zero",
        }
        for blocker in blockers
    )
    return {
        "decision": (
            "sample_gate_passed_but_gate_failed_keep_collecting_fresh_forward"
            if sample_gate_pass
            else "non_promoting_keep_collecting_evidence"
        ),
        "gate_pass": False,
        "sample_gate_pass": sample_gate_pass,
        "raw_stride_gate_pass": False,
        "promotable": False,
        "non_promoting": True,
        "blockers": list(dict.fromkeys(blockers)),
        "recommended_next_action": (
            "rerun read-only pure-polarity/event validation after a fresh "
            "post-registration forward window with cache/fallback closed"
        ),
    }


def build_report(
    source_artifact: Path,
    *,
    hypothesis_id: str = DEFAULT_HYPOTHESIS_ID,
) -> dict[str, Any]:
    if hypothesis_id not in SUPPORTED_HYPOTHESES:
        raise ValueError(f"unsupported hypothesis_id for shadow validation: {hypothesis_id}")
    source_path = source_artifact.expanduser()
    source = _load_json(source_path)
    hypothesis = _hypothesis_by_id(hypothesis_id)
    if hypothesis_id == POST_EVENT_HYPOTHESIS_ID:
        summary = _event_candidate_summary(source, hypothesis)
        validation = _event_validation_decision(source, summary)
        event_ab = source.get("event_ab_5d") or {}
        event_gate = event_ab.get("event_ab_gate") or {}
        sample = source.get("sample") or {}
        start = source.get("start") or sample.get("start")
        end = source.get("end") or sample.get("end")
        panel = sample
        horizon = source.get("horizon") or 5
        exit_days = source.get("exit_days")
        multiple_comparison = {
            "method": "pre_registered_two_variant_shadow_check",
            "n_candidates_tested": 2,
            "warning": event_gate.get("multiple_comparison_warning"),
        }
        artifact_kind = "event_ab_v2_gate"
    else:
        summary = _top_decile_candidate_summary(source, hypothesis)
        validation = _top_decile_validation_decision(source, summary)
        start = source.get("start")
        end = source.get("end")
        panel = source.get("panel") or {}
        horizon = source.get("horizon")
        exit_days = source.get("exit_days")
        multiple_comparison = {
            "method": "pre_registered_single_candidate",
            "n_candidates_tested": 1,
            "warning": None,
        }
        artifact_kind = "top_decile_forward_shadow_rolling"
    provenance_blockers = _source_provenance_blockers(source)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": "m29_shadow_validation.v1",
        "milestone": "M29.2/M29.3",
        "purpose": "read-only shadow validation for a pre-registered M29 alpha hypothesis",
        "run_mode": "read_only_shadow_validation",
        "hypothesis_id": hypothesis_id,
        "candidate_family": hypothesis.get("candidate_family"),
        "candidate_type": "shadow_research_candidate",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "model_promotion": "disabled",
        "signal_profile_unchanged": True,
        "data_source": source.get("data_source"),
        "fetched_at": source.get("fetched_at"),
        "adjustment": source.get("adjustment"),
        "universe_hash": source.get("universe_hash"),
        "train_label_realized_end": source.get("train_label_realized_end"),
        "source_artifacts": [{
            "path": str(source_path),
            "artifact_kind": artifact_kind,
            "run_mode": source.get("run_mode"),
            "start": start,
            "end": end,
            "exit_days": exit_days,
        }],
        "start": start,
        "end": end,
        "horizon": horizon,
        "exit_days": exit_days,
        "panel": panel,
        "hypothesis": hypothesis,
        "sample_gates": hypothesis.get("sample_gates") or {},
        "promotion_gate": hypothesis.get("promotion_gate"),
        "multiple_comparison": multiple_comparison,
        "candidate_summary": summary,
        "shadow_validation": validation,
        "data_quality_blockers": provenance_blockers,
        "blockers": validation["blockers"],
        "decision": {
            "decision": validation["decision"],
            "recommended_next_action": validation["recommended_next_action"],
            "production_unchanged": True,
            "promotable": False,
        },
        "stop_conditions": hypothesis.get("stop_conditions"),
        "forbidden_actions": hypothesis.get("forbidden_actions"),
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    source = (report.get("source_artifacts") or [{}])[0]
    summary = report.get("candidate_summary") or {}
    sample_gate = summary.get("sample_gate") or {}
    best = summary.get("best_candidate") or {}
    validation = report.get("shadow_validation") or {}
    lines = [
        "# M29 Shadow Validation",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- hypothesis_id: {report['hypothesis_id']}",
        f"- candidate_family: {report['candidate_family']}",
        f"- source: {source.get('path')}",
        f"- source_window: {source.get('start')} ~ {source.get('end')}",
        f"- exit_days: {report.get('exit_days')}",
        f"- run_mode: {report['run_mode']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- saves_model: {report['saves_model']}",
        f"- decision: {report['decision']['decision']}",
        f"- recommended_next_action: {report['decision']['recommended_next_action']}",
        "",
        "## Sample Gate",
        "",
        f"- filtered_trades: {sample_gate.get('filtered_trades')}",
        f"- min_filtered_trades: {sample_gate.get('min_filtered_trades')}",
        f"- passes_min_filtered_trades: {sample_gate.get('passes_min_filtered_trades')}",
        f"- positive_rolling_windows: {sample_gate.get('positive_rolling_windows')}",
        f"- min_positive_rolling_windows: {sample_gate.get('min_positive_rolling_windows')}",
        f"- passes_positive_rolling_windows: {sample_gate.get('passes_positive_rolling_windows')}",
        f"- universe_symbols: {sample_gate.get('universe_symbols')}",
        f"- min_symbols: {sample_gate.get('min_symbols')}",
        f"- passes_min_symbols: {sample_gate.get('passes_min_symbols')}",
        f"- validation_rows: {sample_gate.get('validation_rows')}",
        f"- min_validation_rows: {sample_gate.get('min_validation_rows')}",
        f"- passes_min_validation_rows: {sample_gate.get('passes_min_validation_rows')}",
        f"- cache_miss_windows: {sample_gate.get('cache_miss_windows')}",
        f"- rows_with_fallback_polarity: {sample_gate.get('rows_with_fallback_polarity')}",
        f"- trade_weighted_avg_net_return_delta: {best.get('raw_top_bottom')}",
        f"- raw_ic: {best.get('raw_ic')}",
        f"- raw_icir: {best.get('raw_icir')}",
        f"- raw_ic_days: {best.get('raw_ic_days')}",
        f"- raw_pass_monotonic: {best.get('raw_pass_monotonic')}",
        f"- gate_pass: {validation.get('gate_pass')}",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {blocker}" for blocker in report.get("blockers") or [])
    lines.extend(["", "## Forbidden Actions", ""])
    lines.extend(f"- {item}" for item in report.get("forbidden_actions") or [])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hypothesis-id", default=DEFAULT_HYPOTHESIS_ID, choices=sorted(SUPPORTED_HYPOTHESES))
    parser.add_argument("--source-artifact", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_artifact = args.source_artifact or DEFAULT_SOURCE_ARTIFACTS[args.hypothesis_id]
    json_output = args.json_output or DEFAULT_JSON_OUTPUTS[args.hypothesis_id]
    markdown_output = args.markdown_output or DEFAULT_MARKDOWN_OUTPUTS[args.hypothesis_id]
    report = build_report(source_artifact, hypothesis_id=args.hypothesis_id)
    json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    markdown_output.expanduser().write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    print(f"JSON report: {json_output.expanduser()}")
    print(f"Markdown report: {markdown_output.expanduser()}")
    print(f"Decision: {report['decision']['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
