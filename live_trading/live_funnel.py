#!/usr/bin/env python3
"""Fail-closed subset builder for the local Live Track.

This module never places orders and never writes the MingCang database.  Its
only write is the explicitly requested subset JSON after all safety checks pass.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

MAX_TOTAL_EXPOSURE = Decimal("0.80")


class SafetyViolation(RuntimeError):
    """A hard Live Track boundary failed; no subset may be written."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def build_live_subset(
    *,
    db_path: Path,
    live_universe_path: Path,
    test2_universe_path: Path,
    state_path: Path,
    trade_date: str,
    output_path: Path,
    threshold: float = 25.0,
) -> dict[str, Any]:
    """Build ``score > threshold OR held`` subset from read-only inputs."""

    input_paths = {
        db_path.resolve(),
        live_universe_path.resolve(),
        test2_universe_path.resolve(),
        state_path.resolve(),
    }
    if output_path.resolve() in input_paths:
        raise SafetyViolation("output path must differ from every input path")

    universe = _load_json(live_universe_path)
    test2_universe = _load_json(test2_universe_path)
    state = _load_json(state_path)
    stocks = {str(stock["symbol"]): stock for stock in universe["stocks"]}
    test2_symbols = {str(stock["symbol"]) for stock in test2_universe["stocks"]}
    overlap = sorted(set(stocks) & test2_symbols)
    if overlap:
        raise SafetyViolation(f"live/test2 universe overlap: {', '.join(overlap)}")
    state_as_of = str(state.get("as_of", ""))
    if state_as_of != trade_date:
        raise SafetyViolation(
            f"state as_of {state_as_of or 'missing'} does not match trade date {trade_date}"
        )
    holding_symbols = {str(position["symbol"]) for position in state["positions"]}
    holdings_outside_universe = sorted(holding_symbols - set(stocks))
    if holdings_outside_universe:
        raise SafetyViolation(
            f"holding outside live universe: {', '.join(holdings_outside_universe)}"
        )
    portfolio_value = Decimal(str(state["portfolio_value"]))
    if portfolio_value <= 0:
        raise SafetyViolation("portfolio_value must be positive")
    market_values = [
        Decimal(str(position["market_value"])) for position in state["positions"]
    ]
    if any(value < 0 for value in market_values):
        raise SafetyViolation("market_value must be non-negative")
    total_market_value = sum(
        market_values,
        start=Decimal("0"),
    )
    total_exposure = total_market_value / portfolio_value
    if total_exposure > MAX_TOTAL_EXPOSURE:
        raise SafetyViolation(
            "total exposure "
            f"{total_exposure:.2%} exceeds hard limit {MAX_TOTAL_EXPOSURE:.2%}"
        )

    with closing(_connect_read_only(db_path)) as con:
        rows = con.execute(
            """
            SELECT signal.symbol, signal.composite_score
            FROM signals AS signal
            JOIN (
                SELECT symbol, MAX(id) AS id
                FROM signals
                WHERE date = ?
                GROUP BY symbol
            ) AS latest
              ON latest.id = signal.id AND latest.symbol = signal.symbol
            """,
            (trade_date,),
        ).fetchall()
        fresh_symbols = {
            str(row[0])
            for row in con.execute(
                "SELECT DISTINCT symbol FROM prices WHERE date = ?",
                (trade_date,),
            ).fetchall()
        }
    scores = {
        str(symbol): float(score)
        for symbol, score in rows
        if symbol in stocks and score is not None
    }
    holdings_missing_bar = sorted(holding_symbols - fresh_symbols)
    if holdings_missing_bar:
        raise SafetyViolation(
            f"holding missing trade-date bar: {', '.join(holdings_missing_bar)}"
        )
    holdings_missing_signal = sorted(holding_symbols - set(scores))
    if holdings_missing_signal:
        raise SafetyViolation(
            f"holding missing trade-date signal: {', '.join(holdings_missing_signal)}"
        )
    stale_non_holdings = sorted(set(stocks) - holding_symbols - fresh_symbols)
    missing_signal_non_holdings = sorted(
        (set(stocks) - holding_symbols - set(scores)) & fresh_symbols
    )
    warnings = [
        f"non-holding {symbol} missing trade-date bar; excluded"
        for symbol in stale_non_holdings
    ]
    warnings.extend(
        f"non-holding {symbol} missing trade-date signal; excluded"
        for symbol in missing_signal_non_holdings
    )
    excluded_symbols = sorted(set(stale_non_holdings) | set(missing_signal_non_holdings))
    selected = [
        symbol
        for symbol in stocks
        if symbol in holding_symbols
        or (symbol in fresh_symbols and scores.get(symbol, float("-inf")) > threshold)
    ]
    payload = {
        "version": universe.get("version", "live"),
        "source": f"live_funnel_{trade_date}",
        "stocks": [stocks[symbol] for symbol in selected],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "holding_symbols": sorted(holding_symbols),
        "selected_symbols": selected,
        "total_exposure": float(total_exposure),
        "excluded_symbols": excluded_symbols,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fail-closed Live Track subset without writing the database"
    )
    parser.add_argument("--trade-date", required=True, help="Required market date (YYYY-MM-DD)")
    parser.add_argument("--db", required=True, type=Path, help="SQLite source opened read-only")
    parser.add_argument("--live-universe", required=True, type=Path)
    parser.add_argument("--test2-universe", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path, help="Private authoritative state JSON")
    parser.add_argument("--output", required=True, type=Path, help="Explicit subset JSON path")
    parser.add_argument("--threshold", type=float, default=25.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_live_subset(
            db_path=args.db,
            live_universe_path=args.live_universe,
            test2_universe_path=args.test2_universe,
            state_path=args.state,
            trade_date=args.trade_date,
            output_path=args.output,
            threshold=args.threshold,
        )
    except SafetyViolation as exc:
        print(f"[blocked] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
