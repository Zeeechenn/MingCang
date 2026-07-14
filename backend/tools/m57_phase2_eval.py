"""M57/M65 four-arm shadow-evaluation harness.

This tool is deterministic, zero-LLM and artifact-only. It does not call the
retired Serenity analyzer; ``serenity`` means a method lens supplied in the
fixture, not a production agent or score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path

ARM_KEYS = ("base", "memory", "serenity", "both")
QUALITY_METRICS = (
    "source_fidelity",
    "key_fact_coverage",
    "contradiction_handling",
    "falsifiability",
)
ERROR_METRIC = "hallucination_error_rate"
MIN_CASES = 20
MIN_INDUSTRIES = 3
MIN_QUALITY_DELTA = 0.15
MAX_DEEP_COST_DELTA = 0.25


def _fingerprint(case: dict[str, Any]) -> str:
    canonical = json.dumps({
        "id": case.get("id"),
        "as_of": case.get("as_of"),
        "evidence_snapshot": case.get("evidence_snapshot"),
        "output_template_version": case.get("output_template_version"),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_fixture(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixture.cases must be a non-empty list")
    seen: set[str] = set()
    for case in cases:
        required = ("id", "industry", "as_of", "question", "evidence_snapshot", "output_template_version")
        missing = [field for field in required if not case.get(field)]
        if missing:
            raise ValueError(f"case missing required fields: {missing}")
        case_id = str(case["id"])
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        arms = case.get("arms")
        if not isinstance(arms, dict) or set(arms) != set(ARM_KEYS):
            raise ValueError(f"case {case_id} must contain exactly {ARM_KEYS}")
        expected = _fingerprint(case)
        for arm_key in ARM_KEYS:
            arm = arms[arm_key]
            if not isinstance(arm, dict) or not isinstance(arm.get("response"), str):
                raise ValueError(f"case {case_id} arm {arm_key} lacks response")
            supplied = arm.get("input_fingerprint")
            if supplied is not None and supplied != expected:
                raise ValueError(f"case {case_id} arm {arm_key} fingerprint differs")
            arm["input_fingerprint"] = expected
    return cases


def _blind_labels(case_id: str, as_of: str) -> dict[str, str]:
    ranked = sorted(
        ARM_KEYS,
        key=lambda arm: hashlib.sha256(f"{case_id}|{as_of}|{arm}".encode()).hexdigest(),
    )
    return {label: arm for label, arm in zip(("甲", "乙", "丙", "丁"), ranked, strict=True)}


def build_blind_packets(fixture: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    cases = validate_fixture(fixture)
    packets_dir = out_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    answer_key: dict[str, dict[str, str]] = {}
    for case in cases:
        case_id = str(case["id"])
        labels = _blind_labels(case_id, str(case["as_of"]))
        answer_key[case_id] = labels
        lines = [f"# Case {case_id}", "", str(case["question"]), ""]
        for label, arm in labels.items():
            lines.extend([f"## 方案{label}", "", case["arms"][arm]["response"], ""])
        (packets_dir / f"{case_id}.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "answer_key.json").write_text(
        json.dumps(answer_key, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "status": "AWAITING_BLIND_SCORES",
        "cases": len(cases),
        "industries": len({str(case["industry"]) for case in cases}),
        "signal_effect": "none",
        "writes_database": False,
        "promotion_policy": "never",
        "serenity_mode": "method_lens_only",
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def evaluate_scores(fixture: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    cases = validate_fixture(fixture)
    score_cases = scores.get("cases")
    if not isinstance(score_cases, list):
        raise ValueError("scores.cases must be a list")
    by_id = {str(item.get("case_id")): item for item in score_cases if isinstance(item, dict)}
    metric_values: dict[str, dict[str, list[float]]] = {
        arm: {metric: [] for metric in (*QUALITY_METRICS, ERROR_METRIC)}
        for arm in ARM_KEYS
    }
    for case in cases:
        case_id = str(case["id"])
        item = by_id.get(case_id)
        if item is None:
            raise ValueError(f"missing blind scores for case {case_id}")
        arm_scores = item.get("arms")
        if not isinstance(arm_scores, dict) or set(arm_scores) != set(ARM_KEYS):
            raise ValueError(f"scores for {case_id} must contain exactly {ARM_KEYS}")
        for arm in ARM_KEYS:
            for metric in (*QUALITY_METRICS, ERROR_METRIC):
                value = arm_scores[arm].get(metric)
                if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                    raise ValueError(f"invalid {case_id}/{arm}/{metric}: {value!r}")
                metric_values[arm][metric].append(float(value))

    averages = {
        arm: {
            metric: sum(values) / len(values)
            for metric, values in arm_metrics.items()
        }
        for arm, arm_metrics in metric_values.items()
    }
    quality_deltas = {
        metric: averages["both"][metric] - averages["base"][metric]
        for metric in QUALITY_METRICS
    }
    base_cost = sum(float(case["arms"]["base"].get("cost_units") or 0) for case in cases)
    both_cost = sum(float(case["arms"]["both"].get("cost_units") or 0) for case in cases)
    if base_cost == 0:
        deep_cost_delta: float | None = 0.0 if both_cost == 0 else None
    else:
        deep_cost_delta = (both_cost - base_cost) / base_cost
    industries = len({str(case["industry"]) for case in cases})
    gates = {
        "sample_cases": len(cases) >= MIN_CASES,
        "industry_coverage": industries >= MIN_INDUSTRIES,
        **{
            f"{metric}_delta": delta >= MIN_QUALITY_DELTA
            for metric, delta in quality_deltas.items()
        },
        "hallucination_not_worse": (
            averages["both"][ERROR_METRIC] <= averages["base"][ERROR_METRIC]
        ),
        "default_daily_llm_zero": scores.get("default_daily_llm_calls") == 0,
        "deep_cost_delta": (
            deep_cost_delta is not None and deep_cost_delta <= MAX_DEEP_COST_DELTA
        ),
        "signal_boundary_zero": scores.get("signal_boundary_diff") == 0,
    }
    passed = all(gates.values())
    return {
        "decision": "GO_PHASE_3_4" if passed else "HOLD_STOP_PHASE_3_4",
        "cases": len(cases),
        "industries": industries,
        "averages": averages,
        "quality_deltas": quality_deltas,
        "deep_cost_delta": deep_cost_delta,
        "gates": gates,
        "signal_effect": "none",
        "serenity_mode": "method_lens_only",
    }


def audit_live_readiness(db_path: Path | None = None) -> dict[str, Any]:
    resolved = (db_path or default_sqlite_path()).resolve()
    con = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("""
            SELECT id, input_snapshot_json
            FROM decision_runs
            WHERE run_type = 'deep_research'
        """).fetchall()
    finally:
        con.close()
    report_paths: set[str] = set()
    for row in rows:
        try:
            snapshot = json.loads(row["input_snapshot_json"] or "{}")
        except json.JSONDecodeError:
            snapshot = {}
        report_path = snapshot.get("report_path")
        if report_path:
            report_paths.add(str(report_path))

    project_root = Path(__file__).resolve().parents[2]
    readable_report_paths: set[str] = set()
    missing_report_paths: set[str] = set()
    for raw_path in report_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_root / path
        target = path.resolve()
        if target.is_file():
            readable_report_paths.add(str(target))
        else:
            missing_report_paths.add(raw_path)

    independent_cases = len(readable_report_paths)
    return {
        "decision_run_rows": len(rows),
        "independent_cases": independent_cases,
        "recorded_report_paths": len(report_paths),
        "missing_report_paths": sorted(missing_report_paths),
        "minimum_cases": MIN_CASES,
        "sample_gate_pass": independent_cases >= MIN_CASES,
        "decision": "READY_FOR_FOUR_ARM_SCORING" if independent_cases >= MIN_CASES else "HOLD_STOP_PHASE_3_4",
        "reason": None if independent_cases >= MIN_CASES else "独立 deep-research 样本不足",
        "db_read_mode": "sqlite_mode_ro",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M57/M65 four-arm shadow evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--db", type=Path, default=None)
    audit.add_argument("--pretty", action="store_true")
    build = sub.add_parser("build")
    build.add_argument("--fixture", type=Path, required=True)
    build.add_argument("--out-dir", type=Path, required=True)
    build.add_argument("--pretty", action="store_true")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--fixture", type=Path, required=True)
    evaluate.add_argument("--scores", type=Path, required=True)
    evaluate.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.command == "audit":
        result = audit_live_readiness(args.db)
    else:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        if args.command == "build":
            result = build_blind_packets(fixture, args.out_dir)
        else:
            scores = json.loads(args.scores.read_text(encoding="utf-8"))
            result = evaluate_scores(fixture, scores)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, default=str))


if __name__ == "__main__":
    main()
