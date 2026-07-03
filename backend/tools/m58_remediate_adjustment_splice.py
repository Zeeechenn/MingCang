"""M58 — idempotent remediation CLI for adjustment-basis-splice contamination.

Root cause (M58, blocking pre-requisite noted in ROADMAP): the M42 write-time
guard (``check_adjustment_basis_jump`` in ``backend/data/price_quality.py``)
only ever checked the *up*-direction (close > K x median(preceding 10
closes)).  A batch of backfills around 2026-05-27..2026-06-29 spliced together
rows fetched under incompatible ``adjust=`` bases (``qfq`` vs
``forward_additive`` vs unlabeled ``None``) for the same symbols, and some of
those splices present as a *downward* single-day jump (ratio as low as
~0.047x observed in production data) which the up-only guard could never
catch.  The write-time guard itself was fixed symmetrically in M58 (see
``price_quality.check_adjustment_basis_jump`` / ``DOWN_SPLICE_WINDOW``); this
tool is the M42-style remediation companion that finds and removes rows
*already* written before that fix landed.

Detection predicate
--------------------
For every (symbol, date) row (scanning oldest -> newest per symbol):

    ratio = close / median(preceding up-to-10 closes)
    flagged when (ratio > 3 OR ratio < 1/3)
             AND adjustment != previous_row.adjustment

Note that "!=" already covers "one side NULL, the other labeled" (True) as
well as "both labeled but different" (True); it deliberately does NOT flag
"both sides NULL", since that is just normal pre-adjustment-tracking history,
not a splice signal.

This mirrors M42's PRIMARY predicate but is symmetric (catches both the
up-direction hfq-scale splice AND the down-direction splice) and additionally
requires an adjustment-label discontinuity across the transition, so a
genuine (rare) 3x+ rally/crash on a *stable* adjustment basis is never
touched — only rows where the data pipeline itself flipped basis are
candidates.

A SECONDARY, report-only predicate also runs: transitions with a milder ratio
(1/3 <= ratio < 0.8, or 1.25 < ratio <= 3) alongside an adjustment-label
discontinuity.  These are NOT auto-remediated because they are consistent
with a genuine corporate action (e.g. a 10-for-10 bonus share issue roughly
halves the price, landing right in this band) rather than data corruption —
a real ~90%+ single-day move is not achievable through any legitimate A-share
mechanism, but a ~30-50% move is. These rows are listed in the report under
``suspect_transitions`` for a human (leader) decision and are never deleted
by this tool, matching the M58 task instruction to leave ambiguous
"real ex-rights?" cases unresolved rather than guess.

Safety contract (same as M42)
------------------------------
- Default mode is DRY-RUN.  Pass ``--execute`` to write.
- Unlike M42 (which mandated running only against a throwaway DB copy), M58
  is designed to run directly against the live ``mingcang.db`` — the
  mandatory pre-delete backup (see below) is what makes that safe, per the
  explicit task instruction to back up, dry-run, cross-check, then apply.
- Before any DELETE the tool backs up the SQLite file via shutil.copy2 to
  ``~/.stock-sage/backups/<dbname>.<YYYYMMDD_HHMMSS>.bak`` (never overwrites
  an existing backup).
- Idempotent: running twice produces the same result (second run finds 0
  primary-flagged rows).
- Deletion (not soft-marking) was chosen to match the M42 precedent exactly:
  the normal backfill path re-fetches clean qfq data automatically once the
  contaminated row is gone, and the pre-delete backup makes this trivially
  reversible (copy the backup back over the live DB) — this is the "more
  conservative, more easily reversible" option the M42 pattern already
  validated, versus soft-marking rows which would require every downstream
  reader to be updated to respect the mark.

Usage
-----
Dry-run (default — safe, no writes)::

    uv run python -m backend.tools.m58_remediate_adjustment_splice \\
        --db-url sqlite:////Users/zeeechenn/mingcang/mingcang.db

Execute (backs up, then deletes primary-flagged rows)::

    uv run python -m backend.tools.m58_remediate_adjustment_splice \\
        --db-url sqlite:////Users/zeeechenn/mingcang/mingcang.db --execute
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

_RATIO_THRESHOLD: float = 3.0          # must match HFQ_JUMP_RATIO_THRESHOLD
_SUSPECT_LOW: float = 0.8              # secondary band lower/upper bounds
_SUSPECT_HIGH: float = 1.25
_PRECEDING_WINDOW: int = 10
_MIN_PRECEDING: int = 5

_DEFAULT_BACKUP_DIR = Path.home() / ".stock-sage" / "backups"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sqlite_path_from_url(db_url: str) -> Path:
    if not db_url.startswith("sqlite:///"):
        raise ValueError(f"Expected sqlite:/// URL, got: {db_url!r}")
    raw = db_url[len("sqlite:///"):]
    return Path(raw).resolve()


def _backup_db(path: Path, backup_dir: Path = _DEFAULT_BACKUP_DIR) -> Path:
    """Copy *path* into backup_dir as <name>.<timestamp>.bak. Never overwrites."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{path.name}.{stamp}.bak"
    suffix = 0
    while backup.exists():
        suffix += 1
        backup = backup_dir / f"{path.name}.{stamp}_{suffix}.bak"
    shutil.copy2(path, backup)
    logger.info("M58 backup: %s -> %s", path, backup)
    return backup


# ---------------------------------------------------------------------------
# Detection logic (pure Python, hermetic — testable without a DB fixture)
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


def detect_splice_transitions(
    symbol_rows: dict[str, list[tuple[str, float, str | None]]],
    *,
    ratio_threshold: float = _RATIO_THRESHOLD,
    suspect_low: float = _SUSPECT_LOW,
    suspect_high: float = _SUSPECT_HIGH,
    preceding_window: int = _PRECEDING_WINDOW,
    min_preceding: int = _MIN_PRECEDING,
    window_start: str | None = None,
    window_end: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (primary_flagged, suspect) transition records.

    Both lists contain dicts with keys: symbol, date, prev_date, close,
    prev_close, median_preceding, ratio, adjustment, prev_adjustment.

    ``window_start``/``window_end`` (ISO date strings, inclusive) restrict
    detection to a date range — used to keep this tool scoped to the known
    M58 contamination window instead of also sweeping up unrelated historical
    events (e.g. an unrelated 2023-05-10 anomaly cluster observed during
    investigation, which is out of scope for this milestone and is reported
    separately, not remediated here).
    """
    primary: list[dict[str, Any]] = []
    suspect: list[dict[str, Any]] = []

    for symbol, rows in symbol_rows.items():
        for idx in range(1, len(rows)):
            date_str, close, adjustment = rows[idx]
            if window_start and date_str < window_start:
                continue
            if window_end and date_str > window_end:
                continue

            prev_date, prev_close, prev_adjustment = rows[idx - 1]

            # NOTE: comparing with `!=` already covers "one side NULL, other
            # labeled" (that inequality is True) as well as "both labeled but
            # different" — it does NOT flag "both sides NULL", which is the
            # normal case for the bulk of pre-adjustment-tracking history and
            # must NOT be treated as a splice signal on its own.
            adjustment_discontinuous = adjustment != prev_adjustment
            if not adjustment_discontinuous:
                continue

            preceding_slice = rows[max(0, idx - preceding_window): idx]
            preceding_closes = [r[1] for r in preceding_slice if r[1] and r[1] > 0]
            if len(preceding_closes) < min_preceding:
                continue

            med = median(preceding_closes)
            if med <= 0 or close <= 0:
                continue

            ratio = close / med
            record = {
                "symbol": symbol,
                "date": date_str,
                "prev_date": prev_date,
                "close": close,
                "prev_close": prev_close,
                "median_preceding": med,
                "ratio": ratio,
                "adjustment": adjustment,
                "prev_adjustment": prev_adjustment,
            }

            if ratio > ratio_threshold or ratio < 1.0 / ratio_threshold:
                primary.append(record)
            elif ratio < suspect_low or ratio > suspect_high:
                suspect.append(record)

    return primary, suspect


# ---------------------------------------------------------------------------
# Core remediation function (testable independently of argparse)
# ---------------------------------------------------------------------------


def run_remediation(
    db_url: str,
    *,
    execute: bool = False,
    ratio_threshold: float = _RATIO_THRESHOLD,
    suspect_low: float = _SUSPECT_LOW,
    suspect_high: float = _SUSPECT_HIGH,
    window_start: str | None = "2026-05-20",
    window_end: str | None = "2026-07-05",
    backup_dir: Path = _DEFAULT_BACKUP_DIR,
) -> dict[str, Any]:
    """Detect (and optionally delete) adjustment-basis-splice rows.

    Deletion removes only the *flagged row itself* (the row on the far side
    of the splice, matching M42's per-row DELETE style), not a wider
    "interval" — because the flagged row is precisely the row whose close no
    longer belongs to a consistent adjustment basis with its neighbours; once
    it is gone, the normal backfill path re-fetches a clean qfq row for that
    date automatically (same mechanism M42 relied on).
    """
    db_path = _sqlite_path_from_url(db_url)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        symbol_rows = _load_all_prices(conn)
        primary, suspect = detect_splice_transitions(
            symbol_rows,
            ratio_threshold=ratio_threshold,
            suspect_low=suspect_low,
            suspect_high=suspect_high,
            window_start=window_start,
            window_end=window_end,
        )

        primary_symbols = sorted({r["symbol"] for r in primary})
        suspect_symbols = sorted({r["symbol"] for r in suspect})

        result: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "schema_version": "m58_remediate_adjustment_splice.v1",
            "milestone": "M58",
            "run_mode": "execute" if execute else "dry_run",
            "writes_db": execute,
            "writes_tables": ["prices"] if execute else [],
            "db_path": str(db_path),
            "window_start": window_start,
            "window_end": window_end,
            "total_symbols_scanned": len(symbol_rows),
            "primary_flagged_rows": len(primary),
            "primary_flagged_symbols": len(primary_symbols),
            "primary_symbols": primary_symbols,
            "suspect_flagged_rows": len(suspect),
            "suspect_flagged_symbols": len(suspect_symbols),
            "suspect_symbols": suspect_symbols,
            "backup_path": None,
            "rows_deleted": 0,
            "primary_details": sorted(primary, key=lambda r: (r["symbol"], r["date"])),
            "suspect_details": sorted(suspect, key=lambda r: (r["symbol"], r["date"])),
        }

        if execute and primary:
            backup_path = _backup_db(db_path, backup_dir=backup_dir)
            result["backup_path"] = str(backup_path)

            deleted = 0
            for rec in primary:
                cur = conn.execute(
                    "DELETE FROM prices WHERE symbol=? AND date=?",
                    (rec["symbol"], rec["date"]),
                )
                deleted += cur.rowcount
            conn.commit()
            result["rows_deleted"] = deleted
            logger.info(
                "M58 remediation: deleted %d rows across %d symbols from %s",
                deleted, len(primary_symbols), db_path,
            )
        elif execute and not primary:
            logger.info("M58 remediation: 0 primary-flagged rows — nothing to delete (idempotent).")
        else:
            logger.info(
                "M58 dry-run: would delete %d rows across %d symbols "
                "(+ %d suspect rows across %d symbols left for manual review). "
                "Re-run with --execute to apply.",
                len(primary), len(primary_symbols), len(suspect), len(suspect_symbols),
            )

        return result

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M58 — detect and delete adjustment-basis-splice rows from prices.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--db-url",
        required=True,
        metavar="URL",
        help="SQLite URL to operate on, e.g. sqlite:////Users/you/mingcang/mingcang.db",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually delete primary-flagged rows (default: dry-run, no writes).",
    )
    parser.add_argument("--ratio-threshold", type=float, default=_RATIO_THRESHOLD)
    parser.add_argument("--suspect-low", type=float, default=_SUSPECT_LOW)
    parser.add_argument("--suspect-high", type=float, default=_SUSPECT_HIGH)
    parser.add_argument("--window-start", type=str, default="2026-05-20")
    parser.add_argument("--window-end", type=str, default="2026-07-05")
    parser.add_argument(
        "--backup-dir",
        type=str,
        default=str(_DEFAULT_BACKUP_DIR),
        help=f"Directory for pre-delete backups. Default {_DEFAULT_BACKUP_DIR}",
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

    result = run_remediation(
        args.db_url,
        execute=args.execute,
        ratio_threshold=args.ratio_threshold,
        suspect_low=args.suspect_low,
        suspect_high=args.suspect_high,
        window_start=args.window_start,
        window_end=args.window_end,
        backup_dir=Path(args.backup_dir),
    )

    output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(output)

    if args.json_output:
        out_path = Path(args.json_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        logger.info("M58 result written to %s", out_path)

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(
        f"\n[M58 {mode}] scanned {result['total_symbols_scanned']} symbols in "
        f"[{result['window_start']}, {result['window_end']}] — "
        f"primary {result['primary_flagged_rows']} rows / {result['primary_flagged_symbols']} symbols, "
        f"suspect (not touched) {result['suspect_flagged_rows']} rows / {result['suspect_flagged_symbols']} symbols",
        flush=True,
    )
    if args.execute:
        print(f"  deleted {result['rows_deleted']} rows  |  backup: {result['backup_path']}", flush=True)


if __name__ == "__main__":
    main()
