"""Read-only Stage-6 continuity proof for the MingCang One Loop.

The audit intentionally opens an explicit SQLite database in read-only immutable
mode and never imports the production SessionLocal.  It is a completion gate,
not a data producer: historical rows cannot be used unless they are on or after
the caller-provided implementation date.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.ops.run_envelope import SIGNAL_PRODUCING_JOBS

RUN_ENVELOPE_VERSION = "run_envelope.v1"
DAILY_PANEL_VERSION = "daily_panel.v1"
CANONICAL_DAILY_PANEL_CARD_TYPES = (
    "batch_integrity",
    "candidate",
    "position_health",
    "event_risk",
    "watchtower",
    "daily_delta",
    "human_confirmation",
    "review_attribution",
)
PANEL_WORK_METRIC_INPUTS = (
    "duplicate_suppression",
    "human_review",
    "review_freshness",
    "failure_recovery",
)
AUTHORITATIVE_POSTMARKET_ENTRYPOINT = "m63_postmarket"
DEFAULT_REQUIRED_DAYS = 20


class ContinuityAuditError(ValueError):
    """Raised when the audit request itself is invalid."""


@dataclass(frozen=True)
class SignalBatch:
    batch_id: str
    rows: int
    symbols: int
    min_data_timestamp: str | None
    max_data_timestamp: str | None
    run_id: str | None = None
    run_id_count: int = 0
    run_id_missing: int = 0
    authoritative: bool | None = None

    @property
    def run_bound(self) -> bool:
        """True only when *every* row in the batch names the same owning run.

        A batch where some rows carry a run id and others do not is a mixture of
        tracked and untracked writes, and must not be treated as attributable.
        """
        return self.run_id is not None and self.run_id_count == 1 and self.run_id_missing == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "rows": self.rows,
            "symbols": self.symbols,
            "min_data_timestamp": self.min_data_timestamp,
            "max_data_timestamp": self.max_data_timestamp,
            "run_id": self.run_id,
            "run_bound": self.run_bound,
            "run_id_missing": self.run_id_missing,
            "authoritative": self.authoritative,
        }


def _parse_date(value: str, *, field: str) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise ContinuityAuditError(f"{field} must be an ISO date, got {value!r}") from exc


def _connect_immutable(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"database path does not exist: {path}")
    quoted = urllib.parse.quote(str(path), safe="/:")
    conn = sqlite3.connect(f"file:{quoted}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row[1]) for row in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stored_run_envelope(row: sqlite3.Row) -> dict[str, Any] | None:
    output = _as_dict(_json_loads(row["output_summary_json"] if "output_summary_json" in row.keys() else None))
    envelope = output.get("run_envelope")
    if isinstance(envelope, dict) and envelope.get("schema_version") == RUN_ENVELOPE_VERSION:
        return envelope
    coverage = _as_dict(_json_loads(row["input_coverage_json"] if "input_coverage_json" in row.keys() else None))
    envelope = coverage.get("run_envelope")
    if isinstance(envelope, dict) and envelope.get("schema_version") == RUN_ENVELOPE_VERSION:
        return envelope
    return None


def _coverage(envelope: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_as_dict(envelope.get("freshness")).get("input_coverage"))


def _close_confirmed_declared(envelope: dict[str, Any]) -> bool:
    """False only when the run explicitly declares it ran before the close.

    Envelopes written before this contract carry no flag and keep the legacy
    behaviour; anything our own writer produces always states it.
    """
    freshness = _as_dict(envelope.get("freshness"))
    return freshness.get("close_confirmed") is not False


def _is_authoritative(envelope: dict[str, Any]) -> bool:
    coverage = _coverage(envelope)
    return coverage.get("database") != "custom" and coverage.get("authoritative") is not False


def _close_confirmed_days(conn: sqlite3.Connection, implementation_since: str) -> list[str]:
    if not _table_exists(conn, "prices") or "date" not in _table_columns(conn, "prices"):
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT substr(date, 1, 10) AS trade_day
        FROM prices
        WHERE substr(date, 1, 10) >= ?
        ORDER BY trade_day ASC
        """,
        (implementation_since,),
    ).fetchall()
    return [str(row["trade_day"]) for row in rows if row["trade_day"]]


def _job_rows_for_day(conn: sqlite3.Connection, day: str) -> tuple[list[sqlite3.Row], list[str]]:
    if not _table_exists(conn, "job_runs"):
        return [], ["missing_job_runs_table"]
    columns = _table_columns(conn, "job_runs")
    required = {
        "job_name",
        "status",
        "as_of",
        "run_id",
        "output_summary_json",
        "input_coverage_json",
        "artifact_path",
    }
    missing = sorted(required - columns)
    if missing:
        return [], [f"missing_job_runs_columns:{','.join(missing)}"]
    rows = conn.execute(
        """
        SELECT *
        FROM job_runs
        WHERE job_name = ? AND substr(as_of, 1, 10) = ?
        ORDER BY id ASC
        """,
        (AUTHORITATIVE_POSTMARKET_ENTRYPOINT, day),
    ).fetchall()
    return rows, []


def _authoritative_panel_runs(rows: list[sqlite3.Row], day: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    excluded: Counter[str] = Counter()
    complete: list[dict[str, Any]] = []
    for row in rows:
        envelope = _stored_run_envelope(row)
        if envelope is None:
            excluded["missing_explicit_run_envelope"] += 1
            continue
        if row["status"] != "success":
            excluded["job_not_success"] += 1
            continue
        if envelope.get("entrypoint") != AUTHORITATIVE_POSTMARKET_ENTRYPOINT:
            excluded["wrong_entrypoint"] += 1
            continue
        if str(envelope.get("as_of") or "")[:10] != day or str(envelope.get("trade_date") or "")[:10] != day:
            excluded["stale_or_wrong_run_date"] += 1
            continue
        if not _is_authoritative(envelope):
            excluded["non_authoritative_or_custom"] += 1
            continue
        if not _close_confirmed_declared(envelope):
            excluded["panel_run_not_close_confirmed"] += 1
            continue
        if envelope.get("status") != "complete":
            excluded["not_complete"] += 1
            continue
        complete.append({"row": row, "envelope": envelope})
    return complete, excluded


def _all_job_rows_for_day(conn: sqlite3.Connection, day: str) -> tuple[list[sqlite3.Row], list[str]]:
    if not _table_exists(conn, "job_runs"):
        return [], ["missing_job_runs_table"]
    columns = _table_columns(conn, "job_runs")
    required = {
        "job_name",
        "status",
        "as_of",
        "run_id",
        "output_summary_json",
        "input_coverage_json",
        "artifact_path",
    }
    missing = sorted(required - columns)
    if missing:
        return [], [f"missing_job_runs_columns:{','.join(missing)}"]
    rows = conn.execute(
        """
        SELECT *
        FROM job_runs
        WHERE substr(as_of, 1, 10) = ?
        ORDER BY id ASC
        """,
        (day,),
    ).fetchall()
    return rows, []


def _signal_batches_for_day(conn: sqlite3.Connection, day: str) -> tuple[list[SignalBatch], list[str]]:
    if not _table_exists(conn, "signals"):
        return [], ["missing_signals_table"]
    columns = _table_columns(conn, "signals")
    required = {"symbol", "date"}
    missing = sorted(required - columns)
    if missing:
        return [], [f"missing_signals_columns:{','.join(missing)}"]
    day_expr = "substr(COALESCE(data_timestamp, date), 1, 10)" if "data_timestamp" in columns else "substr(date, 1, 10)"
    timestamp_expr = "data_timestamp" if "data_timestamp" in columns else "date"
    has_run_id = "run_id" in columns
    run_id_select = (
        "MIN(run_id) AS run_id, COUNT(DISTINCT run_id) AS run_id_count, "
        "SUM(CASE WHEN run_id IS NULL OR run_id = '' THEN 1 ELSE 0 END) AS run_id_missing"
        if has_run_id
        else "NULL AS run_id, 0 AS run_id_count, 0 AS run_id_missing"
    )
    rows = conn.execute(
        f"""
        SELECT
            date AS batch_id,
            COUNT(*) AS rows,
            COUNT(DISTINCT symbol) AS symbols,
            MIN({timestamp_expr}) AS min_data_timestamp,
            MAX({timestamp_expr}) AS max_data_timestamp,
            {run_id_select}
        FROM signals
        WHERE {day_expr} = ?
        GROUP BY date
        ORDER BY date ASC
        """,
        (day,),
    ).fetchall()
    return [
        SignalBatch(
            batch_id=str(row["batch_id"]),
            rows=int(row["rows"] or 0),
            symbols=int(row["symbols"] or 0),
            min_data_timestamp=row["min_data_timestamp"],
            max_data_timestamp=row["max_data_timestamp"],
            run_id=str(row["run_id"]) if row["run_id"] else None,
            run_id_count=int(row["run_id_count"] or 0),
            run_id_missing=int(row["run_id_missing"] or 0),
            authoritative=_batch_authoritative(
                conn,
                str(row["run_id"]) if row["run_id"] and int(row["run_id_count"] or 0) == 1 else None,
            ),
        )
        for row in rows
    ], []


def _batch_authoritative(conn: sqlite3.Connection, run_id: str | None) -> bool | None:
    """Whether the run that produced a batch declared itself the day's official one.

    The signal runner already marks any non-default universe (live-track sweeps,
    subset deep-evaluation reruns) as non-authoritative; those are research
    reruns, not the day's official signal batch. Unknown stays None so an
    unreadable run is never silently dropped.
    """
    if not run_id or not _table_exists(conn, "job_runs"):
        return None
    row = conn.execute(
        "SELECT * FROM job_runs WHERE run_id = ? LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    envelope = _stored_run_envelope(row)
    if envelope is None:
        return None
    return _is_authoritative(envelope)


def _batch_run_met_expectation(conn: sqlite3.Connection, batch: SignalBatch) -> bool | None:
    """Whether the run that wrote this batch reported hitting its own target.

    A run that declares `failed>0`, or whose `completed` never reached its own
    `expected`, has already said it did not finish the day's work — a data-source
    outage mid-batch is the usual cause. Such a batch is superseded residue, not
    a rival candidate for "the day's official batch".

    Returns None when no run binding or readable envelope exists.  Once a run
    envelope exists, missing or inconsistent counts are an explicit failure so
    an under-filled batch cannot win by elimination.
    """
    if not batch.run_bound or not _table_exists(conn, "job_runs"):
        return None
    row = conn.execute(
        "SELECT * FROM job_runs WHERE run_id = ? LIMIT 1",
        (batch.run_id,),
    ).fetchone()
    if row is None:
        return None
    envelope = _stored_run_envelope(row)
    if envelope is None:
        return None
    if envelope.get("status") != "complete":
        return False
    failed = _as_int(_as_dict(envelope.get("failed")).get("symbols"))
    expected = _as_int(_as_dict(envelope.get("expected")).get("symbols"))
    completed = _as_int(_as_dict(envelope.get("completed")).get("symbols"))
    # A complete-looking envelope without explicit counts is not evidence of a
    # complete batch.  The continuity gate must fail closed when a producer
    # omitted its counts, rather than allowing an under-filled signal batch to
    # become the day's official batch by elimination.
    if failed is None or expected is None or completed is None:
        return False
    if failed != 0:
        return False
    if expected != completed or expected != batch.symbols:
        return False
    return True


def _envelope_covers_batch(envelope: dict[str, Any], batch: SignalBatch) -> bool:
    coverage = _coverage(envelope)
    identifiers = {
        str(envelope.get("batch_id") or ""),
        str(coverage.get("batch_id") or ""),
        str(coverage.get("signal_batch_id") or ""),
    }
    # An explicit run binding on the rows themselves outranks date identifiers;
    # legacy rows carry no run_id and keep the date-matching path.
    if batch.run_bound:
        if str(envelope.get("run_id") or "") != batch.run_id:
            return False
    elif batch.batch_id not in identifiers:
        return False
    expected_symbols = _as_int(_as_dict(envelope.get("expected")).get("symbols"))
    completed_symbols = _as_int(_as_dict(envelope.get("completed")).get("symbols"))
    failed_symbols = _as_int(_as_dict(envelope.get("failed")).get("symbols"))
    if expected_symbols is None or expected_symbols != batch.symbols:
        return False
    if completed_symbols is None or completed_symbols != batch.symbols:
        return False
    return failed_symbols == 0


def _envelope_identifiers(envelope: dict[str, Any]) -> set[str]:
    coverage = _coverage(envelope)
    return {
        str(envelope.get("batch_id") or ""),
        str(coverage.get("batch_id") or ""),
        str(coverage.get("signal_batch_id") or ""),
    }


def _select_signal_run_for_batch(
    rows: list[sqlite3.Row],
    *,
    day: str,
    batch: SignalBatch,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    excluded: Counter[str] = Counter()
    complete: list[dict[str, Any]] = []
    signal_entrypoints = set(SIGNAL_PRODUCING_JOBS)
    for row in rows:
        row_job = str(row["job_name"] or "")
        envelope = _stored_run_envelope(row)
        if envelope is None:
            if row_job in signal_entrypoints:
                excluded["missing_explicit_run_envelope"] += 1
            continue
        entrypoint = str(envelope.get("entrypoint") or row_job)
        identifiers = _envelope_identifiers(envelope)
        run_bound_match = batch.run_bound and str(envelope.get("run_id") or "") == batch.run_id
        relevant = (
            row_job in signal_entrypoints
            or entrypoint in signal_entrypoints
            or batch.batch_id in identifiers
            or run_bound_match
        )
        if not relevant:
            continue
        if row["status"] != "success":
            excluded["job_not_success"] += 1
            continue
        if row_job not in signal_entrypoints and entrypoint not in signal_entrypoints:
            excluded["wrong_signal_entrypoint"] += 1
            continue
        if str(envelope.get("as_of") or "")[:10] != day or str(envelope.get("trade_date") or "")[:10] != day:
            excluded["stale_or_wrong_signal_run_date"] += 1
            continue
        freshness_as_of = str(_as_dict(envelope.get("freshness")).get("as_of") or "")[:10]
        if freshness_as_of and freshness_as_of != day:
            excluded["stale_signal_freshness_as_of"] += 1
            continue
        if not _is_authoritative(envelope):
            excluded["non_authoritative_or_custom"] += 1
            continue
        if envelope.get("status") != "complete":
            excluded["not_complete"] += 1
            continue
        if not _envelope_covers_batch(envelope, batch):
            excluded["mismatched_signal_batch"] += 1
            continue
        complete.append({"row": row, "envelope": envelope})
    return complete, excluded


def _resolve_artifact(path_value: Any, repo_root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    return path if path.is_absolute() else repo_root / path


def _daily_panel_date(payload: dict[str, Any]) -> str:
    return str(payload.get("as_of") or payload.get("day") or payload.get("date") or "")[:10]


def _daily_panel_work_metrics(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    source = payload.get("work_metrics")
    if not isinstance(source, dict):
        source = _as_dict(_as_dict(payload.get("metrics")).get("work_metrics"))
    metrics: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for name in PANEL_WORK_METRIC_INPUTS:
        metric = source.get(name)
        if not isinstance(metric, dict):
            blockers.append(f"missing_panel_work_metric:{name}")
            continue
        if metric.get("status") != "available":
            blockers.append(f"unavailable_panel_work_metric:{name}")
            continue
        metrics[name] = metric
    return metrics, blockers


def _daily_panel_matches_run(path: Path, envelope: dict[str, Any], day: str) -> tuple[bool, list[str], dict[str, dict[str, Any]]]:
    """Verify that a JSON artifact is the Stage5 daily_panel.v1 contract."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False, ["daily_panel_json_unreadable"], {}
    if not isinstance(payload, dict):
        return False, ["daily_panel_json_not_object"], {}
    blockers: list[str] = []
    if payload.get("schema_version") != DAILY_PANEL_VERSION:
        blockers.append("daily_panel_schema_mismatch")
    artifact_day = _daily_panel_date(payload)
    if artifact_day and artifact_day != day:
        blockers.append("daily_panel_date_mismatch")
    elif not artifact_day:
        blockers.append("daily_panel_date_missing")
    cards = payload.get("cards")
    card_types = [card.get("card_type") for card in cards] if isinstance(cards, list) else []
    if card_types != list(CANONICAL_DAILY_PANEL_CARD_TYPES):
        blockers.append("daily_panel_card_types_mismatch")
    artifact_envelope = payload.get("run_envelope")
    if isinstance(artifact_envelope, dict):
        artifact_run_id = artifact_envelope.get("run_id")
        artifact_batch_id = artifact_envelope.get("batch_id")
        if artifact_run_id != envelope.get("run_id"):
            blockers.append("daily_panel_run_id_mismatch")
        if artifact_batch_id != envelope.get("batch_id"):
            blockers.append("daily_panel_batch_id_mismatch")
    else:
        blockers.append("daily_panel_run_envelope_missing")
    if payload.get("ledger_commit_state") != "committed":
        blockers.append("daily_panel_ledger_commit_state_not_committed")
    if _as_dict(payload.get("artifact_contract")).get("close_confirmed") is False:
        blockers.append("daily_panel_not_close_confirmed")
    work_metrics, metric_blockers = _daily_panel_work_metrics(payload)
    blockers.extend(metric_blockers)
    return not blockers, blockers, work_metrics


def _artifact_status(
    row: sqlite3.Row,
    envelope: dict[str, Any],
    day: str,
    repo_root: Path,
) -> tuple[str, list[str], list[str], dict[str, dict[str, Any]]]:
    blockers: list[str] = []
    artifacts: list[str] = []
    panel_work_metrics: dict[str, dict[str, Any]] = {}
    for item in _as_list(envelope.get("artifacts")):
        artifacts.append(str(item))
    if row["artifact_path"]:
        artifacts.append(str(row["artifact_path"]))
    unique_artifacts = list(dict.fromkeys(artifacts))
    if not unique_artifacts:
        return "missing", [], ["missing_panel_artifact_reference"], {}
    existing: list[str] = []
    for item in unique_artifacts:
        resolved = _resolve_artifact(item, repo_root)
        if resolved is not None and resolved.exists():
            existing.append(str(resolved))
    if not existing:
        blockers.append("missing_panel_artifact_file")
    else:
        json_existing = [item for item in existing if Path(item).suffix.lower() == ".json"]
        if not json_existing:
            blockers.append("missing_daily_panel_json_artifact")
        artifact_match = False
        artifact_blockers: list[str] = []
        for item in json_existing:
            matched, item_blockers, item_metrics = _daily_panel_matches_run(Path(item), envelope, day)
            artifact_match = artifact_match or matched
            artifact_blockers.extend(item_blockers)
            if matched:
                panel_work_metrics = item_metrics
        if not artifact_match:
            blockers.extend(list(dict.fromkeys(artifact_blockers)) or ["daily_panel_contract_unverified"])
    if str(envelope.get("as_of") or "")[:10] != day or str(envelope.get("trade_date") or "")[:10] != day:
        blockers.append("panel_run_date_mismatch")
    return ("complete" if not blockers else "missing", existing, blockers, panel_work_metrics)


def _audit_day(conn: sqlite3.Connection, day: str, repo_root: Path) -> dict[str, Any]:
    blockers: list[str] = []
    notes: list[str] = []
    checks: dict[str, str] = {}
    rows, row_blockers = _job_rows_for_day(conn, day)
    blockers.extend(row_blockers)
    complete_panel_runs, panel_excluded = _authoritative_panel_runs(rows, day)
    if len(complete_panel_runs) == 1:
        checks["run_envelope"] = "complete"
        selected_panel = complete_panel_runs[0]
        panel_envelope = selected_panel["envelope"]
        panel_row = selected_panel["row"]
    elif len(complete_panel_runs) > 1:
        checks["run_envelope"] = "ambiguous"
        blockers.append("ambiguous_authoritative_complete_run")
        panel_envelope = None
        panel_row = None
    else:
        checks["run_envelope"] = "missing"
        blockers.append("missing_authoritative_complete_run")
        panel_envelope = None
        panel_row = None

    # Exclusions explain why a selection failed. Once one authoritative run has
    # been selected they are expected residue — a superseded pre-close run, a
    # retried attempt — and must not withhold a day that is otherwise complete.
    for reason, count in sorted(panel_excluded.items()):
        target = notes if panel_envelope is not None else blockers
        target.append(f"excluded_run:{reason}:{count}")

    all_batches, signal_blockers = _signal_batches_for_day(conn, day)
    blockers.extend(signal_blockers)
    # A research rerun over a non-default universe is not the day's official
    # signal batch and must not make the official one look ambiguous.
    batches = [batch for batch in all_batches if batch.authoritative is not False]
    research_batches = len(all_batches) - len(batches)
    if research_batches:
        notes.append(f"non_authoritative_signal_batches:{research_batches}")
    # A run that itself reported failed>0 (or never reached its own expected
    # count) is superseded residue, not a rival for the day's official batch.
    # Re-running after a data-source outage is routine — 2026-08-25 needed three
    # attempts (21/25, 23/25, then 25/25) — and without this the surviving good
    # batch is drowned out by its own failed predecessors and the day reads as
    # `ambiguous_signal_batches`, reporting a gate that is in fact locked as broken.
    # This is the judgement `_envelope_covers_batch` already applies when picking
    # a run, pulled forward to batch selection. Never applied when it would empty
    # the candidate set: an all-incomplete day must still read incomplete.
    met_expectation = [
        batch for batch in batches if _batch_run_met_expectation(conn, batch) is not False
    ]
    if met_expectation and len(met_expectation) < len(batches):
        notes.append(f"superseded_signal_batches:{len(batches) - len(met_expectation)}")
        batches = met_expectation

    run_bound_batches = [batch for batch in batches if batch.run_bound]
    selected_batch: SignalBatch | None = None
    if len(batches) == 1:
        checks["signal_batch_identity"] = "unique"
        selected_batch = batches[0]
    elif len(batches) > 1 and len(run_bound_batches) == 1:
        # Several batches share the trade date, but exactly one names its owning
        # run: the explicit binding resolves what date matching cannot.
        checks["signal_batch_identity"] = "unique_by_run_id"
        selected_batch = run_bound_batches[0]
    elif len(batches) > 1:
        checks["signal_batch_identity"] = "ambiguous"
        blockers.append("ambiguous_signal_batches")
    else:
        checks["signal_batch_identity"] = "missing"
        blockers.append("missing_signal_batch")

    signal_runs: list[dict[str, Any]] = []
    signal_excluded: Counter[str] = Counter()
    if selected_batch is not None:
        all_rows, all_row_blockers = _all_job_rows_for_day(conn, day)
        blockers.extend(all_row_blockers)
        signal_runs, signal_excluded = _select_signal_run_for_batch(
            all_rows,
            day=day,
            batch=selected_batch,
        )
    signal_envelope = signal_runs[0]["envelope"] if len(signal_runs) == 1 else None
    for reason, count in sorted(signal_excluded.items()):
        target = notes if signal_envelope is not None else blockers
        target.append(f"excluded_signal_run:{reason}:{count}")
    if len(signal_runs) == 1:
        checks["batch_envelope_match"] = "matched"
        checks["signal_run"] = "complete"
    elif len(signal_runs) > 1:
        checks["batch_envelope_match"] = "ambiguous"
        checks["signal_run"] = "ambiguous"
        blockers.append("ambiguous_authoritative_signal_run")
    else:
        checks["batch_envelope_match"] = "mismatched"
        checks["signal_run"] = "missing"
        blockers.append("missing_authoritative_signal_run")

    artifacts: list[str] = []
    degradations: list[Any] = []
    panel_work_metrics: dict[str, dict[str, Any]] = {}
    stale = False
    if panel_envelope is not None and panel_row is not None:
        artifact_check, artifacts, artifact_blockers, panel_work_metrics = _artifact_status(
            panel_row,
            panel_envelope,
            day,
            repo_root,
        )
        checks["artifact_panel"] = artifact_check
        blockers.extend(artifact_blockers)
        degradations = _as_list(panel_envelope.get("degradations")) + _as_list(
            signal_envelope.get("degradations") if signal_envelope else []
        )
        freshness_as_of = str(_as_dict(panel_envelope.get("freshness")).get("as_of") or "")[:10]
        stale = bool(freshness_as_of and freshness_as_of != day)
        if stale:
            blockers.append("stale_freshness_as_of")
    else:
        checks["artifact_panel"] = "missing"
        blockers.append("missing_panel_artifact_reference")

    blockers = list(dict.fromkeys(blockers))
    status = "complete" if not blockers else "incomplete"
    return {
        "date": day,
        "status": status,
        "checks": checks,
        "notes": list(dict.fromkeys(notes)),
        "run_id": panel_envelope.get("run_id") if panel_envelope else None,
        "panel_run_id": panel_envelope.get("run_id") if panel_envelope else None,
        "signal_run_id": signal_envelope.get("run_id") if signal_envelope else None,
        "batch_id": selected_batch.batch_id if selected_batch else None,
        "panel_envelope_batch_id": panel_envelope.get("batch_id") if panel_envelope else None,
        "signal_envelope_batch_id": signal_envelope.get("batch_id") if signal_envelope else None,
        "signal_batches": [batch.as_dict() for batch in all_batches],
        "artifacts": artifacts,
        "panel_work_metrics": panel_work_metrics,
        "degradations": degradations,
        "stale": stale,
        "blockers": blockers,
    }


def _metric(status: str, value: float | None, *, evidence: dict[str, Any] | None = None, missing: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "value": value}
    if evidence is not None:
        payload["evidence"] = evidence
    if missing is not None:
        payload["missing"] = missing
    return payload


def _rate(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6)


def _aggregate_panel_input(days: list[dict[str, Any]], name: str) -> tuple[list[dict[str, Any]], list[str]]:
    values: list[dict[str, Any]] = []
    missing: list[str] = []
    for day in days:
        metric = _as_dict(day.get("panel_work_metrics")).get(name)
        if isinstance(metric, dict):
            values.append(metric)
        else:
            missing.append(str(day.get("date")))
    return values, missing


def _work_metrics(days: list[dict[str, Any]], close_confirmed_days: int) -> dict[str, Any]:
    if not close_confirmed_days:
        unavailable = _metric("unavailable", None, missing="no_close_confirmed_days")
        return {
            "completeness_rate": unavailable,
            "degradation_rate": unavailable,
            "duplicate_suppression_rate": unavailable,
            "human_review_rate": unavailable,
            "review_freshness": unavailable,
            "failure_recovery": unavailable,
        }
    complete_days = sum(1 for day in days if day["status"] == "complete")
    degradation_days = sum(1 for day in days if day["degradations"])
    metrics = {
        "completeness_rate": _metric(
            "available",
            _rate(complete_days, close_confirmed_days),
            evidence={"complete_days": complete_days, "close_confirmed_days": close_confirmed_days},
        ),
        "degradation_rate": _metric(
            "available",
            _rate(degradation_days, close_confirmed_days),
            evidence={"degraded_days": degradation_days, "close_confirmed_days": close_confirmed_days},
        ),
    }
    duplicate_inputs, missing_duplicate = _aggregate_panel_input(days, "duplicate_suppression")
    if missing_duplicate:
        metrics["duplicate_suppression_rate"] = _metric("missing", None, missing="panel_work_metric_missing:duplicate_suppression")
    else:
        evaluated = sum(_as_int(item.get("evaluated")) or 0 for item in duplicate_inputs)
        suppressed = sum(_as_int(item.get("suppressed")) or 0 for item in duplicate_inputs)
        metrics["duplicate_suppression_rate"] = (
            _metric("available", _rate(suppressed, evaluated), evidence={"suppressed": suppressed, "evaluated": evaluated})
            if evaluated
            else _metric(
                "not_applicable",
                None,
                evidence={
                    "suppressed": suppressed,
                    "evaluated": evaluated,
                    "reason": "no_duplicate_suppression_events_observed",
                },
            )
        )
    review_inputs, missing_review = _aggregate_panel_input(days, "human_review")
    if missing_review:
        metrics["human_review_rate"] = _metric("missing", None, missing="panel_work_metric_missing:human_review")
    else:
        required = sum(_as_int(item.get("required")) or 0 for item in review_inputs)
        completed = sum(_as_int(item.get("completed")) or 0 for item in review_inputs)
        metrics["human_review_rate"] = (
            _metric("available", _rate(completed, required), evidence={"completed": completed, "required": required})
            if required
            else _metric(
                "not_applicable",
                None,
                evidence={
                    "completed": completed,
                    "required": required,
                    "reason": "no_human_reviews_required",
                },
            )
        )
    freshness_inputs, missing_freshness = _aggregate_panel_input(days, "review_freshness")
    if missing_freshness:
        metrics["review_freshness"] = _metric("missing", None, missing="panel_work_metric_missing:review_freshness")
    else:
        total = sum(_as_int(item.get("total")) or 0 for item in freshness_inputs)
        stale = sum(_as_int(item.get("stale")) or 0 for item in freshness_inputs)
        metrics["review_freshness"] = (
            _metric("available", _rate(total - stale, total), evidence={"fresh": total - stale, "stale": stale, "total": total})
            if total
            else _metric(
                "not_applicable",
                None,
                evidence={
                    "fresh": 0,
                    "stale": stale,
                    "total": total,
                    "reason": "no_reviews_to_check_freshness",
                },
            )
        )
    recovery_inputs, missing_recovery = _aggregate_panel_input(days, "failure_recovery")
    if missing_recovery:
        metrics["failure_recovery"] = _metric("missing", None, missing="panel_work_metric_missing:failure_recovery")
    else:
        recovered = sum(_as_int(item.get("recovered")) or 0 for item in recovery_inputs)
        open_failures = sum(_as_int(item.get("open_failures")) or 0 for item in recovery_inputs)
        denominator = recovered + open_failures
        metrics["failure_recovery"] = (
            _metric(
                "available",
                _rate(recovered, denominator),
                evidence={"recovered": recovered, "open_failures": open_failures},
            )
            if denominator
            else _metric(
                "available",
                1.0,
                evidence={"recovered": 0, "open_failures": 0, "note": "no_failures_observed"},
            )
        )
    return metrics


def _has_blocking_work_metric(metrics: dict[str, Any]) -> bool:
    return any(
        isinstance(metric, dict) and metric.get("status") in {"missing", "unavailable"}
        for metric in metrics.values()
    )


def _metrics(days: list[dict[str, Any]], close_confirmed_days: int, required_days: int) -> dict[str, Any]:
    blockers = Counter(blocker for day in days for blocker in day["blockers"])
    ledger = Counter(day["checks"].get("run_envelope", "missing") for day in days)
    batch_identity = Counter(day["checks"].get("batch_envelope_match", "mismatched") for day in days)
    artifacts = Counter(day["checks"].get("artifact_panel", "missing") for day in days)
    work_metrics = _work_metrics(days, close_confirmed_days)
    return {
        "close_confirmed_days": close_confirmed_days,
        "required_days": required_days,
        "ledger_coverage": dict(sorted(ledger.items())),
        "batch_identity": dict(sorted(batch_identity.items())),
        "artifact_panel_completeness": dict(sorted(artifacts.items())),
        "degradation_rate": work_metrics["degradation_rate"]["value"],
        "work_metrics": work_metrics,
        "stale_count": sum(1 for day in days if day["stale"]),
        "recovery_blockers": dict(sorted(blockers.items())),
    }


def audit_one_loop_continuity(
    *,
    db_path: str | Path,
    implementation_since: str,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Audit post-implementation One Loop continuity from an explicit DB path.

    ``implementation_since`` is inclusive: the first close-confirmed price day
    whose date equals the implementation date can count, but earlier historical
    rows never can.
    """
    implementation_day = _parse_date(implementation_since, field="implementation_since")
    if required_days < 1:
        raise ContinuityAuditError("required_days must be >= 1")
    root = Path(repo_root).resolve() if repo_root is not None else Path.cwd().resolve()
    db = Path(db_path).expanduser().resolve()
    with _connect_immutable(db) as conn:
        close_days = _close_confirmed_days(conn, implementation_day)
        day_results = [_audit_day(conn, day, root) for day in close_days]
    has_incomplete = any(day["status"] != "complete" for day in day_results)
    metrics: dict[str, Any] = _metrics(day_results, len(close_days), required_days)
    has_blocking_work_metric = len(close_days) >= required_days and _has_blocking_work_metric(
        metrics.get("work_metrics", {})
    )
    if len(close_days) < required_days:
        status = "insufficient_days"
    elif has_incomplete or has_blocking_work_metric:
        status = "incomplete"
    else:
        status = "complete"
    raw_recovery_blockers = metrics.get("recovery_blockers")
    recovery_blockers: dict[str, Any] = (
        raw_recovery_blockers if isinstance(raw_recovery_blockers, dict) else {}
    )
    result: dict[str, Any] = {
        "schema_version": "one_loop_continuity_audit.v1",
        "status": status,
        "db_path": str(db),
        "implementation_since": implementation_day,
        "required_days": required_days,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "days": day_results,
        "metrics": metrics,
    }
    if has_blocking_work_metric:
        recovery_blockers = {
            **recovery_blockers,
            "blocking_work_metric_missing_or_unavailable": 1,
        }
    if status == "insufficient_days":
        recovery_blockers = {
            **recovery_blockers,
            "insufficient_close_confirmed_days": required_days - len(close_days),
        }
    result["metrics"]["recovery_blockers"] = recovery_blockers
    return result


def to_json(result: dict[str, Any]) -> str:
    """Serialize audit output in the CLI's stable format."""
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
