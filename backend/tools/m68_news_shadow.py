"""M68 production-mirror CLI for the observe-only news pyramid."""
from __future__ import annotations

import argparse
import json
from datetime import date

from backend.data.database import SessionLocal, init_db
from backend.data.news_shadow import run_production_mirror, shadow_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run M68 news pyramid against production DB evidence without writing official signals."
    )
    parser.add_argument("--date", default=date.today().isoformat(), help="As-of date YYYY-MM-DD")
    parser.add_argument("--symbols", help="Comma-separated symbols; default active CN universe")
    parser.add_argument("--limit", type=int, default=None, help="Optional bounded trial size")
    parser.add_argument("--lookback", type=int, default=3)
    parser.add_argument("--tier", default="capable")
    parser.add_argument("--profile", default="production_mirror")
    parser.add_argument("--force", action="store_true", help="Recompute existing same-day rows in place")
    parser.add_argument("--report-only", action="store_true", help="Read persisted summary; no scoring")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()
    db = SessionLocal()
    try:
        if args.report_only:
            payload = {
                "ok": True,
                "schema_version": "m68.news-shadow.report.v1",
                **shadow_summary(db, as_of=args.date),
            }
        else:
            symbols = (
                [value.strip() for value in args.symbols.split(",") if value.strip()]
                if args.symbols
                else None
            )
            payload = run_production_mirror(
                as_of=args.date,
                db=db,
                symbols=symbols,
                limit=args.limit,
                profile=args.profile,
                tier=args.tier,
                lookback_days=args.lookback,
                force=args.force,
            )
    finally:
        db.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
