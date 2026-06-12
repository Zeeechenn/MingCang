"""Build the M41 read-only probe health ledger.

Default behavior aggregates existing probe JSON files. Passing ``--run-probes``
explicitly runs side-effect-free external probes before writing the ledger.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.data.external_sources import probe_external_sources
from backend.data.global_data import (
    build_probe_health_ledger,
    load_probe_summaries,
    probe_summary_from_payload,
)

DEFAULT_OUTPUT = Path("/private/tmp/mingcang_m41_probe_health_ledger.json")
DEFAULT_SYMBOLS = {
    "CN": ["600519"],
    "HK": ["700", "9988"],
    "US": ["AAPL", "MSFT"],
}


def _json_default(value: Any) -> str:
    return str(value)


def _parse_market_symbol(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("use MARKET:SYMBOL, e.g. US:AAPL")
    market, symbol = value.split(":", 1)
    market = market.upper().strip()
    symbol = symbol.strip()
    if market not in {"CN", "HK", "US"}:
        raise argparse.ArgumentTypeError("market must be CN, HK, or US")
    if not symbol:
        raise argparse.ArgumentTypeError("symbol is required")
    return market, symbol


def _probe_summaries(targets: list[tuple[str, str]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for market, symbol in targets:
        probes = probe_external_sources(symbol=symbol, market=market)
        summaries.append(probe_summary_from_payload(probes, market=market, symbol=symbol))
    return summaries


def _default_targets() -> list[tuple[str, str]]:
    return [
        (market, symbol)
        for market, symbols in DEFAULT_SYMBOLS.items()
        for symbol in symbols
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build M41 probe health ledger")
    parser.add_argument(
        "--input-json",
        action="append",
        default=[],
        help="existing JSON payload with probe_summary or summary rows; may be repeated",
    )
    parser.add_argument(
        "--market-symbol",
        action="append",
        type=_parse_market_symbol,
        default=[],
        help="explicit probe target used with --run-probes, e.g. HK:700",
    )
    parser.add_argument("--run-probes", action="store_true", help="explicitly run side-effect-free network probes")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="JSON output path, defaults to /private/tmp")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    summaries = load_probe_summaries([Path(path) for path in args.input_json])
    if args.run_probes:
        summaries.extend(_probe_summaries(args.market_symbol or _default_targets()))
    ledger = build_probe_health_ledger(summaries, generated_at=datetime.now(UTC).isoformat())
    ledger["safety"] = {
        "database_writes_attempted": False,
        "scheduler_registered": False,
        "network_probes_attempted": bool(args.run_probes),
        "output_scope": "operator_selected_file",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return ledger


if __name__ == "__main__":
    main()
