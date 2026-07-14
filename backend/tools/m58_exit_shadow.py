"""M58 exit-parameter shadow arm for test2 v2 (owner-authorized option B, 2026-07-03).

M21.4 decision (`paper_trading/test2.md`): test2 v2 does **not** change
production exit parameters -- trailing ATR x2.5 / no floating take-profit
stays exactly as-is, single variable, still attributable. The M58 holdout
adjudication separately found variant (3) -- trailing x3.5 + a 10%
retrace-from-peak floating take-profit (``ExitVariant(3.5, "drawdown_10")``)
-- the winning candidate on the holdout window.

This tool is the shadow arm that lets that candidate keep proving (or
disproving) itself against live test2 v2 forward data for 4-6 weeks without
touching production: it replays the test2 v2 ledger window twice through the
exact same ``simulate_exit`` implementation ``m58_exit_sweep`` already uses
for the large-sample sweep and the test2 replay comparison (``B部分`` of that
tool's 14-variant ledger) -- once with the current rule, once with the
shadow candidate -- and reports where they diverge.

Both variants are hardcoded (``CURRENT_VARIANT`` / ``SHADOW_VARIANT``) and are
not exposed as CLI flags or function parameters: this tool answers exactly
one pre-registered question, not a new parameter-sweep surface.

Read/write boundary
--------------------
- Reads: ``mingcang.db`` prices/signals (read-only ``sqlite3`` connections via
  ``paper_trading.test2_ab_data.connect_ro``, ``mode=ro&immutable=1``) and
  ``paper_trading/test2_universe.json``.
- Writes: only JSON/Markdown snapshot reports and the append-only shadow
  history JSONL, all under ``/private/tmp``. This tool never opens
  ``paper_trading/test2_ab_state.json`` (or any other test2 ledger/state
  file) for writing, and never touches production config.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.tools.m58_exit_sweep import (
    ExitVariant,
    _connect_readonly,
    _max_price_date,
    _price_rows_for_holding,
    current_trailing_state,
    run_test2_comparison,
)

OUTPUT_JSON = Path("/private/tmp/m58_exit_shadow_report.json")
OUTPUT_MD = Path("/private/tmp/m58_exit_shadow_report.md")
HISTORY_PATH = Path("/private/tmp/m58_exit_shadow_history.jsonl")

# Hardcoded, non-negotiable per the owner's option-B decision (2026-07-03):
# production stays x2.5/none; the shadow arm is x3.5/drawdown_10 (the M58
# holdout-adjudication winner, variant (3)). Nothing in this module accepts
# an alternate pair.
CURRENT_VARIANT = ExitVariant(2.5, "none")
SHADOW_VARIANT = ExitVariant(3.5, "drawdown_10")


def v2_window(*, db_path: Path) -> tuple[str, str]:
    """Resolve the test2 v2 replay window: v2 start through latest priced date.

    ``start`` comes from ``backend.backtest.test2_models.START_DATE`` -- the
    single source of truth test2_ab_runner/test2_ab_cli already use for the
    v2 epoch boundary (reset 2026-07-03 per the v1/v2 epoch split in
    `test2.md`). This module only reads that constant; it never writes it.
    """
    from backend.backtest.test2_models import START_DATE

    con = _connect_readonly(db_path)
    try:
        end = _max_price_date(con)
    finally:
        con.close()
    return START_DATE, end


def _open_holding_shadow_lines(
    open_holdings: list[dict[str, Any]],
    *,
    price_dates: dict[str, list[str]],
    prices: dict[tuple[str, str], Any],
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for holding in open_holdings:
        rows = _price_rows_for_holding(
            holding["symbol"],
            holding["entry_date"],
            holding["entry_price"],
            holding.get("stop_loss"),
            price_dates=price_dates,
            prices=prices,
        )
        if rows is None:
            continue
        current_state = current_trailing_state(rows, CURRENT_VARIANT)
        shadow_state = current_trailing_state(rows, SHADOW_VARIANT)
        rows_out.append(
            {
                "symbol": holding["symbol"],
                "name": holding.get("name"),
                "entry_date": holding["entry_date"],
                "entry_price": holding["entry_price"],
                "as_of_date": current_state.as_of_date,
                "current_stop_line": current_state.stop_line,
                "current_still_open": current_state.still_open,
                "shadow_stop_line": shadow_state.stop_line,
                "shadow_drawdown_line": shadow_state.drawdown_line,
                "shadow_still_open": shadow_state.still_open,
                "stop_line_delta": round(shadow_state.stop_line - current_state.stop_line, 4),
            }
        )
    return rows_out


def build_shadow_report(
    *,
    db_path: Path,
    universe_path: Path,
    run_date: str | None = None,
) -> dict[str, Any]:
    from paper_trading.test2_ab_data import DEFAULT_UNIVERSE, load_prices, load_universe

    universe_path = Path(universe_path) if universe_path else DEFAULT_UNIVERSE
    start, end = v2_window(db_path=db_path)

    comparison = run_test2_comparison(
        {},
        db_path=db_path,
        universe_path=universe_path,
        start=start,
        end=end,
        variants=[CURRENT_VARIANT, SHADOW_VARIANT],
    )

    current_result = comparison["results"][CURRENT_VARIANT.key]
    shadow_result = comparison["results"][SHADOW_VARIANT.key]
    current_arms = current_result["arms"]
    shadow_arms = shadow_result["arms"]
    trade_diffs = shadow_result.get("trade_differences_vs_baseline", [])

    arm_summary: dict[str, Any] = {}
    total_open = 0
    for arm_key, current_arm in current_arms.items():
        shadow_arm = shadow_arms[arm_key]
        c_summary = current_arm["summary"]
        s_summary = shadow_arm["summary"]
        arm_summary[arm_key] = {
            "framework": current_arm["framework"],
            "current": c_summary,
            "shadow": s_summary,
            "delta_weighted_total_pct": round(
                s_summary["weighted_total_pct"] - c_summary["weighted_total_pct"], 2
            ),
        }
        total_open += c_summary["open"]

    open_position_lines: list[dict[str, Any]] = []
    no_divergence_yet = len(trade_diffs) == 0
    if no_divergence_yet and total_open > 0:
        universe = load_universe(universe_path)
        prices = load_prices(db_path, universe, start=start, end=end)
        price_dates: dict[str, list[str]] = {}
        for symbol, price_date in prices:
            if symbol in universe:
                price_dates.setdefault(symbol, []).append(price_date)
        for dates in price_dates.values():
            dates.sort()
        holdings_by_symbol = {
            holding["symbol"]: holding
            for current_arm in current_arms.values()
            for holding in current_arm["open_holdings"]
        }
        open_position_lines = _open_holding_shadow_lines(
            list(holdings_by_symbol.values()), price_dates=price_dates, prices=prices
        )

    resolved_run_date = run_date or date.today().isoformat()
    return {
        "meta": {
            "schema_version": "m58_exit_shadow.v1",
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "run_date": resolved_run_date,
            "authorization": "owner option B, 2026-07-03: production exit params unchanged; shadow-only for 4-6 weeks",
            "window": {"start": start, "end": end},
            "current_variant": CURRENT_VARIANT.key,
            "shadow_variant": SHADOW_VARIANT.key,
            "read_write_boundary": (
                "read-only against mingcang.db (mode=ro&immutable=1) and test2_universe.json; "
                "writes only /private/tmp report + history artifacts; never writes test2_ab_state.json "
                "or any production/test2 ledger file"
            ),
        },
        "arm_summary": arm_summary,
        "trade_differences": trade_diffs,
        "no_divergence_yet": no_divergence_yet,
        "open_position_count": total_open,
        "open_position_lines": open_position_lines,
    }


def append_history(record: dict[str, Any], *, history_path: Path = HISTORY_PATH) -> Path:
    """Append one run's summary to the shadow history JSONL.

    Idempotent per calendar day: any existing line whose ``run_date`` matches
    this record's ``run_date`` is dropped before the new line is appended, so
    re-running the tool the same day overwrites that day's entry instead of
    accumulating duplicates.
    """
    run_date = record["meta"]["run_date"]
    kept_lines: list[str] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("meta", {}).get("run_date") == run_date:
                continue
            kept_lines.append(line)
    kept_lines.append(json.dumps(record, ensure_ascii=False))
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
    return history_path


def _markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    lines = [
        "# M58 Exit-Parameter Shadow Arm (test2 v2)",
        "",
        f"- run_date: {meta['run_date']}",
        f"- window: {meta['window']['start']} ~ {meta['window']['end']}",
        f"- current_variant: {meta['current_variant']}",
        f"- shadow_variant: {meta['shadow_variant']}",
        f"- authorization: {meta['authorization']}",
        "",
        "## Arm Summary (weighted_total_pct)",
        "",
        "| arm | current | shadow | delta | closed(c/s) | open(c/s) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm_key, payload in report["arm_summary"].items():
        c, s = payload["current"], payload["shadow"]
        lines.append(
            f"| {arm_key} | {c['weighted_total_pct']:+.2f}% | {s['weighted_total_pct']:+.2f}% | "
            f"{payload['delta_weighted_total_pct']:+.2f}% | {c['closed']}/{s['closed']} | "
            f"{c['open']}/{s['open']} |"
        )
    lines.append("")
    if report["no_divergence_yet"]:
        if report["open_position_count"] == 0:
            lines.append("影子臂尚无分歧，且当前无持仓中标的。")
        else:
            lines.append(f"影子臂尚无分歧（无已平仓差异），持仓中 {report['open_position_count']} 笔的两套止损线对比：")
            lines.append("")
            lines.append("| symbol | name | entry_date | as_of | current_stop | shadow_stop | shadow_drawdown | stop_delta |")
            lines.append("|---|---|---|---|---:|---:|---:|---:|")
            for row in report["open_position_lines"]:
                lines.append(
                    f"| {row['symbol']} | {row['name']} | {row['entry_date']} | {row['as_of_date']} | "
                    f"{row['current_stop_line']:.4f} | {row['shadow_stop_line']:.4f} | "
                    f"{row['shadow_drawdown_line'] if row['shadow_drawdown_line'] is not None else '-'} | "
                    f"{row['stop_line_delta']:+.4f} |"
                )
    else:
        lines.append("### Trade Differences (shadow vs current)")
        lines.append("")
        lines.append("| arm | symbol | entry | current_exit | shadow_exit | delta_net | class |")
        lines.append("|---|---|---|---|---|---:|---|")
        for diff in report["trade_differences"]:
            lines.append(
                f"| {diff['arm']} | {diff['symbol']} | {diff['entry_date']} | "
                f"{diff['baseline_exit']} | {diff['candidate_exit']} | "
                f"{diff['delta_net_pct']:+.2f}% | {diff['classification']} |"
            )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], *, json_path: Path = OUTPUT_JSON, md_path: Path = OUTPUT_MD) -> tuple[Path, Path]:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "M58 exit-parameter shadow arm for test2 v2: replays the v2 window with the "
            "current exit rule (trailing x2.5/none) vs the holdout-winning shadow candidate "
            "(trailing x3.5/drawdown_10). Both variants are hardcoded; production is never touched."
        )
    )
    parser.add_argument("--db-path", type=Path, default=default_sqlite_path())
    parser.add_argument("--universe-path", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--md-out", type=Path, default=OUTPUT_MD)
    parser.add_argument("--history-path", type=Path, default=HISTORY_PATH)
    args = parser.parse_args(argv)

    from paper_trading.test2_ab_data import DEFAULT_UNIVERSE

    universe_path = args.universe_path or DEFAULT_UNIVERSE
    report = build_shadow_report(db_path=args.db_path, universe_path=universe_path)
    json_path, md_path = write_report(report, json_path=args.json_out, md_path=args.md_out)
    history_path = append_history(report, history_path=args.history_path)

    summary = {
        "json": str(json_path),
        "md": str(md_path),
        "history": str(history_path),
        "window": report["meta"]["window"],
        "no_divergence_yet": report["no_divergence_yet"],
        "open_position_count": report["open_position_count"],
        "arm_summary": {
            arm_key: {
                "current_weighted_total_pct": payload["current"]["weighted_total_pct"],
                "shadow_weighted_total_pct": payload["shadow"]["weighted_total_pct"],
                "delta": payload["delta_weighted_total_pct"],
            }
            for arm_key, payload in report["arm_summary"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
