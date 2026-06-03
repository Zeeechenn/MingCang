"""M42 — idempotent remediation CLI for hfq-contaminated price rows.

Root cause (M42): ~336–344 symbols had hfq (后复权) rows written on
2026-05-25/26 with adjustment=NULL, indistinguishable from normal qfq rows at
the column level.  Detection signal: close > K × median(preceding 10 closes).
After deletion the normal backfill re-fetches qfq data automatically (all
registered CN providers pass adjust='qfq').

Safety contract
---------------
- Default mode is DRY-RUN.  Pass ``--execute`` to write.
- ``--execute`` requires ``--db-url``.  The tool REFUSES to operate on the
  live settings.database_url path.
- Before any DELETE the tool backs up the SQLite file via shutil.copy2 to
  ``<original>.bak.<YYYYMMDD_HHMMSS>``.
- Never operates on /tmp/m42_prod_copy.db or the live stock-sage.db directly.
  The caller must supply an explicit --db-url pointing at a throwaway copy.
- Idempotent: running twice produces the same result (second run finds 0 rows).

Usage
-----
Dry-run (default — safe, no writes)::

    uv run python -m backend.tools.m42_remediate_hfq_contamination \\
        --db-url sqlite:////tmp/remediation_work.db

Execute (deletes contaminated rows after backup)::

    cp /tmp/m42_prod_copy.db /tmp/remediation_work.db
    uv run python -m backend.tools.m42_remediate_hfq_contamination \\
        --db-url sqlite:////tmp/remediation_work.db \\
        --execute

Detection predicates
--------------------
PRIMARY (write-time equivalent, stateless):
    close > K × median(preceding 10 closes)  AND  adjustment IS NULL
    K = 3.0  (same as HFQ_JUMP_RATIO_THRESHOLD in price_quality.py)

SECONDARY (snap-back — remediation only, requires next-day data):
    close > 1.5 × median(preceding 10 closes)
    AND adjustment IS NULL
    AND next_trading_day_close < 1.2 × median(preceding 10 closes)
    (catches subtler contamination where hfq/qfq ratio is 1.5–3×)

Both predicates are evaluated in Python after a single full-table scan so the
tool works on arbitrary DB copies without schema changes.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)

# Must match HFQ_JUMP_RATIO_THRESHOLD in price_quality.py.
_PRIMARY_RATIO: float = 3.0
_SECONDARY_RATIO: float = 1.5   # only used together with snap-back check
_SNAPBACK_RATIO: float = 1.2    # next-day close must be < this × median
_PRECEDING_WINDOW: int = 10
_MIN_PRECEDING: int = 5         # minimum history required to flag

# Refuse to operate on paths that look like live production databases.
_FORBIDDEN_PATH_FRAGMENTS = (
    "stock-sage.db",
    "m42_prod_copy.db",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sqlite_path_from_url(db_url: str) -> Path:
    """Extract the filesystem path from a sqlite:/// URL."""
    if not db_url.startswith("sqlite:///"):
        raise ValueError(f"Expected sqlite:/// URL, got: {db_url!r}")
    raw = db_url[len("sqlite:///"):]
    return Path(raw).resolve()


def _assert_not_forbidden(path: Path) -> None:
    name = path.name
    for fragment in _FORBIDDEN_PATH_FRAGMENTS:
        if fragment in name:
            raise ValueError(
                f"M42 remediation tool refuses to operate on {path!r} "
                f"(matches forbidden fragment {fragment!r}). "
                "Supply a throwaway copy: cp /tmp/m42_prod_copy.db /tmp/remediation_work.db"
            )


def _backup_db(path: Path) -> Path:
    """Copy *path* to <path>.bak.<timestamp> using shutil.copy2.  Returns backup path."""
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(f".db.bak.{stamp}")
    shutil.copy2(path, backup)
    logger.info("M42 backup: %s → %s", path, backup)
    return backup


# ---------------------------------------------------------------------------
# Detection logic (pure Python, no ORM dependency so tests stay hermetic)
# ---------------------------------------------------------------------------


def _load_all_prices(conn: sqlite3.Connection) -> dict[str, list[tuple[str, float, str | None]]]:
    """Return {symbol: [(date_str, close, adjustment), ...]} sorted by date ASC."""
    cur = conn.execute(
        "SELECT symbol, date, close, adjustment FROM prices ORDER BY symbol, date ASC"
    )
    result: dict[str, list[tuple[str, float, str | None]]] = {}
    for symbol, date_str, close, adjustment in cur.fetchall():
        result.setdefault(symbol, []).append((date_str, float(close), adjustment))
    return result


def _detect_contaminated(
    symbol_rows: dict[str, list[tuple[str, float, str | None]]],
    *,
    primary_ratio: float = _PRIMARY_RATIO,
    secondary_ratio: float = _SECONDARY_RATIO,
    snapback_ratio: float = _SNAPBACK_RATIO,
    preceding_window: int = _PRECEDING_WINDOW,
    min_preceding: int = _MIN_PRECEDING,
) -> list[tuple[str, str, str]]:
    """Return [(symbol, date_str, predicate_name), ...] for contaminated rows."""
    flagged: list[tuple[str, str, str]] = []

    for symbol, rows in symbol_rows.items():
        # Build a dict of date → index for snap-back lookup.
        date_to_idx: dict[str, int] = {r[0]: i for i, r in enumerate(rows)}

        for idx, (date_str, close, adjustment) in enumerate(rows):
            # Both predicates require adjustment IS NULL.
            if adjustment is not None:
                continue

            # Preceding window of closes (excluding current row).
            preceding_slice = rows[max(0, idx - preceding_window): idx]
            preceding_closes = [r[1] for r in preceding_slice if r[1] > 0]

            if len(preceding_closes) < min_preceding:
                continue

            med = median(preceding_closes)
            if med <= 0:
                continue

            ratio = close / med

            # PRIMARY predicate.
            if ratio > primary_ratio:
                flagged.append((symbol, date_str, "primary"))
                continue

            # SECONDARY predicate (snap-back, remediation only).
            if ratio > secondary_ratio:
                # Find next row for this symbol.
                next_idx = idx + 1
                if next_idx < len(rows):
                    next_close = rows[next_idx][1]
                    if next_close < snapback_ratio * med:
                        flagged.append((symbol, date_str, "secondary_snapback"))

    return flagged


# ---------------------------------------------------------------------------
# Core remediation function (testable independently of argparse)
# ---------------------------------------------------------------------------


def run_remediation(
    db_url: str,
    *,
    execute: bool = False,
    primary_ratio: float = _PRIMARY_RATIO,
    secondary_ratio: float = _SECONDARY_RATIO,
    snapback_ratio: float = _SNAPBACK_RATIO,
) -> dict[str, Any]:
    """Detect (and optionally delete) contaminated hfq rows.

    Returns a structured result dict following the m29 tool convention.
    """
    db_path = _sqlite_path_from_url(db_url)

    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    _assert_not_forbidden(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        symbol_rows = _load_all_prices(conn)
        flagged = _detect_contaminated(
            symbol_rows,
            primary_ratio=primary_ratio,
            secondary_ratio=secondary_ratio,
            snapback_ratio=snapback_ratio,
        )

        primary_flagged = [(s, d) for s, d, pred in flagged if pred == "primary"]
        secondary_flagged = [(s, d) for s, d, pred in flagged if pred == "secondary_snapback"]
        total_flagged = len(flagged)
        unique_symbols = len({s for s, _ in primary_flagged + secondary_flagged})

        result: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "schema_version": "m42_remediate_hfq_contamination.v1",
            "milestone": "M42",
            "run_mode": "execute" if execute else "dry_run",
            "writes_db": execute,
            "writes_tables": ["prices"] if execute else [],
            "production_unchanged": True,
            "db_path": str(db_path),
            "total_symbols_scanned": len(symbol_rows),
            "flagged_rows_total": total_flagged,
            "flagged_primary": len(primary_flagged),
            "flagged_secondary_snapback": len(secondary_flagged),
            "flagged_symbols_count": unique_symbols,
            "backup_path": None,
            "rows_deleted": 0,
            "rows_deleted_primary": 0,
            "rows_deleted_secondary": 0,
            "details": [
                {"symbol": s, "date": d, "predicate": pred}
                for s, d, pred in sorted(flagged, key=lambda x: (x[0], x[1]))
            ],
        }

        if execute and total_flagged > 0:
            backup_path = _backup_db(db_path)
            result["backup_path"] = str(backup_path)

            # Delete contaminated rows.
            primary_pairs = [(s, d) for s, d, pred in flagged if pred == "primary"]
            secondary_pairs = [(s, d) for s, d, pred in flagged if pred == "secondary_snapback"]

            deleted_primary = 0
            deleted_secondary = 0

            for symbol, date_str in primary_pairs:
                cur = conn.execute(
                    "DELETE FROM prices WHERE symbol=? AND date=? AND adjustment IS NULL",
                    (symbol, date_str),
                )
                deleted_primary += cur.rowcount

            for symbol, date_str in secondary_pairs:
                cur = conn.execute(
                    "DELETE FROM prices WHERE symbol=? AND date=? AND adjustment IS NULL",
                    (symbol, date_str),
                )
                deleted_secondary += cur.rowcount

            conn.commit()
            result["rows_deleted"] = deleted_primary + deleted_secondary
            result["rows_deleted_primary"] = deleted_primary
            result["rows_deleted_secondary"] = deleted_secondary
            logger.info(
                "M42 remediation: deleted %d rows (%d primary + %d secondary) "
                "across %d symbols from %s",
                result["rows_deleted"],
                deleted_primary,
                deleted_secondary,
                unique_symbols,
                db_path,
            )
        elif execute and total_flagged == 0:
            logger.info("M42 remediation: 0 contaminated rows found — nothing to delete (idempotent).")
        else:
            logger.info(
                "M42 dry-run: would delete %d rows across %d symbols. "
                "Re-run with --execute to apply.",
                total_flagged,
                unique_symbols,
            )

        return result

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M42 — detect and delete hfq-contaminated price rows from a DB copy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db-url",
        required=True,
        metavar="URL",
        help="SQLite URL of the DB COPY to operate on, e.g. sqlite:////tmp/remediation_work.db",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually delete contaminated rows (default: dry-run, no writes).",
    )
    parser.add_argument(
        "--primary-ratio",
        type=float,
        default=_PRIMARY_RATIO,
        metavar="K",
        help=f"Primary detection threshold: close > K × median(preceding 10). Default {_PRIMARY_RATIO}.",
    )
    parser.add_argument(
        "--secondary-ratio",
        type=float,
        default=_SECONDARY_RATIO,
        metavar="K2",
        help=f"Secondary (snap-back) lower bound. Default {_SECONDARY_RATIO}.",
    )
    parser.add_argument(
        "--snapback-ratio",
        type=float,
        default=_SNAPBACK_RATIO,
        metavar="K3",
        help=f"Next-day close must be < K3 × median to trigger snap-back flag. Default {_SNAPBACK_RATIO}.",
    )
    parser.add_argument(
        "--json-output",
        metavar="PATH",
        default=None,
        help="Write structured JSON result to this file path.",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()

    if args.execute and not args.db_url:
        parser.error("--execute requires --db-url")

    result = run_remediation(
        args.db_url,
        execute=args.execute,
        primary_ratio=args.primary_ratio,
        secondary_ratio=args.secondary_ratio,
        snapback_ratio=args.snapback_ratio,
    )

    output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(output)

    if args.json_output:
        out_path = Path(args.json_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        logger.info("M42 result written to %s", out_path)

    # Print human-readable summary.
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(
        f"\n[M42 {mode}] scanned {result['total_symbols_scanned']} symbols — "
        f"flagged {result['flagged_rows_total']} rows "
        f"({result['flagged_primary']} primary + {result['flagged_secondary_snapback']} snap-back) "
        f"across {result['flagged_symbols_count']} symbols",
        flush=True,
    )
    if args.execute:
        print(
            f"  deleted {result['rows_deleted']} rows  |  backup: {result['backup_path']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
