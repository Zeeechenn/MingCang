"""One-command Atlas Stage 2b strict gate runner.

This wraps the existing Stage 2b shadow replay and Gate-B prospective tracker
into a single non-promoting evidence command. It never enables Atlas, never
writes the production DB, and never touches paper-trading state.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings

SCHEMA_VERSION = "atlas_stage2b_strict_gate.v1"
RUN_MODE = "read_only_atlas_stage2b_strict_gate"
DEFAULT_OUTPUT_DIR = Path("/private/tmp")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _compact_date(value: str) -> str:
    return value[:10].replace("-", "")


def _suffix(start: str, end: str) -> str:
    return f"{_compact_date(start)}_{_compact_date(end)}"


def default_output_paths(start: str, end: str) -> tuple[Path, Path]:
    stem = f"atlas_stage2b_strict_gate_{_suffix(start, end)}"
    return DEFAULT_OUTPUT_DIR / f"{stem}.json", DEFAULT_OUTPUT_DIR / f"{stem}.md"


def default_stage2_output_paths(start: str, end: str) -> tuple[Path, Path]:
    stem = f"atlas_stage2b_strict_gate_stage2_{_suffix(start, end)}"
    return DEFAULT_OUTPUT_DIR / f"{stem}.json", DEFAULT_OUTPUT_DIR / f"{stem}.md"


def default_gate_report_paths(start: str, end: str) -> tuple[Path, Path]:
    stem = f"atlas_stage2b_strict_gate_gate_b_{_suffix(start, end)}"
    return DEFAULT_OUTPUT_DIR / f"{stem}.json", DEFAULT_OUTPUT_DIR / f"{stem}.md"


def default_gate_db_path(start: str, end: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"atlas_stage2b_strict_gate_{_suffix(start, end)}.sqlite"


def _db_path_for_loaders(db_path_or_url: str | Path) -> str:
    value = str(db_path_or_url)
    if value.startswith("sqlite:///"):
        return value[len("sqlite:///"):]
    if value.startswith("sqlite:"):
        raise ValueError("paper-trading loaders require a SQLite file path or sqlite:/// URL")
    return value


def _json_write(payload: dict[str, Any], path: Path) -> None:
    path.expanduser().parent.mkdir(parents=True, exist_ok=True)
    path.expanduser().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _trade_date_order_violations(stage2_report: dict[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    arms = stage2_report.get("arms") or {}
    for arm_name, arm in arms.items():
        if not isinstance(arm, dict):
            continue
        for trade in arm.get("closed_trades") or []:
            if not isinstance(trade, dict):
                continue
            entry_date = str(trade.get("entry_date") or "")
            exit_date = str(trade.get("exit_date") or "")
            if entry_date and exit_date and exit_date < entry_date:
                violations.append({
                    "arm": arm_name,
                    "symbol": trade.get("symbol"),
                    "entry_signal_date": trade.get("entry_signal_date") or trade.get("signal_date"),
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                })
    return violations


def _stage2_summary(stage2_report: dict[str, Any]) -> dict[str, Any]:
    arms = stage2_report.get("arms") or {}
    baseline = arms.get("test2_baseline") or {}
    overlay = arms.get("atlas_signal_overlay") or {}
    baseline_summary = baseline.get("summary") or {}
    overlay_summary = overlay.get("summary") or {}
    gate_filter = overlay.get("gate_filter") or {}
    delta = overlay.get("delta_vs_test2_baseline") or {}
    maturity = stage2_report.get("stage2b_maturity_rule") or {}
    return {
        "baseline_weighted_total_pct": baseline_summary.get("weighted_total_pct"),
        "atlas_signal_overlay_weighted_total_pct": overlay_summary.get("weighted_total_pct"),
        "delta_weighted_total_pct": delta.get("weighted_total_pct"),
        "allowed_signals": gate_filter.get("allowed_signals"),
        "blocked_signals": gate_filter.get("blocked_signals"),
        "baseline_trades_current": maturity.get("baseline_trades_current"),
        "atlas_signal_overlay_trades_current": maturity.get("atlas_signal_overlay_trades_current"),
        "min_forward_weeks": maturity.get("min_forward_weeks"),
        "min_matured_trades_per_runnable_arm": maturity.get("min_matured_trades_per_runnable_arm"),
        "mature": bool(maturity.get("mature")),
    }


def _artifact_payload(paths: dict[str, Path | None]) -> dict[str, str]:
    return {key: str(path.expanduser()) for key, path in paths.items() if path is not None}


def build_strict_report(
    *,
    stage2_report: dict[str, Any],
    gate_b_report: dict[str, Any],
    realized_count: int,
    json_output: Path | None = None,
    markdown_output: Path | None = None,
    stage2_json_output: Path | None = None,
    stage2_markdown_output: Path | None = None,
    gate_report_json_output: Path | None = None,
    gate_report_markdown_output: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    violations = _trade_date_order_violations(stage2_report)
    stage2 = _stage2_summary(stage2_report)
    stage2_blockers = list(stage2_report.get("blockers") or [])
    gate_verdict = str(gate_b_report.get("verdict") or "INCONCLUSIVE")
    gate_reason = gate_b_report.get("reason")

    blockers: list[str] = []
    if violations:
        blockers.append("stage2b_exit_before_entry_date")
    blockers.extend(stage2_blockers)
    if gate_verdict != "PROMOTE":
        blockers.append(f"gate_b_{str(gate_reason or gate_verdict).lower()}")
    blockers.append("strict_gate_non_promoting_requires_user_confirmation")
    blockers = list(dict.fromkeys(blockers))

    if violations:
        final_verdict = "ABORT"
    elif gate_verdict == "PROMOTE" and not stage2.get("mature"):
        final_verdict = "INCONCLUSIVE"
    else:
        final_verdict = gate_verdict
    promotable = final_verdict == "PROMOTE" and bool(stage2.get("mature")) and not violations
    decision = {
        "verdict": final_verdict,
        "decision": "atlas_can_be_enabled_after_user_confirmation" if promotable else "keep_atlas_dormant",
        "promotable": promotable,
        "recommended_next_action": (
            "fix_stage2_replay_chronology_before_any_atlas_decision"
            if violations
            else "rerun_strict_gate_after_more_close_confirmed_forward_data"
            if not stage2.get("mature")
            else "review_gate_b_result_before_manual_atlas_enablement"
        ),
        "blockers": blockers,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "run_mode": RUN_MODE,
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "writes_production_db": False,
        "writes_isolated_gate_db": True,
        "touches_test2_state": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "trains_model": False,
        "atlas_enabled_required": False,
        "start": stage2_report.get("start"),
        "end": stage2_report.get("end"),
        "source_db": stage2_report.get("source_db"),
        "gate_db": stage2_report.get("gate_db"),
        "horizon_days": gate_b_report.get("horizon_days", 5),
        "realized_count_this_run": realized_count,
        "artifacts": _artifact_payload({
            "json_output": json_output,
            "markdown_output": markdown_output,
            "stage2_json_output": stage2_json_output,
            "stage2_markdown_output": stage2_markdown_output,
            "gate_report_json_output": gate_report_json_output,
            "gate_report_markdown_output": gate_report_markdown_output,
        }),
        "stage2_summary": stage2,
        "gate_b_report": gate_b_report,
        "sanity_checks": {
            "passed": not violations,
            "exit_before_entry_count": len(violations),
            "exit_before_entry_violations": violations,
        },
        "decision": decision,
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    stage2 = report.get("stage2_summary") or {}
    gate_b = report.get("gate_b_report") or {}
    decision = report.get("decision") or {}
    checks = report.get("sanity_checks") or {}
    lines = [
        "# Atlas Stage 2b Strict Gate",
        "",
        f"- generated_at: {report.get('generated_at')}",
        f"- run_mode: {report.get('run_mode')}",
        f"- non_promoting: {report.get('non_promoting')}",
        f"- production_unchanged: {report.get('production_unchanged')}",
        f"- writes_production_db: {report.get('writes_production_db')}",
        f"- writes_isolated_gate_db: {report.get('writes_isolated_gate_db')}",
        f"- touches_test2_state: {report.get('touches_test2_state')}",
        f"- atlas_enabled_required: {report.get('atlas_enabled_required')}",
        f"- window: {report.get('start')} ~ {report.get('end')}",
        "",
        "## Stage 2b Summary",
        "",
        f"- baseline_weighted_total_pct: {stage2.get('baseline_weighted_total_pct')}",
        f"- atlas_signal_overlay_weighted_total_pct: {stage2.get('atlas_signal_overlay_weighted_total_pct')}",
        f"- delta_weighted_total_pct: {stage2.get('delta_weighted_total_pct')}",
        f"- allowed_signals: {stage2.get('allowed_signals')}",
        f"- blocked_signals: {stage2.get('blocked_signals')}",
        f"- mature: {stage2.get('mature')}",
        "",
        "## Gate-B Summary",
        "",
        f"- verdict: {gate_b.get('verdict')}",
        f"- reason: {gate_b.get('reason')}",
        f"- n_realized: {gate_b.get('n_realized')}",
        f"- n_pass: {gate_b.get('n_pass')}",
        f"- n_fail: {gate_b.get('n_fail')}",
        f"- avg_net_return_delta: {gate_b.get('avg_net_return_delta')}",
        "",
        "## Sanity Checks",
        "",
        f"- passed: {checks.get('passed')}",
        f"- exit_before_entry_count: {checks.get('exit_before_entry_count')}",
        "",
        "## Decision",
        "",
        f"- verdict: {decision.get('verdict')}",
        f"- decision: {decision.get('decision')}",
        f"- promotable: {decision.get('promotable')}",
        f"- recommended_next_action: {decision.get('recommended_next_action')}",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {blocker}" for blocker in decision.get("blockers") or [])
    return "\n".join(lines) + "\n"


def write_artifacts(report: dict[str, Any], *, json_output: Path, markdown_output: Path) -> None:
    _json_write(report, json_output)
    markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    markdown_output.expanduser().write_text(report_to_markdown(report), encoding="utf-8")


def _gate_report_to_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gate-B Experiment Report",
        "",
        f"- verdict: {result.get('verdict')}",
        f"- reason: {result.get('reason')}",
        f"- n_realized: {result.get('n_realized')}",
        f"- n_pass: {result.get('n_pass')}",
        f"- n_fail: {result.get('n_fail')}",
        f"- avg_net_return_pass: {result.get('avg_net_return_pass')}",
        f"- avg_net_return_fail: {result.get('avg_net_return_fail')}",
        f"- avg_net_return_delta: {result.get('avg_net_return_delta')}",
        "",
    ]
    return "\n".join(lines)


def _write_gate_report_artifacts(
    result: dict[str, Any],
    *,
    json_output: Path,
    markdown_output: Path,
) -> None:
    _json_write(result, json_output)
    markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    markdown_output.expanduser().write_text(_gate_report_to_markdown(result), encoding="utf-8")


def run_strict_gate(
    *,
    db: str | Path,
    universe: Path,
    start: str,
    end: str,
    gate_db: str | Path | None = None,
    horizon_days: int = 5,
    json_output: Path | None = None,
    markdown_output: Path | None = None,
    stage2_json_output: Path | None = None,
    stage2_markdown_output: Path | None = None,
    gate_report_json_output: Path | None = None,
    gate_report_markdown_output: Path | None = None,
) -> dict[str, Any]:
    from backend.research.gate_b_recorder import realize_returns
    from backend.research.gate_b_recorder import report as gate_b_report
    from backend.tools import atlas_test4_stage2b_shadow as stage2
    from backend.tools.gate_b_tracker import readonly_session, write_session

    json_output = (json_output or default_output_paths(start, end)[0]).expanduser()
    markdown_output = (markdown_output or default_output_paths(start, end)[1]).expanduser()
    stage2_json_output = (stage2_json_output or default_stage2_output_paths(start, end)[0]).expanduser()
    stage2_markdown_output = (stage2_markdown_output or default_stage2_output_paths(start, end)[1]).expanduser()
    gate_report_json_output = (gate_report_json_output or default_gate_report_paths(start, end)[0]).expanduser()
    gate_report_markdown_output = (gate_report_markdown_output or default_gate_report_paths(start, end)[1]).expanduser()

    gate_db_path_or_url = gate_db or default_gate_db_path(start, end)
    source_db_url = stage2._sqlite_url(db)
    gate_db_url = stage2._sqlite_url(gate_db_path_or_url)
    loader_db_path = _db_path_for_loaders(db)

    universe_names = stage2.load_universe(universe)
    universe_set = set(universe_names)
    sectors = stage2.load_sectors(universe)
    signals = stage2.load_signals(loader_db_path, universe_names, start=start, end=end)
    prices = stage2.load_prices(loader_db_path, universe_names, start=start, end=end)
    gate_rows = stage2._record_gate_rows(
        gate_db_url=gate_db_url,
        source_db_url=source_db_url,
        as_of=end,
        horizon_days=horizon_days,
        symbols=sorted(universe_set),
    )
    stage2_report = stage2.build_report(
        signals=signals,
        prices=prices,
        universe=universe_set,
        sectors=sectors,
        gate_rows=gate_rows,
        start=start,
        end=end,
        source_db=source_db_url,
        gate_db=gate_db_url,
        writes_isolated_gate_db=True,
    )
    stage2.write_artifacts(
        stage2_report,
        json_output=stage2_json_output,
        markdown_output=stage2_markdown_output,
    )

    previous = settings.gate_b_tracker_enabled
    settings.gate_b_tracker_enabled = True
    try:
        with write_session(gate_db_url) as gate_session, readonly_session(source_db_url) as source_session:
            realized = realize_returns(gate_session, source_db=source_session, as_of=end)
            gate_report = gate_b_report(gate_session)
    finally:
        settings.gate_b_tracker_enabled = previous

    gate_report["horizon_days"] = horizon_days
    _write_gate_report_artifacts(
        gate_report,
        json_output=gate_report_json_output,
        markdown_output=gate_report_markdown_output,
    )
    report = build_strict_report(
        stage2_report=stage2_report,
        gate_b_report=gate_report,
        realized_count=len(realized),
        json_output=json_output,
        markdown_output=markdown_output,
        stage2_json_output=stage2_json_output,
        stage2_markdown_output=stage2_markdown_output,
        gate_report_json_output=gate_report_json_output,
        gate_report_markdown_output=gate_report_markdown_output,
    )
    write_artifacts(report, json_output=json_output, markdown_output=markdown_output)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from paper_trading.test2_ab_data import DEFAULT_DB, DEFAULT_UNIVERSE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="read-only source DB path or sqlite URL")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--start", default="2026-05-18")
    parser.add_argument("--end", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--gate-db", help="isolated Gate-B observation DB path or sqlite URL")
    parser.add_argument("--horizon-days", type=int, default=5)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--stage2-json-output", type=Path)
    parser.add_argument("--stage2-markdown-output", type=Path)
    parser.add_argument("--gate-report-json-output", type=Path)
    parser.add_argument("--gate-report-markdown-output", type=Path)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_strict_gate(
        db=args.db,
        universe=args.universe,
        start=args.start,
        end=args.end,
        gate_db=args.gate_db,
        horizon_days=args.horizon_days,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
        stage2_json_output=args.stage2_json_output,
        stage2_markdown_output=args.stage2_markdown_output,
        gate_report_json_output=args.gate_report_json_output,
        gate_report_markdown_output=args.gate_report_markdown_output,
    )
    if args.print:
        print(report_to_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
