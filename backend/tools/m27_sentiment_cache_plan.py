"""Build a dry-run M27.3 sentiment_cache backfill plan from exported misses.

This tool intentionally reads only the cache-miss JSON exported by
``m27_alpha_diagnostic --event-ab-cache-missing-output``. It does not call an
LLM/API and it does not write ``sentiment_cache``. If a SQLite DB URL is
explicitly provided, it is opened in read-only mode only to count keys that may
have been filled after the export was produced.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.analysis.sentiment import _cache_key

DEFAULT_BATCH_SIZE = 25


def _as_titles(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _load_windows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cache-miss export must be a JSON object")
    windows = payload.get("windows")
    if not isinstance(windows, list):
        raise ValueError("cache-miss export must contain a windows list")
    return payload, [row for row in windows if isinstance(row, dict)]


def _normalize_window(row: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_symbol = str(row.get("symbol") or "").strip()
    titles = _as_titles(row.get("titles"))
    if not raw_symbol or not titles:
        return None, {
            "index": index,
            "symbol": raw_symbol or None,
            "date": str(row.get("date") or ""),
            "reason": "missing_symbol_or_titles",
        }
    symbol = raw_symbol
    expected_cache_key, expected_titles_hash = _cache_key(titles, symbol)
    provided_cache_key = str(row.get("cache_key") or "")
    provided_titles_hash = str(row.get("titles_hash") or "")
    if provided_cache_key and provided_cache_key != expected_cache_key:
        return None, {
            "index": index,
            "symbol": symbol,
            "date": str(row.get("date") or ""),
            "reason": "cache_key_mismatch",
            "provided_cache_key": provided_cache_key,
            "expected_cache_key": expected_cache_key,
        }
    if provided_titles_hash and provided_titles_hash != expected_titles_hash:
        return None, {
            "index": index,
            "symbol": symbol,
            "date": str(row.get("date") or ""),
            "reason": "titles_hash_mismatch",
            "provided_titles_hash": provided_titles_hash,
            "expected_titles_hash": expected_titles_hash,
        }
    return {
        "symbol": symbol,
        "date": str(row.get("date") or ""),
        "titles": titles,
        "cache_key": expected_cache_key,
        "titles_hash": expected_titles_hash,
        "news_count": int(row.get("news_count") or len(titles)),
        "event_score_mode": str(row.get("event_score_mode") or ""),
    }, None


def _sqlite_path_from_url(db_url: str) -> Path:
    parsed = urlparse(db_url)
    if parsed.scheme != "sqlite":
        raise ValueError("only sqlite:/// DB URLs are supported for read-only checks")
    if parsed.netloc and parsed.netloc != "":
        raise ValueError("sqlite DB URL must point to a local file")
    path = unquote(parsed.path)
    if not path:
        raise ValueError("sqlite DB URL is missing a path")
    return Path(path).expanduser()


def _count_existing_cache_keys(db_url: str, cache_keys: list[str]) -> int:
    if not cache_keys:
        return 0
    db_path = _sqlite_path_from_url(db_url).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        try:
            con.execute("SELECT 1 FROM sentiment_cache LIMIT 1")
        except sqlite3.OperationalError:
            return 0
        found: set[str] = set()
        for idx in range(0, len(cache_keys), 500):
            chunk = cache_keys[idx : idx + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = con.execute(
                f"SELECT cache_key FROM sentiment_cache WHERE cache_key IN ({placeholders})",  # noqa: S608
                chunk,
            ).fetchall()
            found.update(str(row[0]) for row in rows)
        return len(found)
    finally:
        con.close()


def build_plan(
    export_path: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    db_url: str | None = None,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    export_payload, raw_windows = _load_windows(export_path)
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
                "symbols": set(),
                "windows": 0,
                "news_count_max": 0,
                "sample_date": window["date"],
                "sample_titles": window["titles"],
                "source_dates": set(),
                "event_score_modes": set(),
            },
        )
        entry["symbols"].add(window["symbol"])
        if window["date"]:
            entry["source_dates"].add(window["date"])
        if window["event_score_mode"]:
            entry["event_score_modes"].add(window["event_score_mode"])
        entry["windows"] += 1
        entry["news_count_max"] = max(entry["news_count_max"], window["news_count"])

    deduped_rows = []
    for entry in by_key.values():
        deduped_rows.append({
            **entry,
            "symbols": sorted(entry["symbols"]),
            "source_dates": sorted(entry["source_dates"]),
            "event_score_modes": sorted(entry["event_score_modes"]),
        })
    deduped_rows.sort(key=lambda row: (-row["windows"], row["cache_key"]))

    existing_cache_keys = _count_existing_cache_keys(db_url, sorted(by_key)) if db_url else 0
    estimated_llm_calls = max(0, len(by_key) - existing_cache_keys)
    batch_count = math.ceil(estimated_llm_calls / batch_size) if estimated_llm_calls else 0

    risks = [
        "dry_run_only_no_sentiment_cache_writes",
        "no_llm_or_api_calls_are_made_by_this_tool",
        "export_may_be_stale_if_news_or_cache_changed_after_generation",
    ]
    if db_url is None:
        risks.append("db_not_checked_by_design_pass_explicit_db_url_for_readonly_recheck")
    if len(windows) != len(raw_windows):
        risks.append("some_windows_were_skipped_because_required_fields_or_cache_keys_were_invalid")
    if invalid_windows:
        risks.append("invalid_windows_require_review_before_any_backfill_writer")

    next_steps = [
        "review_plan_counts_against_m27_event_ab_cache_missing_export",
        "if_counts_look_safe_run_a_separately_approved_backfill_writer_in_small_batches",
        "rerun_m27_alpha_diagnostic_event_ab_after_any_approved_backfill",
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "purpose": "M27.3 dry-run sentiment_cache backfill planning; no writes and no LLM/API calls",
        "input": {
            "path": str(export_path),
            "generated_at": export_payload.get("generated_at"),
            "exported_cache_miss_windows": export_payload.get("cache_miss_windows"),
        },
        "db_check": {
            "enabled": db_url is not None,
            "mode": "sqlite_readonly" if db_url else "not_connected",
            "existing_cache_keys": existing_cache_keys,
        },
        "summary": {
            "total_windows": len(windows),
            "unique_symbols": len({window["symbol"] for window in windows}),
            "deduped_cache_keys": len(by_key),
            "duplicate_windows": max(0, len(windows) - len(by_key)),
            "invalid_windows": len(invalid_windows),
            "estimated_llm_calls": estimated_llm_calls,
        },
        "batch_recommendation": {
            "batch_size": batch_size,
            "estimated_batches": batch_count,
            "strategy": "process deduped cache keys once, persist results only in a separately approved writer",
        },
        "invalid_windows_sample": invalid_windows[:10],
        "deduped_cache_keys_sample": deduped_rows[:10],
        "risks": risks,
        "next_steps": next_steps,
    }


def plan_to_markdown(plan: dict[str, Any]) -> str:
    summary = plan["summary"]
    batch = plan["batch_recommendation"]
    db_check = plan["db_check"]
    lines = [
        "# M27.3 Sentiment Cache Backfill Dry-Run Plan",
        "",
        f"- generated_at: {plan['generated_at']}",
        f"- input: {plan['input']['path']}",
        f"- db_check: {db_check['mode']} / existing_cache_keys={db_check['existing_cache_keys']}",
        "",
        "## Summary",
        "",
        f"- total_windows: {summary['total_windows']}",
        f"- unique_symbols: {summary['unique_symbols']}",
        f"- deduped_cache_keys: {summary['deduped_cache_keys']}",
        f"- duplicate_windows: {summary['duplicate_windows']}",
        f"- invalid_windows: {summary['invalid_windows']}",
        f"- estimated_llm_calls: {summary['estimated_llm_calls']}",
        "",
        "## Batch Recommendation",
        "",
        f"- batch_size: {batch['batch_size']}",
        f"- estimated_batches: {batch['estimated_batches']}",
        f"- strategy: {batch['strategy']}",
        "",
        "## Top Deduped Keys",
        "",
        "| cache_key | windows | symbols | news_count_max | sample_date |",
        "| --- | ---: | --- | ---: | --- |",
    ]
    for row in plan["deduped_cache_keys_sample"]:
        lines.append(
            f"| {row['cache_key']} | {row['windows']} | {','.join(row['symbols'])} | "
            f"{row['news_count_max']} | {row['sample_date']} |"
        )
    lines += [
        "",
        "## Risks",
        "",
    ]
    lines.extend(f"- {risk}" for risk in plan["risks"])
    lines += [
        "",
        "## Next Steps",
        "",
    ]
    lines.extend(f"- {step}" for step in plan["next_steps"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Exported M27.3 cache-miss JSON")
    parser.add_argument("--db-url", help="Optional explicit sqlite:///... URL for read-only sentiment_cache recheck")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--json-output", type=Path, help="Write JSON plan to this path")
    parser.add_argument("--markdown-output", type=Path, help="Write Markdown plan to this path")
    parser.add_argument("--print", action="store_true", help="Print Markdown plan to stdout")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = build_plan(args.input, batch_size=args.batch_size, db_url=args.db_url)
    markdown = plan_to_markdown(plan)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON plan: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown, encoding="utf-8")
        print(f"Markdown plan: {args.markdown_output}")
    if args.print or not args.json_output and not args.markdown_output:
        print(markdown)


if __name__ == "__main__":
    main()
