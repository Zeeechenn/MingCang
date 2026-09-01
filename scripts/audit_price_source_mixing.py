#!/usr/bin/env python3
"""Report price history stitched from multiple providers, per symbol.

M69 follow-up (2026-09-02 audit).  Adjustment-basis drift detection only ever
sees a symbol when a backfill happens to overlap stored rows, so it under-reports
splicing by construction: that audit found 47 drift events across 18 symbols
while 369 of 758 symbols actually held multi-provider history.  Each provider
carries its own adjustment basis, so every source boundary inside one series is
a potential seam.  This is therefore its own read-only data-quality metric, not
a by-product of drift detection.

Read-only.  Repairing a spliced series is an explicit operator decision — see
``backend.tools.rebase_price_history``, and rebase onto ONE provider over the
full history, not the default window (a short window just moves the seam).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.data.price_quality import summarize_source_mixing


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="SQLite DB path; opened read-only.")
    parser.add_argument("--market", help="Optional market filter, e.g. CN.")
    parser.add_argument("--worst-limit", type=int, default=10, help="How many worst offenders to list.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text summary.")
    parser.add_argument(
        "--fail-on-mixed",
        action="store_true",
        help="Exit 1 when any symbol holds multi-provider history (for CI/scheduled use).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path = Path(args.db).expanduser()
    if not path.exists():
        print(f"db not found: {path}", file=sys.stderr)
        return 2
    uri = f"file:{path}?mode=ro"
    sql = "SELECT symbol, source FROM prices"
    params: tuple[str, ...] = ()
    if args.market:
        sql += " WHERE market = ?"
        params = (args.market,)
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute(sql, params).fetchall()

    report = summarize_source_mixing(rows, worst_limit=args.worst_limit)
    if args.json:
        print(json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(report.describe())
        for count, symbols in sorted(report.distribution.items()):
            print(f"  {count} source(s): {symbols} symbols")
        if report.worst:
            print("\nworst offenders:")
            for symbol, sources in report.worst:
                print(f"  {symbol}: {', '.join(sources)}")
    return 1 if args.fail_on_mixed and not report.clean else 0


if __name__ == "__main__":
    raise SystemExit(main())
