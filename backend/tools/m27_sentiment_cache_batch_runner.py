"""Resume-safe M27.3 sentiment_cache batch backfill runner.

This runner wraps ``m27_sentiment_cache_backfill`` in small explicit batches so
long real backfills can be resumed from the SQLite cache and per-batch
audit/rollback manifests. It defaults to dry-run and does not touch production
signals.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.tools.m27_sentiment_cache_backfill import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_PLAN_PATH,
    SentimentRunner,
    run_backfill,
)

DEFAULT_AUDIT_DIR = Path.home() / ".stock-sage" / "m27_sentiment_cache_backfill_batches"
DEFAULT_SUMMARY_OUTPUT = Path.home() / ".stock-sage" / "m27_sentiment_cache_batch_runner_summary.json"


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_batch_runner(
    plan_path: Path = DEFAULT_PLAN_PATH,
    *,
    db_url: str | None = None,
    execute: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batches: int = 1,
    max_llm_calls_total: int = DEFAULT_BATCH_SIZE,
    audit_dir: Path = DEFAULT_AUDIT_DIR,
    summary_output: Path | None = DEFAULT_SUMMARY_OUTPUT,
    run_id: str | None = None,
    sentiment_runner: SentimentRunner | None = None,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_batches <= 0:
        raise ValueError("max_batches must be positive")
    if max_llm_calls_total < 0:
        raise ValueError("max_llm_calls_total must be non-negative")
    if execute and not db_url:
        raise ValueError("--execute requires explicit --db-url")
    if execute and max_llm_calls_total <= 0:
        raise ValueError("--execute requires positive --max-llm-calls-total")

    run_id = run_id or f"m27_sentiment_cache_{_timestamp()}"
    audit_dir = audit_dir.expanduser()
    batches: list[dict[str, Any]] = []
    total_inserted = 0
    total_llm_calls = 0
    stop_reason = "max_batches_reached"

    iterations = max_batches if execute else 1
    for batch_index in range(1, iterations + 1):
        remaining_calls = max_llm_calls_total - total_llm_calls
        if execute and remaining_calls <= 0:
            stop_reason = "max_llm_calls_total_reached"
            break
        limit = min(batch_size, remaining_calls) if execute else batch_size
        audit_path = audit_dir / f"{run_id}_batch_{batch_index:03d}_audit.json"
        rollback_path = audit_dir / f"{run_id}_batch_{batch_index:03d}_rollback.json"
        result = run_backfill(
            plan_path,
            db_url=db_url,
            execute=execute,
            max_keys=limit,
            batch_size=limit,
            max_llm_calls=limit,
            audit_output=audit_path,
            rollback_output=rollback_path,
            sentiment_runner=sentiment_runner,
        )
        audit = result["audit"]
        summary = audit["summary"]
        selected = int(summary["selected_cache_keys"])
        inserted = int(summary["inserted_cache_keys"])
        llm_calls = int(summary["llm_calls"])
        total_inserted += inserted
        total_llm_calls += llm_calls
        batches.append({
            "batch": batch_index,
            "audit_output": str(audit_path),
            "rollback_output": str(rollback_path),
            "pending_before_batch": summary["pending_cache_keys"],
            "selected_cache_keys": selected,
            "inserted_cache_keys": inserted,
            "llm_calls": llm_calls,
            "existing_cache_keys": summary["existing_cache_keys"],
        })

        if selected == 0:
            stop_reason = "no_pending_keys"
            break
        if not execute:
            stop_reason = "dry_run_only"
            break
        if inserted == 0:
            stop_reason = "no_insertions_in_batch"
            break
        if total_llm_calls >= max_llm_calls_total:
            stop_reason = "max_llm_calls_total_reached"
            break

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": "backend.tools.m27_sentiment_cache_batch_runner",
        "run_id": run_id,
        "execute": execute,
        "writes_db": execute,
        "calls_llm_or_api": execute,
        "production_unchanged": True,
        "plan_path": str(plan_path),
        "db_url_provided": db_url is not None,
        "limits": {
            "batch_size": batch_size,
            "max_batches": max_batches,
            "max_llm_calls_total": max_llm_calls_total,
        },
        "summary": {
            "batches_attempted": len(batches),
            "inserted_cache_keys": total_inserted,
            "llm_calls": total_llm_calls,
            "stop_reason": stop_reason,
        },
        "batches": batches,
        "next_steps": [
            "rerun this runner with another bounded max-batches value until pending keys reach zero",
            "rerun m27_alpha_diagnostic --event-ab after cache alignment is complete or at review checkpoints",
        ],
    }
    if summary_output is not None:
        _write_json(summary_output, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--db-url", help="Explicit sqlite:///... URL. Required for --execute.")
    parser.add_argument("--execute", action="store_true", help="Actually run bounded LLM/API backfill batches")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--max-llm-calls-total", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--run-id")
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_batch_runner(
        args.plan,
        db_url=args.db_url,
        execute=args.execute,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        max_llm_calls_total=args.max_llm_calls_total,
        audit_dir=args.audit_dir,
        summary_output=args.summary_output,
        run_id=args.run_id,
    )
    summary = report["summary"]
    print(
        "M27.3 sentiment_cache batch runner "
        f"{'execute' if report['execute'] else 'dry_run'}: "
        f"batches={summary['batches_attempted']} "
        f"inserted={summary['inserted_cache_keys']} "
        f"llm_calls={summary['llm_calls']} "
        f"stop={summary['stop_reason']}"
    )
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
