"""Atlas test4 Stage 2b forward shadow starter.

This tool starts the Stage 2b shadow lane without promoting Atlas behavior:

- reads the frozen test2 universe, production signals, and prices read-only;
- optionally records Gate-B observations into an isolated DB under /private/tmp;
- replays the current test2 baseline and an Atlas signal-overlay arm;
- registers the exit-overlay arms as not started until a runnable thesis-
  invalidation backtest exists.

It never writes production DB rows, test2 state files, scheduler config,
official signals, positions, or scoring configuration.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings
from paper_trading.test2_ab_data import (
    DEFAULT_DB,
    DEFAULT_STATE,
    DEFAULT_UNIVERSE,
    load_prices,
    load_sectors,
    load_signals,
    load_universe,
)
from paper_trading.test2_ab_models import (
    DEFAULT_MAX_POSITIONS,
    FRAMEWORKS,
    Framework,
    PriceBar,
    Signal,
)
from paper_trading.test2_ab_runner import replay
from paper_trading.test2_ab_stats import holding_state, result_summary

SCHEMA_VERSION = "atlas_test4_stage2b_shadow.v1"
RUN_MODE = "read_only_atlas_stage2b_forward_shadow"
DEFAULT_OUTPUT_DIR = Path("/private/tmp")
DEFAULT_GATE_DB = Path("/private/tmp/atlas_test4_stage2b_gate_b.sqlite")
MIN_FORWARD_WEEKS = 8
MIN_MATURED_TRADES = 30
BASELINE_FRAMEWORK = FRAMEWORKS["B_quant_off"]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _compact_date(value: str) -> str:
    return value[:10].replace("-", "")


def _sqlite_url(path_or_url: str | Path) -> str:
    value = str(path_or_url)
    if value.startswith("sqlite:"):
        return value
    return "sqlite:///" + str(Path(value).expanduser().resolve())


def default_output_paths(start: str, end: str) -> tuple[Path, Path]:
    suffix = f"{_compact_date(start)}_{_compact_date(end)}"
    stem = f"atlas_test4_stage2b_shadow_{suffix}"
    return DEFAULT_OUTPUT_DIR / f"{stem}.json", DEFAULT_OUTPUT_DIR / f"{stem}.md"


def _atlas_framework(key: str, label: str) -> Framework:
    return Framework(
        key=key,
        label=label,
        quant_weight=BASELINE_FRAMEWORK.quant_weight,
        tech_weight=BASELINE_FRAMEWORK.tech_weight,
        sent_weight=BASELINE_FRAMEWORK.sent_weight,
        entry_threshold=BASELINE_FRAMEWORK.entry_threshold,
    )


def _gate_ready_keys(gate_rows: list[dict[str, Any]]) -> tuple[set[tuple[str, str]], dict[str, Any]]:
    allowed: set[tuple[str, str]] = set()
    blocked = 0
    for row in gate_rows:
        symbol = str(row.get("symbol") or "").strip()
        signal_date = str(row.get("signal_date") or "").strip()
        if not symbol or not signal_date:
            continue
        ready = row.get("ready_variant")
        if ready is None:
            ready = bool(row.get("gate_pass_variant")) and bool(row.get("card_pass", True))
        if ready:
            allowed.add((symbol, signal_date))
        else:
            blocked += 1
    return allowed, {
        "source_rows": len(gate_rows),
        "allowed_signals": len(allowed),
        "blocked_signals": blocked,
        "filter": "Gate-B ready_variant, falling back to gate_pass_variant AND card_pass",
    }


def _filter_signals(signals: list[Signal], allowed: set[tuple[str, str]]) -> list[Signal]:
    return [signal for signal in signals if (signal.symbol, signal.date) in allowed]


def _arm_payload(result, prices: dict[tuple[str, str], PriceBar], *, status: str) -> dict[str, Any]:
    return {
        "status": status,
        "framework": {
            "key": result.framework.key,
            "label": result.framework.label,
            "weights": {
                "quant": result.framework.quant_weight,
                "technical": result.framework.tech_weight,
                "sentiment": result.framework.sent_weight,
            },
            "entry_threshold": result.framework.entry_threshold,
        },
        "summary": result_summary(result, prices),
        "open_holdings": [holding_state(holding, prices) for holding in result.open_holdings],
        "closed_trades": [trade.__dict__ for trade in result.closed_trades],
        "daily_entries": result.daily_entries,
    }


def _delta(overlay: dict[str, Any], baseline: dict[str, Any], metric: str) -> float | None:
    left = (overlay.get("summary") or {}).get(metric)
    right = (baseline.get("summary") or {}).get(metric)
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 4)


def build_report(
    *,
    signals: list[Signal],
    prices: dict[tuple[str, str], PriceBar],
    universe: set[str],
    sectors: dict[str, str],
    gate_rows: list[dict[str, Any]],
    start: str,
    end: str,
    source_db: str,
    gate_db: str,
    test2_state_path: str | Path = DEFAULT_STATE,
    writes_isolated_gate_db: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    allowed, gate_filter = _gate_ready_keys(gate_rows)
    baseline_key = "test2_baseline"
    signal_key = "atlas_signal_overlay"
    baseline_results = replay(
        signals,
        prices,
        universe=universe,
        frameworks={baseline_key: _atlas_framework(baseline_key, "test2 baseline (quant_off)")},
        max_positions=DEFAULT_MAX_POSITIONS,
        sectors=sectors,
    )
    signal_results = replay(
        _filter_signals(signals, allowed),
        prices,
        universe=universe,
        frameworks={signal_key: _atlas_framework(signal_key, "Atlas signal overlay (Gate-B ready)")},
        max_positions=DEFAULT_MAX_POSITIONS,
        sectors=sectors,
    )
    baseline_arm = _arm_payload(baseline_results[baseline_key], prices, status="runnable")
    signal_arm = _arm_payload(signal_results[signal_key], prices, status="runnable")
    signal_arm["gate_filter"] = gate_filter
    signal_arm["delta_vs_test2_baseline"] = {
        "weighted_total_pct": _delta(signal_arm, baseline_arm, "weighted_total_pct"),
        "total_stock_pct": _delta(signal_arm, baseline_arm, "total_stock_pct"),
        "closed": _delta(signal_arm, baseline_arm, "closed"),
        "open": _delta(signal_arm, baseline_arm, "open"),
    }

    baseline_trades = len(baseline_arm["closed_trades"]) + len(baseline_arm["open_holdings"])
    overlay_trades = len(signal_arm["closed_trades"]) + len(signal_arm["open_holdings"])
    blockers = [
        "stage2b_forward_sample_not_mature",
        "exit_overlay_not_implemented",
        "entry_exit_overlay_not_implemented",
        "promotion_requires_stage2_pass_and_user_confirmation",
        "non_promoting_shadow_only",
    ]
    if gate_filter["allowed_signals"] == 0:
        blockers.append("no_gate_ready_signal_overlay_entries")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "milestone": "M44/test4 Stage 2b",
        "purpose": "forward shadow starter for Atlas investment-effect measurement",
        "run_mode": RUN_MODE,
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "writes_production_db": False,
        "writes_isolated_gate_db": writes_isolated_gate_db,
        "touches_test2_state": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "atlas_enabled_required": False,
        "source_db": source_db,
        "gate_db": gate_db,
        "test2_state_path": str(Path(test2_state_path).expanduser()),
        "start": start,
        "end": end,
        "universe_symbols": len(universe),
        "input_signals": len(signals),
        "arms": {
            "test2_baseline": baseline_arm,
            "atlas_signal_overlay": signal_arm,
            "atlas_exit_overlay": {
                "status": "registered_not_started",
                "reason": "thesis-invalidation exit overlay does not yet have a runnable backtest",
            },
            "atlas_entry_exit_overlay": {
                "status": "registered_not_started",
                "reason": "requires both signal overlay and thesis-invalidation exit overlay",
            },
        },
        "stage2b_maturity_rule": {
            "min_forward_weeks": MIN_FORWARD_WEEKS,
            "min_matured_trades_per_runnable_arm": MIN_MATURED_TRADES,
            "baseline_trades_current": baseline_trades,
            "atlas_signal_overlay_trades_current": overlay_trades,
            "mature": False,
        },
        "blockers": blockers,
        "decision": {
            "decision": "collect_forward_shadow",
            "promotable": False,
            "recommended_next_action": "rerun after new close-confirmed forward data; implement exit overlay separately",
        },
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    arms = report.get("arms") or {}
    signal = arms.get("atlas_signal_overlay") or {}
    gate_filter = signal.get("gate_filter") or {}
    lines = [
        "# Atlas Test4 Stage 2b Forward Shadow",
        "",
        f"- generated_at: {report.get('generated_at')}",
        f"- run_mode: {report.get('run_mode')}",
        f"- non_promoting: {report.get('non_promoting')}",
        f"- production_unchanged: {report.get('production_unchanged')}",
        f"- writes_db: {report.get('writes_db')}",
        f"- touches_test2_state: {report.get('touches_test2_state')}",
        f"- atlas_enabled_required: {report.get('atlas_enabled_required')}",
        f"- window: {report.get('start')} ~ {report.get('end')}",
        "",
        "## Arms",
        "",
        "| arm | status | weighted_total_pct | notes |",
        "| --- | --- | ---: | --- |",
    ]
    for key in ("test2_baseline", "atlas_signal_overlay", "atlas_exit_overlay", "atlas_entry_exit_overlay"):
        arm = arms.get(key) or {}
        summary = arm.get("summary") or {}
        weighted = summary.get("weighted_total_pct")
        notes = arm.get("reason") or ""
        if key == "atlas_signal_overlay":
            notes = (
                f"allowed={gate_filter.get('allowed_signals')}, "
                f"blocked={gate_filter.get('blocked_signals')}"
            )
        lines.append(f"| {key} | {arm.get('status')} | {weighted if weighted is not None else '—'} | {notes} |")
    lines.extend([
        "",
        "## Blockers",
        "",
    ])
    lines.extend(f"- {blocker}" for blocker in report.get("blockers") or [])
    decision = report.get("decision") or {}
    lines.extend([
        "",
        "## Decision",
        "",
        f"- decision: {decision.get('decision')}",
        f"- promotable: {decision.get('promotable')}",
        f"- recommended_next_action: {decision.get('recommended_next_action')}",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(report: dict[str, Any], *, json_output: Path, markdown_output: Path) -> None:
    json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    json_output.expanduser().write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_output.expanduser().write_text(report_to_markdown(report), encoding="utf-8")


def _load_gate_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("rows") or payload.get("observations") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("gate rows artifact must be a list or object with rows/observations")
    return [row for row in rows if isinstance(row, dict)]


def _record_gate_rows(
    *,
    gate_db_url: str,
    source_db_url: str,
    as_of: str,
    horizon_days: int,
    symbols: list[str],
) -> list[dict[str, Any]]:
    from backend.research.gate_b_recorder import list_observations, record_observations
    from backend.tools.gate_b_tracker import readonly_session, write_session

    previous = settings.gate_b_tracker_enabled
    settings.gate_b_tracker_enabled = True
    try:
        with write_session(gate_db_url) as db, readonly_session(source_db_url) as src:
            record_observations(
                db,
                source_db=src,
                as_of=as_of,
                horizon_days=horizon_days,
                symbols=symbols,
            )
            rows = list_observations(db, limit=100_000)
    finally:
        settings.gate_b_tracker_enabled = previous
    return [
        row
        for row in rows
        if row.get("symbol") in set(symbols) and str(row.get("signal_date") or "")[:10] <= as_of[:10]
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="read-only source DB path or sqlite URL")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--start", default="2026-05-18")
    parser.add_argument("--end", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--gate-db", default=str(DEFAULT_GATE_DB), help="isolated Gate-B observation DB")
    parser.add_argument("--gate-rows-json", type=Path, help="optional precomputed Gate-B rows JSON")
    parser.add_argument("--horizon-days", type=int, default=5)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    json_output, markdown_output = default_output_paths(args.start, args.end)
    json_output = (args.json_output or json_output).expanduser()
    markdown_output = (args.markdown_output or markdown_output).expanduser()

    universe_names = load_universe(args.universe)
    universe = set(universe_names)
    sectors = load_sectors(args.universe)
    db_path_or_url = args.db
    db_path = db_path_or_url if not str(db_path_or_url).startswith("sqlite:") else DEFAULT_DB
    signals = load_signals(db_path, universe_names, start=args.start, end=args.end)
    prices = load_prices(db_path, universe_names, start=args.start, end=args.end)
    source_db_url = _sqlite_url(db_path_or_url)
    gate_db_url = _sqlite_url(args.gate_db)
    gate_rows = (
        _load_gate_rows(args.gate_rows_json)
        if args.gate_rows_json
        else _record_gate_rows(
            gate_db_url=gate_db_url,
            source_db_url=source_db_url,
            as_of=args.end,
            horizon_days=args.horizon_days,
            symbols=sorted(universe),
        )
    )
    report = build_report(
        signals=signals,
        prices=prices,
        universe=universe,
        sectors=sectors,
        gate_rows=gate_rows,
        start=args.start,
        end=args.end,
        source_db=source_db_url,
        gate_db=gate_db_url,
        test2_state_path=DEFAULT_STATE,
        writes_isolated_gate_db=args.gate_rows_json is None,
    )
    write_artifacts(report, json_output=json_output, markdown_output=markdown_output)
    if args.print:
        print(report_to_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
