"""Build independent P0-R cash-NAV evidence from a read-only One Loop snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from backend.backtest.nav_replay import DailyBar, ReplayConfig, SignalIntent, run_nav_replay
from backend.ops.one_loop_continuity import (
    DEFAULT_IMPLEMENTATION_SINCE,
    DEFAULT_REQUIRED_DAYS,
    ContinuityAuditError,
    audit_one_loop_continuity,
    require_canonical_implementation_since,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_snapshot(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    if any(item.exists() for item in sidecars):
        raise ValueError("P0-R requires a standalone SQLite snapshot without WAL/SHM sidecars")
    return path


def _connect_immutable(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _assert_temporary_output(path: Path) -> None:
    roots = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
    resolved = path.expanduser().resolve()
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError(f"P0-R output must stay under a temporary directory: {resolved}")


def _selected_complete_days(
    continuity: dict[str, Any],
    *,
    end: str | None = None,
) -> list[dict[str, Any]]:
    days = [
        item
        for item in continuity.get("days", [])
        if item.get("status") == "complete"
        and item.get("batch_id")
        and (end is None or str(item.get("date")) <= end)
    ]
    if not days:
        raise ValueError("continuity audit contains no complete authoritative days")
    return days


def _load_inputs(
    connection: sqlite3.Connection,
    days: list[dict[str, Any]],
) -> tuple[list[SignalIntent], list[DailyBar], dict[str, str], dict[str, Any]]:
    signals: list[SignalIntent] = []
    day_lineage: list[dict[str, Any]] = []
    for item in days:
        trade_date = str(item["date"])
        batch_id = str(item["batch_id"])
        rows = connection.execute(
            "SELECT symbol, composite_score, stop_loss, take_profit "
            "FROM signals WHERE date = ? ORDER BY composite_score DESC, symbol",
            (batch_id,),
        ).fetchall()
        day_lineage.append({
            "trade_date": trade_date,
            "batch_id": batch_id,
            "signal_rows": len(rows),
        })
        for row in rows:
            if row["symbol"] is None or row["composite_score"] is None:
                continue
            signals.append(SignalIntent(
                symbol=str(row["symbol"]),
                date=trade_date,
                score=float(row["composite_score"]),
                stop_loss=float(row["stop_loss"]) if row["stop_loss"] is not None else None,
                take_profit=(
                    float(row["take_profit"]) if row["take_profit"] is not None else None
                ),
            ))
    symbols = sorted({item.symbol for item in signals})
    if not symbols:
        raise ValueError("selected authoritative batches contain no usable signals")
    placeholders = ",".join("?" for _ in symbols)
    start = str(days[0]["date"])
    end = str(days[-1]["date"])
    price_rows = connection.execute(
        f"SELECT symbol, date, open, high, low, close, source, adjustment "
        f"FROM prices WHERE market = 'CN' AND symbol IN ({placeholders}) "
        "AND date >= ? AND date <= ? ORDER BY date, symbol",
        (*symbols, start, end),
    ).fetchall()
    bars = [
        DailyBar(
            symbol=str(row["symbol"]),
            date=str(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in price_rows
    ]
    stock_rows = connection.execute(
        f"SELECT symbol, industry FROM stocks WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchall()
    sectors = {
        str(row["symbol"]): str(row["industry"] or "未分类") for row in stock_rows
    }

    lineage_by_symbol: dict[str, dict[str, Any]] = {
        symbol: {"sources": set(), "adjustments": set(), "rows": 0} for symbol in symbols
    }
    for row in price_rows:
        lineage = lineage_by_symbol[str(row["symbol"])]
        lineage["rows"] += 1
        lineage["sources"].add(str(row["source"]) if row["source"] else "missing")
        lineage["adjustments"].add(
            str(row["adjustment"]) if row["adjustment"] else "missing"
        )
    basis_issues: list[dict[str, Any]] = []
    serial_lineage: dict[str, Any] = {}
    for symbol, raw in lineage_by_symbol.items():
        sources = sorted(raw["sources"])
        adjustments = sorted(raw["adjustments"])
        serial_lineage[symbol] = {
            "sources": sources,
            "adjustments": adjustments,
            "rows": raw["rows"],
        }
        reasons = []
        if raw["rows"] == 0:
            reasons.append("missing_prices")
        if len(sources) != 1 or "missing" in sources:
            reasons.append("mixed_or_missing_source")
        if len(adjustments) != 1 or "missing" in adjustments:
            reasons.append("mixed_or_missing_adjustment")
        if reasons:
            basis_issues.append({"symbol": symbol, "reasons": reasons, **serial_lineage[symbol]})
    lineage = {
        "selected_days": day_lineage,
        "price_window": {"start": start, "end": end},
        "price_by_symbol": serial_lineage,
        "price_basis_issues": basis_issues,
    }
    return signals, bars, sectors, lineage


def build_evidence(
    db_path: str | Path,
    *,
    repo_root: str | Path,
    implementation_since: str = DEFAULT_IMPLEMENTATION_SINCE,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    end: str | None = None,
    config: ReplayConfig | None = None,
    continuity_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = _resolve_snapshot(db_path)
    before_hash = _sha256(snapshot)
    continuity = continuity_result or audit_one_loop_continuity(
        db_path=snapshot,
        implementation_since=implementation_since,
        required_days=required_days,
        repo_root=repo_root,
    )
    days = _selected_complete_days(continuity, end=end)
    with _connect_immutable(snapshot) as connection:
        signals, bars, sectors, lineage = _load_inputs(connection, days)
    replay = run_nav_replay(signals, bars, sectors=sectors, config=config)
    after_hash = _sha256(snapshot)
    if before_hash != after_hash:
        raise RuntimeError("snapshot changed during P0-R replay")

    price_basis_issues = lineage["price_basis_issues"]
    continuity_complete = continuity.get("status") == "complete"
    if price_basis_issues:
        status = "blocked_price_basis"
    elif not continuity_complete:
        status = "evidence_only_continuity_open"
    else:
        status = "evidence_only"
    return {
        "schema_version": "p0r_nav_evidence.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": status,
        "production_unchanged": True,
        "promotion_eligible": False,
        "writes_db": False,
        "writes_tables": [],
        "snapshot": {
            "path": str(snapshot),
            "sha256_before": before_hash,
            "sha256_after": after_hash,
            "open_mode": "ro_immutable",
        },
        "continuity": {
            "status": continuity.get("status"),
            "implementation_since": continuity.get("implementation_since"),
            "required_days": continuity.get("required_days"),
            "selected_complete_days": len(days),
        },
        "lineage": lineage,
        "nav_replay": replay,
        "caveats": [
            "independent evidence only; not wired into One Loop or test2 state",
            "daily OHLC cannot establish intraday stop/take ordering, so both-hit bars use stop-first",
            "current output cannot support return optimization while price-basis issues remain",
            "old continuity days do not validate future code or future returns",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Standalone SQLite snapshot")
    parser.add_argument("--repo-root", required=True, help="Root for continuity artifacts")
    parser.add_argument("--output", required=True, help="JSON output under a temporary directory")
    parser.add_argument(
        "--implementation-since",
        default=DEFAULT_IMPLEMENTATION_SINCE,
        help="Must equal the canonical One Loop start date; CLI overrides fail closed.",
    )
    parser.add_argument("--required-days", type=int, default=DEFAULT_REQUIRED_DAYS)
    parser.add_argument("--end", help="Optional inclusive evidence end date")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    try:
        _assert_temporary_output(output)
        implementation_since = require_canonical_implementation_since(
            args.implementation_since
        )
        result = build_evidence(
            args.db,
            repo_root=args.repo_root,
            implementation_since=implementation_since,
            required_days=args.required_days,
            end=args.end,
            config=ReplayConfig(initial_cash=args.initial_cash),
        )
    except (ContinuityAuditError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"P0-R replay failed: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["status"] == "evidence_only" else 1


if __name__ == "__main__":
    sys.exit(main())
