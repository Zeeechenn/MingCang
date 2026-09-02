"""M69 price-basis audit and guarded rebase planning.

The command is deliberately split into two safety levels:

* dry-run is the default, requires an explicit SQLite file, and opens it with
  ``mode=ro&immutable=1``;
* execute is allowed only on a resolved temporary-database path, requires the
  caller to pin both provider and adjustment basis, snapshots the database
  before writing, and applies all requested symbols in one transaction.

Production price history and trading ledgers are outside this P0-B1 tool's
write boundary. A production repair remains a separate P0-B2 maintenance
operation with explicit approval, ledger restatement, and a maintenance window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

logger = logging.getLogger("backend.tools.rebase_price_history")

_REQUIRED_PRICE_COLUMNS = {
    "asset_key", "symbol", "market", "currency", "date", "open", "high",
    "low", "close", "volume", "atr14", "source", "fetched_at", "adjustment",
}
_FETCH_COLUMNS = ("open", "high", "low", "close", "volume")


class RebaseSafetyError(ValueError):
    """Raised before a request can cross the P0-B1 safety boundary."""


@dataclass(frozen=True)
class SymbolAudit:
    symbol: str
    status: str  # clean | drift | skipped | blocked
    detail: str
    source: str | None = None
    adjustment: str | None = None
    fetched_rows: int = 0
    stored_sources: tuple[str, ...] = ()
    stored_rows: int = 0
    uncovered_stored_rows: int = 0
    cross_source: bool | None = None
    payload: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "detail": self.detail,
            "source": self.source,
            "adjustment": self.adjustment,
            "fetched_rows": self.fetched_rows,
            "stored_sources": list(self.stored_sources),
            "stored_rows": self.stored_rows,
            "uncovered_stored_rows": self.uncovered_stored_rows,
            "cross_source": self.cross_source,
            "drift": self.payload,
        }


@dataclass
class _SymbolPlan:
    audit: SymbolAudit
    asset_key: str
    market: str
    currency: str
    frame: Any | None = field(default=None, repr=False)
    fetched_at: Any | None = field(default=None, repr=False)


def _load_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    elif args.universe:
        with Path(args.universe).open(encoding="utf-8") as handle:
            payload = json.load(handle)
        symbols = [str(item["symbol"]).strip() for item in payload["stocks"]]
    else:  # argparse enforces this; keep the core helper fail-closed too.
        raise RebaseSafetyError("需要 --symbols 或 --universe")
    deduplicated = list(dict.fromkeys(symbols))
    if not deduplicated:
        raise RebaseSafetyError("标的列表为空")
    return deduplicated


def _resolve_db_path(value: str | Path) -> Path:
    raw = str(value)
    if raw.startswith("sqlite:///"):
        raw = raw[len("sqlite:///"):]
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"database path does not exist: {path}")
    return path


def _database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _assert_self_contained_snapshot(path: Path) -> None:
    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    existing = [str(item) for item in sidecars if item.exists()]
    if existing:
        raise RebaseSafetyError(
            "database has SQLite sidecars; create a consistent standalone snapshot first: "
            + ", ".join(existing)
        )


def _require_price_schema(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prices'"
    ).fetchone()
    if table is None:
        raise RebaseSafetyError("target database has no prices table")
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(prices)")}
    missing = sorted(_REQUIRED_PRICE_COLUMNS - columns)
    if missing:
        raise RebaseSafetyError(f"prices table missing required columns: {missing}")


def _temporary_roots() -> tuple[Path, ...]:
    roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
    return tuple(sorted(roots, key=str))


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _assert_temporary_execute_target(path: Path) -> None:
    resolved = path.resolve()
    if not any(_is_under(resolved, root) for root in _temporary_roots()):
        raise RebaseSafetyError(
            "P0-B1 execute is restricted to a resolved temporary database copy; "
            f"refusing {resolved}"
        )


def _validate_fetched_frame(frame: Any) -> None:
    if frame is None or frame.empty:
        raise RebaseSafetyError("provider returned no rows")
    missing = sorted(set(_FETCH_COLUMNS) - set(frame.columns))
    if missing:
        raise RebaseSafetyError(f"provider frame missing columns: {missing}")
    if not frame.index.is_unique:
        raise RebaseSafetyError("provider frame contains duplicate dates")

    seen_dates: set[str] = set()
    for raw_day, row in frame.iterrows():
        day = str(raw_day)[:10]
        try:
            parsed = date.fromisoformat(day)
        except ValueError as exc:
            raise RebaseSafetyError(f"provider frame has invalid date: {raw_day!r}") from exc
        if parsed.isoformat() != day or day in seen_dates:
            raise RebaseSafetyError(f"provider frame has ambiguous date: {raw_day!r}")
        seen_dates.add(day)

        values: dict[str, float] = {}
        for column in _FETCH_COLUMNS:
            try:
                value = float(row[column])
            except (TypeError, ValueError) as exc:
                raise RebaseSafetyError(f"{day} {column} is not numeric") from exc
            if not math.isfinite(value):
                raise RebaseSafetyError(f"{day} {column} is not finite")
            values[column] = value
        if min(values[name] for name in ("open", "high", "low", "close")) <= 0:
            raise RebaseSafetyError(f"{day} OHLC must be positive")
        if values["volume"] < 0:
            raise RebaseSafetyError(f"{day} volume must be non-negative")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise RebaseSafetyError(f"{day} high is below another OHLC value")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise RebaseSafetyError(f"{day} low is above another OHLC value")


def _stored_overlap(
    connection: sqlite3.Connection,
    *,
    asset_key: str,
    dates: list[str],
) -> tuple[dict[str, float], tuple[str, ...], int, int]:
    rows = connection.execute(
        "SELECT date, close, source FROM prices WHERE asset_key = ?",
        (asset_key,),
    ).fetchall()
    fetched_dates = set(dates)
    closes = {
        str(row["date"]): float(row["close"])
        for row in rows
        if row["close"] and str(row["date"]) in fetched_dates
    }
    sources = tuple(sorted({str(row["source"]) for row in rows if row["source"]}))
    uncovered = sum(str(row["date"]) not in fetched_dates for row in rows)
    return closes, sources, len(rows), uncovered


def _audit_symbol(
    symbol: str,
    market: str,
    connection: sqlite3.Connection,
    *,
    days: int,
    fetch_daily_fn: Callable[..., Any],
    expected_source: str | None,
    expected_adjustment: str | None,
) -> _SymbolPlan:
    from backend.data.market_profiles import (
        get_market_profile,
        instrument_key,
        normalize_market,
        normalize_symbol,
    )
    from backend.data.price_quality import classify_drift_source, detect_adjustment_basis_drift

    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    asset_key = instrument_key(market, symbol)
    profile = get_market_profile(market)
    try:
        frame = fetch_daily_fn(symbol, market, days=days)
        _validate_fetched_frame(frame)
    except Exception as exc:
        audit = SymbolAudit(symbol, "blocked", f"fetch/quality gate failed: {exc}")
        return _SymbolPlan(audit, asset_key, market, profile.currency)

    source_value = frame.attrs.get("source")
    adjustment_value = frame.attrs.get("adjustment")
    source = str(source_value).strip() if source_value is not None else ""
    adjustment = str(adjustment_value).strip() if adjustment_value is not None else ""
    if not source or not adjustment:
        audit = SymbolAudit(
            symbol, "blocked", "provider provenance requires source and adjustment",
            source=source or None, adjustment=adjustment or None, fetched_rows=len(frame),
        )
        return _SymbolPlan(audit, asset_key, market, profile.currency)
    if expected_source is not None and source != expected_source:
        audit = SymbolAudit(
            symbol, "blocked", f"source mismatch: expected {expected_source}, got {source}",
            source=source, adjustment=adjustment, fetched_rows=len(frame),
        )
        return _SymbolPlan(audit, asset_key, market, profile.currency)
    if expected_adjustment is not None and adjustment != expected_adjustment:
        audit = SymbolAudit(
            symbol, "blocked",
            f"adjustment mismatch: expected {expected_adjustment}, got {adjustment}",
            source=source, adjustment=adjustment, fetched_rows=len(frame),
        )
        return _SymbolPlan(audit, asset_key, market, profile.currency)

    ordered = frame.sort_index().copy()
    dates = [str(item)[:10] for item in ordered.index]
    fetched = {
        day: float(row["close"])
        for day, (_, row) in zip(dates, ordered.iterrows(), strict=True)
    }
    stored, stored_sources, stored_rows, uncovered = _stored_overlap(
        connection, asset_key=asset_key, dates=dates,
    )
    cross_source = classify_drift_source(source, stored_sources)
    if len(stored) < 3:
        audit = SymbolAudit(
            symbol, "skipped", f"overlap has only {len(stored)} rows",
            source=source, adjustment=adjustment, fetched_rows=len(ordered),
            stored_sources=stored_sources, stored_rows=stored_rows,
            uncovered_stored_rows=uncovered, cross_source=cross_source,
        )
        return _SymbolPlan(audit, asset_key, market, profile.currency)

    drift = detect_adjustment_basis_drift(fetched, stored)
    status = "drift" if drift.detected else "clean"
    detail = drift.describe() if drift.detected else f"{drift.compared_rows} overlapping rows agree"
    audit = SymbolAudit(
        symbol, status, detail, source=source, adjustment=adjustment,
        fetched_rows=len(ordered), stored_sources=stored_sources, stored_rows=stored_rows,
        uncovered_stored_rows=uncovered, cross_source=cross_source,
        payload=drift.to_payload(),
    )
    return _SymbolPlan(
        audit, asset_key, market, profile.currency, ordered, frame.attrs.get("fetched_at"),
    )


def _serialise_fetched_at(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _replace_symbol_prices(connection: sqlite3.Connection, plan: _SymbolPlan) -> tuple[int, int]:
    from backend.analysis.factors import add_all_factors

    if plan.frame is None:
        raise RebaseSafetyError(f"{plan.audit.symbol} has no validated frame")
    frame = add_all_factors(plan.frame.copy())
    dates = [str(item)[:10] for item in frame.index]
    placeholders = ",".join("?" for _ in dates)
    deleted = connection.execute(
        f"DELETE FROM prices WHERE asset_key = ? AND date IN ({placeholders})",
        (plan.asset_key, *dates),
    ).rowcount
    fetched_at = _serialise_fetched_at(plan.fetched_at)
    rows: list[tuple[Any, ...]] = []
    for raw_day, row in frame.iterrows():
        atr = row.get("atr14")
        atr_value = None if atr is None or not math.isfinite(float(atr)) else float(atr)
        rows.append((
            plan.audit.symbol,
            plan.asset_key,
            plan.market,
            plan.currency,
            str(raw_day)[:10],
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
            atr_value,
            plan.audit.source,
            fetched_at,
            plan.audit.adjustment,
        ))
    connection.executemany(
        "INSERT INTO prices (symbol, asset_key, market, currency, date, open, high, low, "
        "close, volume, atr14, source, fetched_at, adjustment) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return int(deleted), len(rows)


def _verify_replacement(connection: sqlite3.Connection, plan: _SymbolPlan) -> None:
    if plan.frame is None:
        raise RebaseSafetyError(f"{plan.audit.symbol} has no frame to verify")
    dates = [str(item)[:10] for item in plan.frame.index]
    placeholders = ",".join("?" for _ in dates)
    row = connection.execute(
        f"SELECT COUNT(*) AS rows, COUNT(DISTINCT date) AS dates, "
        f"MIN(source) AS min_source, MAX(source) AS max_source, "
        f"MIN(adjustment) AS min_adjustment, MAX(adjustment) AS max_adjustment "
        f"FROM prices WHERE asset_key = ? AND date IN ({placeholders})",
        (plan.asset_key, *dates),
    ).fetchone()
    if row is None or int(row["rows"]) != len(dates) or int(row["dates"]) != len(dates):
        raise RebaseSafetyError(f"{plan.audit.symbol} replacement row/date count mismatch")
    if row["min_source"] != plan.audit.source or row["max_source"] != plan.audit.source:
        raise RebaseSafetyError(f"{plan.audit.symbol} replacement source mismatch")
    if (
        row["min_adjustment"] != plan.audit.adjustment
        or row["max_adjustment"] != plan.audit.adjustment
    ):
        raise RebaseSafetyError(f"{plan.audit.symbol} replacement adjustment mismatch")


def _backup_database(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    with _connect_read_only(path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()
        if check != ("ok",):
            raise sqlite3.DatabaseError(f"backup quick_check failed: {check!r}")
    return backup


def run_rebase(
    db_path: str | Path,
    symbols: list[str],
    *,
    market: str = "CN",
    days: int = 120,
    execute: bool = False,
    expected_source: str | None = None,
    expected_adjustment: str | None = None,
    fetch_daily_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only plan and optionally apply it to a temporary DB copy."""
    if days < 3:
        raise RebaseSafetyError("days must be >= 3")
    target = _resolve_db_path(db_path)
    _assert_self_contained_snapshot(target)
    if execute:
        _assert_temporary_execute_target(target)
        if not expected_source or not expected_adjustment:
            raise RebaseSafetyError(
                "execute requires expected_source and expected_adjustment"
            )
    if fetch_daily_fn is None:
        from backend.data.market import fetch_daily

        fetch_daily_fn = fetch_daily

    before_hash = _database_sha256(target)
    with _connect_read_only(target) as connection:
        _require_price_schema(connection)
        plans = [
            _audit_symbol(
                symbol,
                market,
                connection,
                days=days,
                fetch_daily_fn=fetch_daily_fn,
                expected_source=expected_source,
                expected_adjustment=expected_adjustment,
            )
            for symbol in list(dict.fromkeys(symbols))
        ]

    result: dict[str, Any] = {
        "schema_version": "price_basis_rebase_plan.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_mode": "execute" if execute else "dry_run",
        "production_unchanged": True,
        "db_path": str(target),
        "database_sha256_before": before_hash,
        "database_sha256_after": _database_sha256(target),
        "expected_source": expected_source,
        "expected_adjustment": expected_adjustment,
        "audits": [plan.audit.to_payload() for plan in plans],
        "counts": {
            status: sum(plan.audit.status == status for plan in plans)
            for status in ("clean", "drift", "skipped", "blocked")
        },
        "writes_db": False,
        "writes_tables": [],
        "backup_path": None,
        "rows_deleted": 0,
        "rows_inserted": 0,
    }
    if result["database_sha256_after"] != before_hash:
        raise RebaseSafetyError("database changed during read-only planning")
    _assert_self_contained_snapshot(target)
    if not execute:
        return result

    unsafe = [plan.audit for plan in plans if plan.audit.status in {"skipped", "blocked"}]
    if unsafe:
        details = "; ".join(f"{item.symbol}: {item.detail}" for item in unsafe)
        raise RebaseSafetyError(f"execute blocked by incomplete plans: {details}")
    drifted = [plan for plan in plans if plan.audit.status == "drift"]
    uncovered = [plan.audit for plan in drifted if plan.audit.uncovered_stored_rows]
    if uncovered:
        details = "; ".join(
            f"{item.symbol}: {item.uncovered_stored_rows} stored rows outside fetched window"
            for item in uncovered
        )
        raise RebaseSafetyError(f"execute requires full stored-history coverage: {details}")
    if not drifted:
        return result
    if _database_sha256(target) != before_hash:
        raise RebaseSafetyError("database changed after planning; refusing stale plan")

    backup = _backup_database(target)
    deleted = inserted = 0
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        _require_price_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        for plan in drifted:
            symbol_deleted, symbol_inserted = _replace_symbol_prices(connection, plan)
            deleted += symbol_deleted
            inserted += symbol_inserted
        for plan in drifted:
            _verify_replacement(connection, plan)
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise sqlite3.DatabaseError(f"target quick_check failed: {check!r}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    result.update({
        "writes_db": True,
        "writes_tables": ["prices"],
        "backup_path": str(backup),
        "rows_deleted": deleted,
        "rows_inserted": inserted,
        "database_sha256_after": _database_sha256(target),
    })
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        required=True,
        help="Explicit SQLite file or sqlite:/// URL. Dry-run opens it immutable/read-only.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", help="Comma-separated symbols")
    group.add_argument("--universe", help="Universe JSON path")
    parser.add_argument("--market", default="CN")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument(
        "--execute", "--apply", dest="execute", action="store_true",
        help="Write only to a temporary DB copy; default is dry-run.",
    )
    parser.add_argument("--expected-source", help="Required in execute mode")
    parser.add_argument("--expected-adjustment", help="Required in execute mode")
    parser.add_argument("--json-output", help="Optional structured report path")
    return parser


def _result_exit_code(result: dict[str, Any], *, execute: bool) -> int:
    counts = result["counts"]
    if counts["blocked"] or counts["skipped"]:
        return 2
    return 1 if not execute and counts["drift"] else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.execute and (not args.expected_source or not args.expected_adjustment):
        parser.error("--execute requires --expected-source and --expected-adjustment")
    try:
        result = run_rebase(
            args.db,
            _load_symbols(args),
            market=args.market,
            days=args.days,
            execute=args.execute,
            expected_source=args.expected_source,
            expected_adjustment=args.expected_adjustment,
        )
    except (FileNotFoundError, RebaseSafetyError, sqlite3.DatabaseError) as exc:
        parser.error(str(exc))
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_output:
        output = Path(args.json_output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    return _result_exit_code(result, execute=args.execute)


if __name__ == "__main__":
    sys.exit(main())
