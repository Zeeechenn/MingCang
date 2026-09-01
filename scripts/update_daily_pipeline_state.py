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
# 每条 track 的终局判定。ok/aborted 有对应的 track status（complete/aborted）；
# skipped（行情门未过）与 not_attempted（--one-loop-only 主动跳过）没有——它们
# 既不是失败也不是跑完，沿用既有写法把 track status 留在 running，靠 outcome
# 这一位把语义讲清楚。
VALID_TRACK_OUTCOMES = ("ok", "aborted", "skipped", "not_attempted")


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
    parser.add_argument("--track-status", choices=VALID_STATUSES, default=None)
    parser.add_argument("--track-outcome", choices=VALID_TRACK_OUTCOMES, default=None)
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
    track_status: str | None = None,
    track_outcome: str | None = None,
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
        # track 的状态独立于顶层 status：收尾时顶层还在 running，两条 track 却
        # 已经各自定局，必须能分别回填 complete/aborted，否则 tracks 会永远停在
        # 最后一次 begin_step 写下的 running（2026-08-27/08-28 两轮的记录瑕疵）。
        effective_status = track_status or status
        entry: dict[str, Any] = {
            "status": effective_status,
            "step": step,
            "message": message,
            "updated_at": now,
        }
        # outcome 只在收尾时给，四个取值都表示这条 track 已定局——因此它、而不是
        # 状态位，才是该打 finished_at 的判据：mark_track_failed 在跑到一半写下的
        # aborted 不带 outcome，不能因此显得这条 track 已经收尾。
        if track_outcome is not None:
            entry["outcome"] = track_outcome
            entry["finished_at"] = now
        previous = payload["tracks"].get(track) or {}
        # 收尾时 step 已经是 "done" 了，但一条 aborted 的 track 最有用的信息就是
        # 「在哪一步倒的」——那是跑到一半 mark_track_failed 记下的。终态回填只补
        # outcome/finished_at 和更完整的原因，绝不能把失败步号抹成 done。
        if track_outcome == "aborted" and previous.get("status") == "aborted":
            entry["step"] = previous.get("step", step)
        # 实盘数据门的判决挂在 tracks.live.gate 上，是 ⑤⑥⑦ 之前写入的；本次
        # 覆盖不能把它丢掉（此前每次 begin_step --track live 都会抹掉它）。
        if previous.get("gate") is not None:
            entry["gate"] = previous["gate"]
        payload["tracks"][track] = entry

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
        track_status=args.track_status,
        track_outcome=args.track_outcome,
        gate_json=args.gate_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
