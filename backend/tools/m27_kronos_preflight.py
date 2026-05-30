"""M27.4 Kronos fine-tuning read-only preflight report.

This tool checks whether reviewed M27.4 data and local environment look ready
for a separately approved Kronos-small fine-tuning run. It does not start
training, does not write model checkpoints, and does not evaluate production.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = Path.home() / ".stock-sage" / "m27_kronos_reviewed_data"
DEFAULT_COVERAGE_REPORT = DEFAULT_DATA_DIR / "coverage_report.json"
DEFAULT_UNIVERSE_PATH = Path.home() / ".stock-sage" / "m27_kronos_reviewed_complete_universe.json"
DEFAULT_CHECKPOINT_DIR = Path.home() / ".stock-sage" / "models" / "kronos_finetuned"
DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m27_kronos_preflight_report.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m27_kronos_preflight_report.md"

REQUIRED_DATA_FILES = ["train_data.pkl", "valid_data.pkl", "windows.csv", "coverage_report.json"]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def _file_status(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    return {
        "path": str(expanded),
        "exists": expanded.exists(),
        "size_bytes": expanded.stat().st_size if expanded.exists() else 0,
    }


def _count_universe_symbols(path: Path) -> int | None:
    if not path.expanduser().exists():
        return None
    payload = _load_json(path)
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None
    symbols = [
        str(row.get("symbol") if isinstance(row, dict) else row)
        for row in rows
        if (row.get("symbol") if isinstance(row, dict) else row)
    ]
    return len(set(symbols))


def build_report(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    coverage_report_path: Path = DEFAULT_COVERAGE_REPORT,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    checkpoint_dir: Path = DEFAULT_CHECKPOINT_DIR,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    data_dir = data_dir.expanduser()
    coverage_report_path = coverage_report_path.expanduser()
    checkpoint_dir = checkpoint_dir.expanduser()
    coverage = _load_json(coverage_report_path) if coverage_report_path.exists() else {}
    data_files = {
        name: _file_status(data_dir / name)
        for name in REQUIRED_DATA_FILES
    }
    missing_data_files = [name for name, status in data_files.items() if not status["exists"]]
    hard_failures = list(coverage.get("hard_failures") or [])
    universe_symbols = _count_universe_symbols(universe_path)
    complete_symbols = int(coverage.get("complete_symbols") or 0)
    min_symbols = int(coverage.get("min_symbols") or 0)
    coverage_passed = bool(coverage.get("passed"))
    checkpoint_status = _file_status(checkpoint_dir)
    vendor_status = _file_status(repo_root / "vendor" / "kronos")
    venv_status = _file_status(repo_root / ".venv_kronos")

    blockers: list[str] = []
    warnings: list[str] = []
    if missing_data_files:
        blockers.append("missing_required_data_files")
    if not coverage_passed:
        blockers.append("coverage_report_not_passed")
    if hard_failures:
        blockers.append("coverage_report_has_hard_failures")
    if universe_symbols is not None and universe_symbols != complete_symbols:
        warnings.append("reviewed_universe_count_differs_from_complete_symbols")
    if complete_symbols < min_symbols:
        blockers.append("complete_symbols_below_min_symbols")
    if checkpoint_status["exists"]:
        warnings.append("finetuned_checkpoint_already_exists_review_before_overwrite")
    else:
        warnings.append("finetuned_checkpoint_missing_expected_before_first_training")
    if not vendor_status["exists"]:
        warnings.append("vendor_kronos_missing_training_environment_not_ready")
    if not venv_status["exists"]:
        warnings.append("venv_kronos_missing_training_environment_not_ready")

    decision = "ready_for_training_confirmation" if not blockers else "blocked_before_training"
    stop_gates = [
        "starting Kronos training writes model artifacts and requires explicit approval",
        "training may use GPU/MPS time and local model cache; confirm runtime budget first",
        "final evaluation must use M27 production gate IC>=0.04 / ICIR>=0.40 / monotonic=True",
        "do not judge finetuned Kronos solely by the older M26 diagnostic gate",
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "milestone": "M27.4",
        "purpose": "read-only preflight before any Kronos-small fine-tuning run",
        "starts_training": False,
        "writes_checkpoint": False,
        "calls_external_api": False,
        "data": {
            "data_dir": str(data_dir),
            "files": data_files,
            "missing_files": missing_data_files,
        },
        "coverage": {
            "path": str(coverage_report_path),
            "exists": coverage_report_path.exists(),
            "passed": coverage_passed,
            "requested_symbols": coverage.get("requested_symbols"),
            "complete_symbols": complete_symbols,
            "min_symbols": min_symbols,
            "train_windows": ((coverage.get("splits") or {}).get("train") or {}).get("windows"),
            "valid_windows": ((coverage.get("splits") or {}).get("valid") or {}).get("windows"),
            "hard_failures": hard_failures,
        },
        "universe": {
            "path": str(universe_path.expanduser()),
            "symbols": universe_symbols,
        },
        "checkpoint": checkpoint_status,
        "environment": {
            "vendor_kronos": vendor_status,
            "venv_kronos": venv_status,
        },
        "gate_policy": {
            "m27_production_gate": {"ic_floor": 0.04, "icir_floor": 0.40, "require_monotonic": True},
            "m26_diagnostic_gate_is_not_sufficient_for_m27_promotion": True,
            "must_beat_m27_1_baseline": True,
        },
        "decision": {
            "decision": decision,
            "blockers": blockers,
            "warnings": warnings,
            "stop_gates": stop_gates,
            "recommended_next_action": (
                "ask_user_for_explicit_training_confirmation_with_runtime_and_output_limits"
                if not blockers
                else "fix_preflight_blockers_before_training_confirmation"
            ),
        },
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    decision = report["decision"]
    checkpoint = report["checkpoint"]
    env = report["environment"]
    lines = [
        "# M27.4 Kronos Preflight",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- starts_training: {report['starts_training']}",
        f"- writes_checkpoint: {report['writes_checkpoint']}",
        f"- calls_external_api: {report['calls_external_api']}",
        f"- decision: {decision['decision']}",
        f"- blockers: {', '.join(decision['blockers']) if decision['blockers'] else 'none'}",
        f"- warnings: {', '.join(decision['warnings']) if decision['warnings'] else 'none'}",
        "",
        "## Coverage",
        "",
        f"- passed: {coverage['passed']}",
        f"- complete_symbols: {coverage['complete_symbols']} / min_symbols: {coverage['min_symbols']}",
        f"- train_windows: {coverage['train_windows']}",
        f"- valid_windows: {coverage['valid_windows']}",
        f"- hard_failures: {coverage['hard_failures']}",
        "",
        "## Checkpoint And Environment",
        "",
        f"- checkpoint_exists: {checkpoint['exists']} ({checkpoint['path']})",
        f"- vendor_kronos_exists: {env['vendor_kronos']['exists']}",
        f"- venv_kronos_exists: {env['venv_kronos']['exists']}",
        "",
        "## Stop Gates",
        "",
    ]
    lines.extend(f"- {gate}" for gate in decision["stop_gates"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--coverage-report", type=Path, default=DEFAULT_COVERAGE_REPORT)
    parser.add_argument("--universe-path", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        data_dir=args.data_dir,
        coverage_report_path=args.coverage_report,
        universe_path=args.universe_path,
        checkpoint_dir=args.checkpoint_dir,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.write_text(markdown, encoding="utf-8")
    if args.print:
        print(markdown)
    else:
        print(f"JSON report: {args.json_output}")
        print(f"Markdown report: {args.markdown_output}")
        print(f"Decision: {report['decision']['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
