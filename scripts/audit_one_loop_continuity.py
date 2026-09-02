#!/usr/bin/env python3
"""Run the Stage-6 One Loop continuity audit against an explicit SQLite DB."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Direct execution sets sys.path[0] to ``scripts/`` rather than the repository
# root.  Add the root before importing the backend package so this read-only
# CLI works from any current working directory without requiring PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ops.one_loop_continuity import (
    DEFAULT_IMPLEMENTATION_SINCE,
    DEFAULT_REQUIRED_DAYS,
    ContinuityAuditError,
    audit_one_loop_continuity,
    require_canonical_implementation_since,
    to_json,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only fail-closed One Loop continuity audit. "
            "Default behavior prints JSON to stdout; use --output for an explicit file, "
            "preferably under /private/tmp."
        )
    )
    parser.add_argument("--db", required=True, help="Explicit SQLite DB path opened with mode=ro&immutable=1.")
    parser.add_argument(
        "--implementation-since",
        default=DEFAULT_IMPLEMENTATION_SINCE,
        help=(
            "Inclusive ISO date for post-implementation evidence; older rows are ignored. "
            f"Must equal the canonical One Loop start date ({DEFAULT_IMPLEMENTATION_SINCE}); "
            "a different window requires a reviewed code migration."
        ),
    )
    parser.add_argument("--required-days", type=int, default=DEFAULT_REQUIRED_DAYS)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Root used to resolve relative artifact paths.",
    )
    parser.add_argument(
        "--output",
        help="Optional caller-selected JSON output path. Without this flag, no files are written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        implementation_since = require_canonical_implementation_since(
            args.implementation_since
        )
        result = audit_one_loop_continuity(
            db_path=args.db,
            implementation_since=implementation_since,
            required_days=args.required_days,
            repo_root=args.repo_root,
        )
        payload = to_json(result)
    except (ContinuityAuditError, FileNotFoundError, OSError) as exc:
        print(f"continuity audit failed: {exc}", file=sys.stderr)
        return 2
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
