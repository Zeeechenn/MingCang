#!/usr/bin/env python3
"""Read-only runtime follow-up diagnostics for an explicit SQLite database.

This is deliberately separate from the One Loop continuity contract and daily
runner.  It joins operational facts (stuck jobs and persisted degradations)
with an optional, already-produced continuity JSON without writing either
source.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = "runtime_followups.v1"
INTENTIONAL_SKIP_MARKERS = ("--no-llm", "--no_llm", "--no-shadow", "--no_shadow")


def _connect_immutable(path_value: str | Path) -> sqlite3.Connection:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"database path does not exist: {path}")
    quoted = quote(str(path), safe="/:")
    connection = sqlite3.connect(f"file:{quoted}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.DatabaseError:
        return set()


def _json(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _as_of(value: str | None) -> datetime:
    if value:
        parsed = _parse_datetime(value)
        if parsed is None:
            raise ValueError(f"--as-of must be an ISO date or datetime, got {value!r}")
        return parsed
    return datetime.now(UTC).replace(tzinfo=None)


def _stale_running(
    connection: sqlite3.Connection, as_of: datetime, threshold_hours: float
) -> dict[str, Any]:
    if "job_runs" not in _tables(connection):
        return {"threshold_hours": threshold_hours, "count": 0, "jobs": [], "missing_table": True}
    columns = _columns(connection, "job_runs")
    if not {"run_id", "job_name", "status", "started_at", "as_of"} <= columns:
        return {"threshold_hours": threshold_hours, "count": 0, "jobs": [], "missing_columns": True}
    jobs: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT run_id, job_name, status, as_of, started_at, finished_at, error
        FROM job_runs
        WHERE status = 'running'
        ORDER BY started_at ASC, run_id ASC
        """
    ):
        started = _parse_datetime(row["started_at"])
        age_hours = (as_of - started).total_seconds() / 3600 if started else None
        if age_hours is None or age_hours < threshold_hours:
            continue
        jobs.append(
            {
                "run_id": row["run_id"],
                "job_name": row["job_name"],
                "status": row["status"],
                "as_of": row["as_of"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "error": row["error"],
                "age_hours": round(age_hours, 3),
            }
        )
    return {"threshold_hours": threshold_hours, "count": len(jobs), "jobs": jobs}


def _drift_by_symbol(connection: sqlite3.Connection) -> dict[str, Any]:
    if "degradation_events" not in _tables(connection):
        return {"event_count": 0, "by_symbol": [], "unknown_symbol_count": 0, "missing_table": True}
    columns = _columns(connection, "degradation_events")
    required = {"id", "ts", "category", "component", "provider", "error", "context_json"}
    if not required <= columns:
        return {
            "event_count": 0,
            "by_symbol": [],
            "unknown_symbol_count": 0,
            "missing_columns": True,
        }
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "first_ts": None, "last_ts": None, "event_ids": []}
    )
    unknown = 0
    total = 0
    for row in connection.execute(
        """
        SELECT id, ts, component, provider, error, context_json
        FROM degradation_events
        WHERE category = 'adjustment_basis_drift'
        ORDER BY ts ASC, id ASC
        """
    ):
        context = _dict(_json(row["context_json"]))
        symbol = str(context.get("symbol") or context.get("asset_key") or "").strip()
        if not symbol:
            symbol = "unknown"
            unknown += 1
        item = grouped[symbol]
        item["count"] += 1
        item["event_ids"].append(row["id"])
        item["first_ts"] = item["first_ts"] or row["ts"]
        item["last_ts"] = row["ts"]
        total += 1
    by_symbol = [{"symbol": symbol, **item} for symbol, item in sorted(grouped.items())]
    return {"event_count": total, "by_symbol": by_symbol, "unknown_symbol_count": unknown}


def _flatten_degradations(continuity: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for day in continuity.get("days") or []:
        if not isinstance(day, dict):
            continue
        for item in day.get("degradations") or []:
            if isinstance(item, dict):
                reason = item.get("reason") or item.get("name") or item.get("code")
                count = item.get("count", 1)
                try:
                    repetitions = max(1, int(count))
                except (TypeError, ValueError):
                    repetitions = 1
            else:
                reason, repetitions = str(item), 1
            if reason:
                values.extend([str(reason)] * repetitions)
    return values


def _degradation_summary(continuity: dict[str, Any]) -> dict[str, Any]:
    observed = _flatten_degradations(continuity)
    intentional: Counter[str] = Counter()
    unexpected: Counter[str] = Counter()
    for reason in observed:
        if any(marker in reason.lower() for marker in INTENTIONAL_SKIP_MARKERS):
            intentional[reason] += 1
        else:
            unexpected[reason] += 1
    work_metrics = _dict(_dict(continuity.get("metrics")).get("work_metrics"))
    return {
        "contract_degradation_rate": work_metrics.get("degradation_rate"),
        "intentional_skips": dict(sorted(intentional.items())),
        "unexpected_degradations": dict(sorted(unexpected.items())),
        "observed_degradation_count": len(observed),
    }


def _review_evidence(continuity: dict[str, Any]) -> dict[str, Any]:
    work_metrics = _dict(_dict(continuity.get("metrics")).get("work_metrics"))
    human_contract = work_metrics.get("human_review_rate")
    freshness_contract = work_metrics.get("review_freshness")
    human_observations: list[dict[str, Any]] = []
    freshness_observations: list[dict[str, Any]] = []
    for day in continuity.get("days") or []:
        if not isinstance(day, dict):
            continue
        date_value = day.get("date")
        panel = _dict(day.get("panel_work_metrics"))
        if isinstance(panel.get("human_review"), dict):
            human_observations.append({"date": date_value, **panel["human_review"]})
        if isinstance(panel.get("review_freshness"), dict):
            freshness_observations.append({"date": date_value, **panel["review_freshness"]})
    return {
        "human_review": {
            "contract_metric": human_contract,
            "observations": human_observations,
            "observation_days": len(human_observations),
        },
        "review_freshness": {
            "contract_metric": freshness_contract,
            "observations": freshness_observations,
            "observation_days": len(freshness_observations),
            "semantics": "cross-day backlog observations, not a unique task count",
        },
    }


def audit_runtime_followups(
    *,
    db_path: str | Path,
    continuity_path: str | Path | None = None,
    stale_running_hours: float = 6.0,
    as_of: str | None = None,
) -> dict[str, Any]:
    if stale_running_hours < 0:
        raise ValueError("--stale-running-hours must be >= 0")
    as_of_dt = _as_of(as_of)
    continuity: dict[str, Any] = {}
    continuity_source: str | None = None
    if continuity_path:
        path = Path(continuity_path).expanduser().resolve()
        continuity = _json(path.read_text(encoding="utf-8"))
        if not isinstance(continuity, dict):
            raise ValueError("continuity JSON must contain an object")
        continuity_source = str(path)
    connection = _connect_immutable(db_path)
    try:
        return {
            "schema_version": SCHEMA_VERSION,
            "as_of": as_of_dt.isoformat(sep=" "),
            "database": {
                "path": str(Path(db_path).expanduser().resolve()),
                "mode": "ro&immutable=1",
            },
            "stale_running": _stale_running(connection, as_of_dt, stale_running_hours),
            "adjustment_basis_drift": _drift_by_symbol(connection),
            "continuity": {
                "source": continuity_source,
                "available": bool(continuity_path),
                "status": continuity.get("status") if continuity else None,
                "degradations": _degradation_summary(continuity) if continuity else None,
                "review_evidence": _review_evidence(continuity) if continuity else None,
            },
        }
    finally:
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only runtime follow-up diagnostics")
    parser.add_argument("--db", dest="db_path", required=True, help="Explicit SQLite DB path")
    parser.add_argument(
        "--continuity-json",
        dest="continuity_path",
        help="Optional output from audit_one_loop_continuity.py",
    )
    parser.add_argument("--stale-running-hours", type=float, default=6.0)
    parser.add_argument("--as-of", help="ISO date/datetime used as the deterministic age clock")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        result = audit_runtime_followups(**vars(_parser().parse_args(argv)))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"runtime follow-up audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
