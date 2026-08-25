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
    parser.add_argument("--track", choices=("one_loop", "live"), default=None)
    parser.add_argument("--gate-json", default=None)
    return parser


def _load_gate_json(gate_json_path: str | None) -> dict[str, Any] | None:
    """读取 --gate-json 指向的判决文件，挂到 payload["tracks"]["live"]["gate"]。

    文件不存在或解析失败时不让整个命令失败——挂一个 {"error": "..."} 即可，
    状态文件写入本身不能成为流水线的失败点。
    """
    if gate_json_path is None:
        return None
    try:
        return json.loads(Path(gate_json_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        return {"error": str(exc)}


def update_state(
    path: Path,
    *,
    day: str,
    status: str,
    step: str,
    message: str,
    one_loop_status: str | None = None,
    llm_calls: int | None = None,
    track: str | None = None,
    gate_json: str | None = None,
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
            "tracks": {},
        }
    payload.setdefault("tracks", {})

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

    if track is not None:
        payload["tracks"][track] = {
            "status": status,
            "step": step,
            "message": message,
            "updated_at": now,
        }

    gate_payload = _load_gate_json(gate_json)
    if gate_payload is not None:
        payload["tracks"].setdefault("live", {})
        payload["tracks"]["live"]["gate"] = gate_payload

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
        track=args.track,
        gate_json=args.gate_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
