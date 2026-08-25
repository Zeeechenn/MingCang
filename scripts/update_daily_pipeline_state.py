#!/usr/bin/env python3
"""Atomically update the machine-readable state for the daily pipeline."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "daily_pipeline.v1"
VALID_STATUSES = ("running", "aborted", "complete")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--status", required=True, choices=VALID_STATUSES)
    parser.add_argument("--step", required=True)
    parser.add_argument("--message", default="")
    parser.add_argument("--one-loop-status", choices=("pending", "complete"), default=None)
    parser.add_argument("--llm-calls", type=int, default=None)
    return parser


def update_state(
    path: Path,
    *,
    day: str,
    status: str,
    step: str,
    message: str,
    one_loop_status: str | None = None,
    llm_calls: int | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("date") != day:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "date": day,
            "started_at": now,
            "events": [],
            "one_loop_status": "pending",
        }

    event = {"at": now, "status": status, "step": step, "message": message}
    payload.update(
        {
            "status": status,
            "current_step": step,
            "message": message,
            "updated_at": now,
            "pid": os.getppid(),
        }
    )
    payload.setdefault("events", []).append(event)
    if one_loop_status is not None:
        payload["one_loop_status"] = one_loop_status
    if llm_calls is not None:
        payload["llm_calls_total"] = llm_calls
    if status in {"aborted", "complete"}:
        payload["finished_at"] = now
    else:
        payload.pop("finished_at", None)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    update_state(
        Path(args.path),
        day=args.date,
        status=args.status,
        step=args.step,
        message=args.message,
        one_loop_status=args.one_loop_status,
        llm_calls=args.llm_calls,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
