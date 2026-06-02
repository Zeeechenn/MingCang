"""Conservative M27.3 sentiment_cache backfill writer.

Default mode is dry-run: no LLM/API calls and no database writes. Real writes
require ``--execute`` plus an explicit SQLite ``--db-url``. The tool reloads
the cache-miss export referenced by the dry-run plan and revalidates keys with
the current ``backend.analysis.sentiment._cache_key`` before any work.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.analysis.event_taxonomy import apply_event_score
from backend.analysis.sentiment import _SENTIMENT_TOOL, SYSTEM_PROMPT, _cache_key
from backend.llm import get_provider, has_runtime_llm_provider, runtime_readiness
from backend.tools.m27_sentiment_cache_plan import (
    _load_windows,
    _normalize_window,
    _sqlite_path_from_url,
)

DEFAULT_PLAN_PATH = Path("~/.stock-sage/m27_sentiment_cache_plan.json")
DEFAULT_AUDIT_PATH = Path("~/.stock-sage/m27_sentiment_cache_backfill_audit.json")
DEFAULT_ROLLBACK_PATH = Path("~/.stock-sage/m27_sentiment_cache_backfill_rollback.json")
DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_KEYS = 25
DEFAULT_MAX_LLM_CALLS = 25


SentimentRunner = Callable[[list[str], str], dict[str, Any]]


def _load_plan(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sentiment cache plan must be a JSON object")
    if isinstance(payload.get("windows"), list):
        plan = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "input": {"path": str(path)},
            "summary": {},
        }
        _items, invalid_windows, summary = _collect_items(plan)
        if invalid_windows:
            summary["invalid_windows"] = len(invalid_windows)
        plan["summary"] = summary
        return plan
    if payload.get("summary", {}).get("invalid_windows", 0):
        raise ValueError("plan has invalid_windows; rerun/fix the plan before backfill")
    input_path = payload.get("input", {}).get("path")
    if not input_path:
        raise ValueError("plan JSON is missing input.path")
    return payload


def _collect_items(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    export_path = Path(str(plan["input"]["path"])).expanduser()
    _export_payload, raw_windows = _load_windows(export_path)
    windows: list[dict[str, Any]] = []
    invalid_windows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_windows):
        window, invalid = _normalize_window(row, index)
        if window is not None:
            windows.append(window)
        if invalid is not None:
            invalid_windows.append(invalid)

    by_key: dict[str, dict[str, Any]] = {}
    for window in windows:
        entry = by_key.setdefault(
            window["cache_key"],
            {
                "cache_key": window["cache_key"],
                "titles_hash": window["titles_hash"],
                "symbol": window["symbol"],
                "symbols": set(),
                "titles": window["titles"],
                "windows": 0,
                "source_dates": set(),
            },
        )
        expected_key, expected_hash = _cache_key(entry["titles"], entry["symbol"])
        if expected_key != entry["cache_key"] or expected_hash != entry["titles_hash"]:
            invalid_windows.append({
                "cache_key": entry["cache_key"],
                "symbol": entry["symbol"],
                "reason": "plan_key_current_cache_key_mismatch",
                "expected_cache_key": expected_key,
                "expected_titles_hash": expected_hash,
            })
        entry["symbols"].add(window["symbol"])
        if window["date"]:
            entry["source_dates"].add(window["date"])
        entry["windows"] += 1

    items = []
    for entry in by_key.values():
        items.append({
            **entry,
            "symbols": sorted(entry["symbols"]),
            "source_dates": sorted(entry["source_dates"]),
        })
    items.sort(key=lambda row: (-row["windows"], row["cache_key"]))
    summary = {
        "total_windows": len(windows),
        "deduped_cache_keys": len(items),
        "duplicate_windows": max(0, len(windows) - len(items)),
        "invalid_windows": len(invalid_windows),
    }
    return items, invalid_windows, summary


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_cache (
            cache_key TEXT PRIMARY KEY,
            symbol TEXT,
            titles_hash TEXT,
            result_json TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)
    try:
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_cache_symbol_hash
            ON sentiment_cache(symbol, titles_hash)
        """)
    except sqlite3.OperationalError:
        # Some tests and ad-hoc dry-run DBs only expose cache_key for existence checks.
        pass


def _existing_keys(con: sqlite3.Connection, cache_keys: list[str]) -> set[str]:
    if not cache_keys:
        return set()
    try:
        con.execute("SELECT 1 FROM sentiment_cache LIMIT 1")
    except sqlite3.OperationalError:
        return set()
    found: set[str] = set()
    for idx in range(0, len(cache_keys), 500):
        chunk = cache_keys[idx : idx + 500]
        placeholders = ",".join("?" * len(chunk))
        rows = con.execute(
            f"SELECT cache_key FROM sentiment_cache WHERE cache_key IN ({placeholders})",  # noqa: S608
            chunk,
        ).fetchall()
        found.update(str(row[0]) for row in rows)
    return found


def _connect_sqlite(db_url: str, *, execute: bool) -> sqlite3.Connection:
    db_path = _sqlite_path_from_url(db_url).resolve()
    if execute:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _call_llm_sentiment(titles: list[str], symbol: str) -> dict[str, Any]:
    if not has_runtime_llm_provider():
        readiness = runtime_readiness()
        raise RuntimeError(f"runtime LLM provider is not usable: {readiness.get('reason')}")
    prompt = f"股票代码：{symbol}\n新闻标题：\n" + "\n".join(f"- {title}" for title in titles[:15])
    data = get_provider().complete_structured(
        prompt=prompt,
        tool=_SENTIMENT_TOOL,
        system=SYSTEM_PROMPT,
        max_tokens=300,
        model_tier="fast",
    )
    if not data:
        data = {"sentiment": 0.0, "summary": "解析失败", "impact": "short", "key_events": []}
    data["sentiment"] = max(-1.0, min(1.0, float(data.get("sentiment", 0))))
    data["key_events"] = list(data.get("key_events") or [])[:3]
    return apply_event_score(data, titles)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_progress_files(
    *,
    audit_output: Path | None,
    rollback_output: Path | None,
    now: str,
    plan_path: Path,
    db_url: str | None,
    max_keys: int,
    batch_size: int,
    max_llm_calls: int,
    item_count: int,
    existing_count: int,
    pending_count: int,
    selected_count: int,
    analyzed: int,
    inserted: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    mode: str,
) -> None:
    audit = {
        "generated_at": now,
        "milestone": "M27.3",
        "mode": mode,
        "decision": "backfill_in_progress" if mode == "execute_partial" else "backfill_executed",
        "writes_db": mode.startswith("execute"),
        "calls_llm_or_api": mode.startswith("execute"),
        "plan_path": str(plan_path),
        "db_url_provided": db_url is not None,
        "limits": {"max_keys": max_keys, "batch_size": batch_size, "max_llm_calls": max_llm_calls},
        "summary": {
            "plan_deduped_cache_keys": item_count,
            "existing_cache_keys": existing_count,
            "pending_cache_keys": pending_count,
            "selected_cache_keys": selected_count,
            "estimated_batches": math.ceil(selected_count / batch_size) if selected_count else 0,
            "llm_calls": analyzed,
            "inserted": len(inserted),
            "inserted_cache_keys": len(inserted),
            "skipped_existing_cache_keys": existing_count,
        },
        "selected_cache_keys_sample": [
            {
                "cache_key": item["cache_key"],
                "symbol": item["symbol"],
                "titles_hash": item["titles_hash"],
                "windows": item["windows"],
                "source_dates": item["source_dates"][:5],
            }
            for item in selected[:10]
        ],
    }
    rollback = {
        "generated_at": now,
        "mode": mode,
        "db_url_provided": db_url is not None,
        "rollback_type": "delete_inserted_keys_only_no_overwrites",
        "inserted_keys": inserted,
        "inserted_cache_keys": inserted,
        "rollback_sql": [
            "DELETE FROM sentiment_cache WHERE cache_key = ?",
        ] if inserted else [],
    }
    if audit_output is not None:
        _write_json(audit_output, audit)
    if rollback_output is not None:
        _write_json(rollback_output, rollback)


def run_backfill(
    plan_path: Path,
    *,
    db_url: str | None = None,
    execute: bool = False,
    max_keys: int = DEFAULT_MAX_KEYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS,
    audit_output: Path | None = DEFAULT_AUDIT_PATH,
    rollback_output: Path | None = DEFAULT_ROLLBACK_PATH,
    sentiment_runner: SentimentRunner | None = None,
) -> dict[str, Any]:
    if max_keys < 0 or batch_size <= 0 or max_llm_calls < 0:
        raise ValueError("max_keys/max_llm_calls must be non-negative and batch_size must be positive")
    if execute and not db_url:
        raise ValueError("--execute requires explicit --db-url")

    plan = _load_plan(plan_path)
    items, invalid_windows, recomputed_summary = _collect_items(plan)
    plan_summary = plan.get("summary", {})
    for field in ("total_windows", "deduped_cache_keys", "duplicate_windows", "invalid_windows"):
        if int(plan_summary.get(field, -1)) != recomputed_summary[field]:
            raise ValueError(f"plan summary mismatch for {field}; rerun m27_sentiment_cache_plan")
    if invalid_windows:
        raise ValueError("current cache-key validation found invalid_windows; aborting backfill")

    con: sqlite3.Connection | None = None
    existing: set[str] = set()
    if db_url:
        con = _connect_sqlite(db_url, execute=execute)
        if execute:
            _ensure_schema(con)
        existing = _existing_keys(con, [item["cache_key"] for item in items])

    pending = [item for item in items if item["cache_key"] not in existing]
    selected = pending[:max_keys]
    stop_reasons: list[str] = []
    if len(selected) > max_llm_calls:
        stop_reasons.append("selected_keys_exceed_max_llm_calls")
    if stop_reasons:
        if con is not None:
            con.close()
        raise ValueError("; ".join(stop_reasons))

    now = datetime.now(UTC).isoformat(timespec="seconds")
    inserted: list[dict[str, Any]] = []
    analyzed = 0
    if execute and selected:
        assert con is not None
        runner = sentiment_runner or _call_llm_sentiment
        try:
            for batch_start in range(0, len(selected), batch_size):
                batch = selected[batch_start : batch_start + batch_size]
                for item in batch:
                    result = runner(list(item["titles"]), str(item["symbol"]))
                    if not result:
                        raise RuntimeError(
                            f"empty sentiment result for cache_key={item['cache_key']}; "
                            "aborting batch without writing fallback cache"
                        )
                    payload = json.dumps(result, ensure_ascii=False)
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO sentiment_cache
                        (cache_key, symbol, titles_hash, result_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (item["cache_key"], item["symbol"], item["titles_hash"], payload, now, now),
                    )
                    analyzed += 1
                    if cur.rowcount == 1:
                        inserted.append({
                            "cache_key": item["cache_key"],
                            "symbol": item["symbol"],
                            "titles_hash": item["titles_hash"],
                        })
                con.commit()
                _write_progress_files(
                    audit_output=audit_output,
                    rollback_output=rollback_output,
                    now=now,
                    plan_path=plan_path,
                    db_url=db_url,
                    max_keys=max_keys,
                    batch_size=batch_size,
                    max_llm_calls=max_llm_calls,
                    item_count=len(items),
                    existing_count=len(existing),
                    pending_count=len(pending),
                    selected_count=len(selected),
                    analyzed=analyzed,
                    inserted=inserted,
                    selected=selected,
                    mode="execute_partial",
                )
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
    elif con is not None:
        con.close()

    audit = {
        "generated_at": now,
        "milestone": "M27.3",
        "mode": "execute" if execute else "dry_run",
        "decision": "backfill_executed" if execute else "dry_run_ready",
        "writes_db": bool(execute and inserted),
        "calls_llm_or_api": bool(execute and selected),
        "plan_path": str(plan_path),
        "db_url_provided": db_url is not None,
        "limits": {"max_keys": max_keys, "batch_size": batch_size, "max_llm_calls": max_llm_calls},
        "summary": {
            "plan_deduped_cache_keys": len(items),
            "existing_cache_keys": len(existing),
            "pending_cache_keys": len(pending),
            "selected_cache_keys": len(selected),
            "estimated_batches": math.ceil(len(selected) / batch_size) if selected else 0,
            "llm_calls": analyzed,
            "inserted": len(inserted),
            "inserted_cache_keys": len(inserted),
            "skipped_existing_cache_keys": len(existing),
        },
        "selected_cache_keys_sample": [
            {
                "cache_key": item["cache_key"],
                "symbol": item["symbol"],
                "titles_hash": item["titles_hash"],
                "windows": item["windows"],
                "source_dates": item["source_dates"][:5],
            }
            for item in selected[:10]
        ],
    }
    rollback = {
        "generated_at": now,
        "mode": "execute" if execute else "dry_run",
        "db_url_provided": db_url is not None,
        "rollback_type": "delete_inserted_keys_only_no_overwrites",
        "inserted_keys": inserted,
        "inserted_cache_keys": inserted,
        "rollback_sql": [
            "DELETE FROM sentiment_cache WHERE cache_key = ?",
        ] if inserted else [],
    }
    if audit_output is not None:
        _write_json(audit_output, audit)
    if rollback_output is not None:
        _write_json(rollback_output, rollback)
    return {"audit": audit, "rollback": rollback}


def build_backfill_report(
    input_path: Path,
    *,
    db_url: str | None = None,
    execute: bool = False,
    max_keys: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_llm_calls: int | None = None,
    audit_output: Path | None = None,
    rollback_output: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if execute and (max_keys is None or max_llm_calls is None):
        raise ValueError("--execute requires explicit --max-keys and --max-llm-calls")
    result = run_backfill(
        input_path,
        db_url=db_url,
        execute=execute,
        max_keys=DEFAULT_MAX_KEYS if max_keys is None else max_keys,
        batch_size=batch_size,
        max_llm_calls=DEFAULT_MAX_LLM_CALLS if max_llm_calls is None else max_llm_calls,
        audit_output=audit_output,
        rollback_output=rollback_output,
    )
    return result["audit"], result["rollback"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH, help="M27.3 sentiment cache plan JSON")
    parser.add_argument("--db-url", help="Explicit sqlite:///... URL. Required for --execute.")
    parser.add_argument("--execute", action="store_true", help="Actually call LLM and insert missing cache rows")
    parser.add_argument("--max-keys", type=int, default=DEFAULT_MAX_KEYS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-llm-calls", type=int, default=DEFAULT_MAX_LLM_CALLS)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--rollback-output", type=Path, default=DEFAULT_ROLLBACK_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_backfill(
        args.plan,
        db_url=args.db_url,
        execute=args.execute,
        max_keys=args.max_keys,
        batch_size=args.batch_size,
        max_llm_calls=args.max_llm_calls,
        audit_output=args.audit_output,
        rollback_output=args.rollback_output,
    )
    audit = result["audit"]
    print(
        "M27.3 sentiment_cache backfill "
        f"{audit['mode']}: selected={audit['summary']['selected_cache_keys']} "
        f"inserted={audit['summary']['inserted_cache_keys']} "
        f"llm_calls={audit['summary']['llm_calls']}"
    )


if __name__ == "__main__":
    main()
