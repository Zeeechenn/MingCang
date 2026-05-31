"""Wrap one pre-registered M29 hypothesis in a read-only shadow validation.

The first supported hypothesis is ``top_decile_entry_timing_v1``. It reads an
existing top-decile 1d rolling forward-shadow artifact, checks it against the
M29 registry sample gates, and emits a non-promoting M29 artifact that can be
added to the evidence ledger. It never writes the DB, calls LLM/API services,
saves a model, trains a model, or changes production configuration.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.tools.m29_hypothesis_registry import default_hypotheses

DEFAULT_HYPOTHESIS_ID = "top_decile_entry_timing_v1"
DEFAULT_SOURCE_ARTIFACT = Path("/private/tmp/m27_forward_shadow_rolling_20260401_20260529_1d.json")
DEFAULT_JSON_OUTPUT = Path("/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.json")
DEFAULT_MARKDOWN_OUTPUT = Path("/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.md")
SUPPORTED_HYPOTHESES = {DEFAULT_HYPOTHESIS_ID}


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


def _candidate_summary(source: dict[str, Any], hypothesis: dict[str, Any]) -> dict[str, Any]:
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


def _validation_decision(source: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
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
    summary = _candidate_summary(source, hypothesis)
    validation = _validation_decision(source, summary)
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
            "run_mode": source.get("run_mode"),
            "start": source.get("start"),
            "end": source.get("end"),
            "exit_days": source.get("exit_days"),
        }],
        "start": source.get("start"),
        "end": source.get("end"),
        "horizon": source.get("horizon"),
        "exit_days": source.get("exit_days"),
        "panel": source.get("panel") or {},
        "hypothesis": hypothesis,
        "sample_gates": hypothesis.get("sample_gates") or {},
        "promotion_gate": hypothesis.get("promotion_gate"),
        "multiple_comparison": {
            "method": "pre_registered_single_candidate",
            "n_candidates_tested": 1,
            "warning": None,
        },
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
        f"- trade_weighted_avg_net_return_delta: {best.get('raw_top_bottom')}",
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
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_SOURCE_ARTIFACT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.source_artifact, hypothesis_id=args.hypothesis_id)
    args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.expanduser().write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    print(f"JSON report: {args.json_output.expanduser()}")
    print(f"Markdown report: {args.markdown_output.expanduser()}")
    print(f"Decision: {report['decision']['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
