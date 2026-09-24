"""Explicit offline readiness audit for the shadow news event-risk path.

This report is diagnostic evidence only. It never promotes event risk or
directional news weights and reads only a caller-supplied immutable SQLite
snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "news_event_readiness.v2"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_STATUSES = {"evidence", "no_evidence", "verified_no_news", "fetch_failed", "score_failed"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _rows(conn: sqlite3.Connection, table: str, columns: set[str]) -> list[dict[str, Any]]:
    selected = sorted(columns)
    if not selected:
        return []
    names = ", ".join('"' + name.replace('"', '""') + '"' for name in selected)
    cursor = conn.execute(f'SELECT {names} FROM "{table}"')
    return [dict(zip(selected, row, strict=True)) for row in cursor.fetchall()]


def _json(value: Any) -> tuple[Any, bool]:
    if value is None:
        return None, True
    try:
        return json.loads(value) if isinstance(value, str) else value, True
    except (TypeError, json.JSONDecodeError):
        return None, False


def _day(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def _on_or_before(value: Any, cutoff: str) -> bool:
    value_day = _day(value)
    return value_day is not None and value_day <= cutoff


def _after(value: Any, cutoff: str) -> bool:
    value_day = _day(value)
    return value_day is not None and value_day > cutoff


def _gate(status: str, reasons: list[str]) -> dict[str, Any]:
    return {"status": status, "reasons": reasons}


def build_readiness(
    conn: sqlite3.Connection,
    *,
    as_of: str,
    max_staleness_days: int = 7,
    snapshot_sha256: str | None = None,
    snapshot_path: str | None = None,
    audit_source_sha256: str | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize available snapshot evidence without inferring missing facts."""
    cutoff = date.fromisoformat(as_of)
    if cutoff.isoformat() != as_of:
        raise ValueError("--as-of must use YYYY-MM-DD")
    tables = _tables(conn)
    run_fields = {
        "run_id", "symbol", "as_of", "status", "created_at", "updated_at",
        "attribution_json", "trigger_reasons_json", "tokens_spent", "provider",
        "evidence_json", "degradation_flags_json", "error", "profile",
    }
    run_columns = _columns(conn, "news_shadow_runs") if "news_shadow_runs" in tables else set()
    runs_available = bool(run_columns)
    runs = _rows(conn, "news_shadow_runs", run_fields & run_columns) if runs_available else []
    all_run_days = [_day(row.get("as_of")) for row in runs]
    eligible = [row for row in runs if _on_or_before(row.get("as_of"), as_of)]
    future_runs = sum(_after(row.get("as_of"), as_of) for row in runs)
    runs_created_after_cutoff = sum(_after(row.get("created_at"), as_of) for row in eligible)
    runs_created_time_unknown = sum(not _day(row.get("created_at")) for row in eligible)
    available_runs = [row for row in eligible if _on_or_before(row.get("created_at"), as_of)]
    latest_eligible_days = [day for day in (_day(row.get("as_of")) for row in eligible) if day is not None]
    latest_days = [day for day in (_day(row.get("as_of")) for row in available_runs) if day is not None]
    latest_day = max(latest_days, default=None)
    age_days = (cutoff - date.fromisoformat(latest_day)).days if latest_day else None
    latest_eligible_day = max(latest_eligible_days, default=None)
    invalid_dates = sum(day is None for day in all_run_days)
    status_counts: dict[str, int] = {}
    historical_status_counts: dict[str, int] = {}
    for row in available_runs:
        value = row.get("status")
        key = str(value) if value not in (None, "") else "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1
    for row in eligible:
        value = row.get("status")
        key = str(value) if value not in (None, "") else "unknown"
        historical_status_counts[key] = historical_status_counts.get(key, 0) + 1
    unknown_status_rows = sum(row.get("status") in (None, "") for row in available_runs)
    unexpected_statuses = sorted(set(status_counts) - RUN_STATUSES - {"unknown"})

    evidence_rows = [row for row in available_runs if row.get("status") == "evidence"]
    trigger_known = run_columns >= {"status", "attribution_json"}
    triggered = untriggered = trigger_unknown = 0
    for row in evidence_rows:
        flags, flags_valid = _json(row.get("degradation_flags_json"))
        if not isinstance(flags, list):
            flags = []
        parsed, valid = _json(row.get("attribution_json"))
        attribution_shape = isinstance(parsed, dict) and isinstance(parsed.get("timeline"), list) and isinstance(parsed.get("main_cause"), str) and bool(parsed.get("main_cause"))
        if "PYRAMID_NOT_TRIGGERED" in flags and flags_valid:
            if attribution_shape:
                trigger_unknown += 1
            else:
                untriggered += 1
        elif not trigger_known or not valid or not flags_valid:
            trigger_unknown += 1
        elif attribution_shape:
            triggered += 1
        else:
            trigger_unknown += 1

    historical_tokens_known = [row.get("tokens_spent") for row in eligible if row.get("tokens_spent") is not None]
    tokens_known = [row.get("tokens_spent") for row in available_runs if row.get("tokens_spent") is not None]
    tokens_unknown = sum(row.get("tokens_spent") is None for row in available_runs)
    valid_tokens = [value for value in tokens_known if type(value) is int and value >= 0]
    token_total = sum(valid_tokens)
    token_non_numeric = len(tokens_known) - len(valid_tokens)
    historical_token_total = sum(value for value in historical_tokens_known
                                 if type(value) is int and value >= 0)

    # News table coverage is date-level only. SQLite naive timestamp conventions
    # differ across producers, so it is not asserted as strict PIT proof.
    news_columns = _columns(conn, "news") if "news" in tables else set()
    news_required = {"published_at", "content"}
    news_read_columns = news_required | ({"fetched_at"} if "fetched_at" in news_columns else set())
    news_rows = _rows(conn, "news", news_read_columns & news_columns) if news_required <= news_columns else []
    news_coverage_available = news_required <= news_columns
    news_published_eligible = [row for row in news_rows if _on_or_before(row.get("published_at"), as_of)]
    future_news = sum(_after(row.get("published_at"), as_of) for row in news_rows)
    news_published_unknown = len(news_rows) - len(news_published_eligible) - future_news
    news_fetch_unknown = sum(not _day(row.get("fetched_at")) for row in news_published_eligible) if "fetched_at" in news_columns else len(news_published_eligible)
    news_fetch_future = sum(_after(row.get("fetched_at"), as_of) for row in news_published_eligible) if "fetched_at" in news_columns else 0
    news_eligible = [row for row in news_published_eligible if "fetched_at" in news_columns and _on_or_before(row.get("fetched_at"), as_of)]
    news_fetched_after_cutoff = (
        news_fetch_future if "fetched_at" in news_columns else None
    )
    body_known = 0
    for row in news_eligible:
        content = row.get("content")
        if isinstance(content, str) and content.strip():
            body_known += 1
    body_coverage = (body_known / len(news_eligible)) if news_eligible else None

    manifest_total = manifest_pit_items = manifest_future_items = 0
    manifest_parse_unknown = manifest_arrays_unknown = 0
    for row in evidence_rows:
        parsed, valid = _json(row.get("evidence_json"))
        if not valid or not isinstance(parsed, dict):
            manifest_parse_unknown += 1
            manifest_arrays_unknown += 1
            continue
        items = parsed.get("items")
        if not isinstance(items, list):
            manifest_parse_unknown += 1
            manifest_arrays_unknown += 1
            continue
        run_day = _day(row.get("as_of"))
        for item in items:
            manifest_total += 1
            if not isinstance(item, dict) or not item.get("published_at"):
                manifest_parse_unknown += 1
                continue
            published_day = _day(item.get("published_at"))
            if not run_day or not published_day:
                manifest_parse_unknown += 1
            elif published_day <= run_day:
                manifest_pit_items += 1
            else:
                manifest_future_items += 1

    feedback_columns = _columns(conn, "news_shadow_feedback") if "news_shadow_feedback" in tables else set()
    feedback_rows = _rows(conn, "news_shadow_feedback", {"run_id", "created_at", "category", "evidence_ref"} & feedback_columns) if "news_shadow_feedback" in tables else []
    eligible_run_ids = {str(row.get("run_id")) for row in eligible if row.get("run_id") is not None}
    feedback_run_eligible = [row for row in feedback_rows if str(row.get("run_id")) in eligible_run_ids]
    feedback_future_excluded = sum(_after(row.get("created_at"), as_of) for row in feedback_run_eligible)
    feedback_created_unknown = sum(not _day(row.get("created_at")) for row in feedback_run_eligible)
    feedback_eligible = [row for row in feedback_run_eligible if _on_or_before(row.get("created_at"), as_of)] if "created_at" in feedback_columns else []
    available_run_ids = {str(row.get("run_id")) for row in available_runs if row.get("run_id") is not None}
    actually_available_feedback = [row for row in feedback_eligible if str(row.get("run_id")) in available_run_ids]
    feedback_unlinked = sum(row.get("run_id") is None or str(row.get("run_id")) not in {str(r.get("run_id")) for r in runs if r.get("run_id") is not None} for row in feedback_rows)
    feedback_available = "news_shadow_feedback" in tables and {"run_id", "created_at"} <= feedback_columns

    data_reasons: list[str] = []
    if not runs_available:
        data_reasons.append("news_shadow_runs_table_or_fields_missing")
    if not news_coverage_available:
        data_reasons.append("news_content_or_published_at_unavailable")
    if invalid_dates:
        data_reasons.append("invalid_run_dates_present")
    if not available_runs:
        data_reasons.append("no_runs_proven_available_by_as_of")
    data_reasons.append("strict_pit_availability_unverified")
    if future_news:
        data_reasons.append("future_news_rows_excluded_from_as_of_coverage")
    if runs_created_after_cutoff:
        data_reasons.append("run_created_after_as_of_boundary")
    if runs_created_time_unknown:
        data_reasons.append("run_created_at_unknown_availability")
    if manifest_future_items:
        data_reasons.append("future_manifest_items_excluded_from_run_pit_coverage")
    data_status = "blocked" if not available_runs or not runs_available else "unknown"

    runtime_reasons: list[str] = []
    if not latest_day:
        runtime_reasons.append("latest_run_date_unknown")
    elif age_days is not None and age_days > max_staleness_days:
        runtime_reasons.append("latest_run_is_stale")
    if unknown_status_rows or unexpected_statuses:
        runtime_reasons.append("run_status_unknown_or_unrecognized")
    failed = sum(count for status, count in status_counts.items() if status in {"fetch_failed", "score_failed"})
    if failed:
        runtime_reasons.append("failed_runs_present")
    runtime_reasons.append("job_run_and_twenty_day_acceptance_evidence_not_in_scope")
    runtime_status = "blocked" if not available_runs or failed or (age_days is not None and age_days > max_staleness_days) else "unknown"

    review_reasons: list[str] = []
    if not feedback_available:
        review_reasons.append("feedback_table_or_run_id_missing")
    elif not actually_available_feedback:
        review_reasons.append("no_feedback_for_as_of_run_cohort")
    review_reasons.append("independent_gold_fact_review_evidence_not_in_scope")
    if feedback_unlinked:
        review_reasons.append("feedback_references_missing_run")
    review_status = "unknown"

    cost_reasons = ["no_independent_provider_billing_receipt_or_cost_reconciliation"]
    if not run_columns or "tokens_spent" not in run_columns:
        cost_reasons.append("tokens_spent_field_missing")
    if tokens_unknown:
        cost_reasons.append("run_token_values_unknown")
    if token_non_numeric:
        cost_reasons.append("run_token_values_invalid")
    cost_status = "unknown"

    gates = {
        "event_risk": {
            "data": _gate(data_status, data_reasons),
            "runtime": _gate(runtime_status, runtime_reasons),
            "review": _gate(review_status, review_reasons),
            "cost": _gate(cost_status, cost_reasons),
            "readiness": "blocked",
            "promotion_effect": "none; diagnostic gates do not promote",
        },
        "direction": {
            "status": "blocked",
            "direction_weights_allowed": False,
            "reason": "independent direction quality gate and explicit user authorization are not established by this audit",
        },
    }
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "as_of": as_of,
        "as_of_boundary": "date-level inclusive; naive timestamp timezone semantics are not certified",
        "snapshot": {"path": snapshot_path, "sha256": snapshot_sha256, "read_mode": "sqlite mode=ro&immutable=1"},
        "audit_source_sha256": audit_source_sha256,
        "command": command or [],
        "scope": {"owner": "backend.evidence", "consumer": "python -m backend.evidence.news_event_readiness", "offline": True, "calls_provider": False, "reads_runtime_config": False, "writes_database": False, "writes_external_report_only": True},
        "news_shadow_runs": {
            "table_present": "news_shadow_runs" in tables,
            "columns_present": sorted(run_columns),
            "all_history_count": len(runs),
            "eligible_as_of_count": len(eligible),
            "future_runs_excluded": future_runs,
            "eligible_rows_created_after_as_of_boundary": runs_created_after_cutoff,
            "eligible_rows_created_at_unknown": runs_created_time_unknown,
            "actually_available_by_as_of_count": len(available_runs),
            "as_of_metrics_cohort": "runs created on or before the inclusive as_of date; unknown created_at is unavailable",
            "unavailable_eligible_count": len(eligible) - len(available_runs),
            "invalid_date_rows": invalid_dates,
            "latest_eligible_as_of": latest_eligible_day,
            "latest_available_as_of": latest_day,
            "freshness_age_days": age_days,
            "freshness_cohort": "actually_available_by_as_of_count",
            "max_staleness_days": max_staleness_days,
            "status_counts_as_of": dict(sorted(status_counts.items())),
            "status_counts_as_of_cohort": "actually_available_by_as_of_count",
            "status_counts_eligible_historical": dict(sorted(historical_status_counts.items())),
            "failed_run_count": failed,
            "eligible_historical_failed_run_count": sum(
                count for status, count in historical_status_counts.items()
                if status in {"fetch_failed", "score_failed"}
            ),
            "scored_evidence_denominator": len(evidence_rows),
            "evidence_denominator_cohort": "actually_available_by_as_of_count",
            "triggered": triggered,
            "untriggered": untriggered,
            "trigger_unknown": trigger_unknown,
            "trigger_fraction": (triggered / len(evidence_rows)) if evidence_rows else None,
            "trigger_fraction_denominator_note": "status=evidence rows demonstrably created on or before as_of; untriggered and unknown rows remain in denominator",
            "tokens_spent_known_sum_informational_only": token_total,
            "tokens_spent_known_row_count": len(tokens_known),
            "tokens_spent_unknown_row_count": tokens_unknown,
            "tokens_spent_invalid_row_count": token_non_numeric,
            "tokens_spent_historical_known_sum_informational_only": historical_token_total,
            "tokens_spent_historical_known_row_count": len(historical_tokens_known),
            "cost_certified": False,
        },
        "news_coverage": {
            "scope": "all snapshot news rows with required fields; no official universe or lookback-window join",
            "table_present": "news" in tables,
            "required_fields_present": news_coverage_available,
            "eligible_as_of_row_count": len(news_eligible) if news_coverage_available else None,
            "future_rows_excluded": future_news if news_coverage_available else None,
            "published_time_unknown_excluded": news_published_unknown if news_coverage_available else None,
            "rows_with_unknown_fetch_time_excluded": news_fetch_unknown if news_coverage_available else None,
            "rows_fetched_after_as_of_excluded": news_fetch_future if news_coverage_available else None,
            "eligible_rows_fetched_after_as_of_date": news_fetched_after_cutoff,
            "body_present_rows": body_known if news_coverage_available else None,
            "body_coverage": body_coverage,
            "pit_status": "unverified_timestamp_semantics",
            "pit_note": "Published-date filtering excludes future dates; naive timestamp timezone and historical availability-at-run time are not proven.",
        },
        "shadow_manifest_pit": {
            "item_count": manifest_total,
            "unparsed_items_arrays": manifest_arrays_unknown,
            "total_item_count_unknown": manifest_arrays_unknown > 0,
            "items_on_or_before_each_run_day": manifest_pit_items,
            "future_items_excluded": manifest_future_items,
            "parse_or_timestamp_unknown_count": manifest_parse_unknown,
            "coverage": (manifest_pit_items / manifest_total) if manifest_total and not manifest_arrays_unknown else None,
            "status": "unverified_timestamp_semantics",
        },
        "feedback": {
            "table_present": "news_shadow_feedback" in tables,
            "columns_present": sorted(feedback_columns),
            "all_history_count": len(feedback_rows),
            "eligible_as_of_run_count": len(actually_available_feedback),
            "eligible_historical_run_count": len(feedback_eligible),
            "future_feedback_excluded": feedback_future_excluded,
            "feedback_created_at_unknown_excluded": feedback_created_unknown,
            "actually_available_feedback_count": len(actually_available_feedback),
            "unlinked_feedback_count": feedback_unlinked,
            "status_counts": {key: sum(str(row.get("category")) == key for row in actually_available_feedback) for key in sorted({str(row.get("category")) for row in actually_available_feedback if row.get("category") is not None})} if "category" in feedback_columns else None,
            "status_counts_historical": {key: sum(str(row.get("category")) == key for row in feedback_eligible) for key in sorted({str(row.get("category")) for row in feedback_eligible if row.get("category") is not None})} if "category" in feedback_columns else None,
            "evidence_ref_count": sum(bool(row.get("evidence_ref")) for row in actually_available_feedback) if "evidence_ref" in feedback_columns else None,
        },
        "gates": gates,
        "promotion_decision": "not_evaluated; audit never automatically promotes",
        "limitations": ["Date-level filtering is not strict PIT proof.", "Historical as_of does not prove created_at was available at that time.", "News body coverage is snapshot-wide and is not official-pool daily coverage; per-window coverage needs a forward evidence protocol.", "Recorded zero token values are reported as recorded and do not establish zero cost or savings.", "Missing fields and unknown values are not treated as zero."],
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    runs = report["news_shadow_runs"]
    coverage = report["news_coverage"]
    gates = report["gates"]["event_risk"]
    lines = [
        "# Offline News Event Readiness Audit", "",
        f"- As of: {report['as_of']} (inclusive date boundary)",
        f"- Snapshot SHA-256: {report['snapshot']['sha256'] or 'unknown'}",
        f"- Runs: {runs['actually_available_by_as_of_count']} available by as-of / {runs['eligible_as_of_count']} historical as-of rows / {runs['all_history_count']} total; {runs['unavailable_eligible_count']} late or unknown-created rows excluded from as-of metrics; {runs['future_runs_excluded']} future rows excluded",
        f"- Latest run available by as-of: {runs['latest_available_as_of'] or 'unknown'}; age: {runs['freshness_age_days'] if runs['freshness_age_days'] is not None else 'unknown'} days",
        f"- Status counts: `{json.dumps(runs['status_counts_as_of'], ensure_ascii=False, sort_keys=True)}`",
        f"- Trigger count: {runs['triggered']} triggered, {runs['untriggered']} untriggered, {runs['trigger_unknown']} unknown; denominator {runs['scored_evidence_denominator']}",
        f"- Recorded tokens: {runs['tokens_spent_known_sum_informational_only']} known across {runs['tokens_spent_known_row_count']} rows; {runs['tokens_spent_unknown_row_count']} unknown; cost certified: no",
        f"- News bodies: {coverage['body_present_rows'] if coverage['body_present_rows'] is not None else 'unknown'} / {coverage['eligible_as_of_row_count'] if coverage['eligible_as_of_row_count'] is not None else 'unknown'}; PIT: {coverage['pit_status']}",
        "", "## Event-risk gates", "", "| Gate | Status | Reasons |", "|---|---|---|",
    ]
    for name in ("data", "runtime", "review", "cost"):
        gate = gates[name]
        lines.append(f"| {name} | {gate['status']} | {', '.join(gate['reasons']) or 'none'} |")
    lines.extend(["", "## Direction gate", "", "**blocked** — direction weights remain disabled; this audit does not promote.", "", "## Evidence limits", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def _validate_paths(db_path: Path, output_path: Path, *, output_format: str) -> tuple[Path, Path]:
    source = db_path.expanduser().resolve(strict=True)
    target = output_path.expanduser().resolve(strict=False)
    if not source.is_file():
        raise ValueError("--db must point to an existing SQLite snapshot file")
    if target == source or str(target) in {str(source) + "-wal", str(source) + "-shm"}:
        raise ValueError("output must not overwrite the snapshot or its sidecars")
    if target.exists() and source.exists() and target.samefile(source):
        raise ValueError("output must not be a hard link to the snapshot")
    wal_path = Path(str(source) + "-wal")
    if wal_path.exists() and wal_path.stat().st_size > 0:
        raise ValueError("snapshot has a non-empty WAL sidecar; use a consistent immutable snapshot")
    if target == REPO_ROOT or REPO_ROOT in target.parents:
        raise ValueError("report output must be outside the repository")
    if source.is_symlink() or db_path.expanduser().is_symlink():
        raise ValueError("snapshot symlinks are not accepted")
    if output_path.expanduser().is_symlink():
        raise ValueError("report output symlinks are not accepted")
    expected_suffix = ".json" if output_format == "json" else ".md"
    if target.suffix.lower() != expected_suffix:
        raise ValueError(f"{output_format} report output must use {expected_suffix}")
    if target.exists():
        raise ValueError("report output already exists; refusing to overwrite")
    return source, target


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Existing immutable SQLite snapshot path")
    parser.add_argument("--as-of", required=True, help="Inclusive YYYY-MM-DD readiness cutoff")
    parser.add_argument("--max-staleness-days", type=int, default=7)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", required=True, help="External report file path; must be outside repository")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_staleness_days < 0:
        raise SystemExit("--max-staleness-days must be nonnegative")
    try:
        source, target = _validate_paths(Path(args.db), Path(args.output), output_format=args.format)
        before_hash = _sha256(source)
        uri = source.as_uri() + "?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            report = build_readiness(
                conn,
                as_of=args.as_of,
                max_staleness_days=args.max_staleness_days,
                snapshot_sha256=before_hash,
                snapshot_path=str(source),
                audit_source_sha256=_sha256(Path(__file__).resolve()),
                command=["python", "-m", "backend.evidence.news_event_readiness", *list(argv if argv is not None else sys.argv[1:])],
            )
        finally:
            conn.close()
        after_hash = _sha256(source)
        if before_hash != after_hash:
            raise RuntimeError("snapshot changed during audit")
        rendered = report_to_markdown(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as output_file:
            output_file.write(rendered)
        return 0
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"news-event-readiness: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
