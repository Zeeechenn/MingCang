#!/usr/bin/env python3
"""Export stored historical news visible before fixed decision dates.

Read-only SQLite export. This tool makes no source or model calls. Naive DB
timestamps are interpreted as Asia/Shanghai wall time; offset-aware timestamps
are converted to that zone before applying the strict cutoff.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
TABLE_FIELDS = {
    "news": (
        "id",
        "symbol",
        "title",
        "url",
        "published_at",
        "source",
        "fetched_at",
        "content",
        "provider",
        "asset_key",
        "market",
    ),
    "announcements": (
        "id",
        "symbol",
        "title",
        "content",
        "ann_type",
        "published_at",
        "source_url",
        "provider",
        "fetched_at",
        "asset_key",
        "market",
        "currency",
    ),
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_timestamp(raw: object) -> datetime | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def parse_dates(values: list[str]) -> list[date]:
    parsed = [date.fromisoformat(value) for value in values]
    if not parsed:
        raise ValueError("at least one decision date is required")
    if len(parsed) != len(set(parsed)):
        raise ValueError("duplicate decision dates are not allowed")
    return sorted(parsed)


def validate_snapshot_path(db_path: Path) -> Path:
    if db_path.is_symlink():
        raise ValueError(f"SQLite input may not be a symlink: {db_path}")
    resolved = db_path.resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(resolved) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise ValueError(f"SQLite input has a sidecar; use a standalone snapshot: {sidecar}")
    return resolved


def sqlite_uri(path: Path) -> str:
    # Percent-encode spaces, unicode and URI metacharacters in database paths.
    return f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"


def load_table(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[dict]]:
    available = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    fields = [field for field in TABLE_FIELDS[table] if field in available]
    required = {"id", "symbol", "title", "published_at", "fetched_at", "market"}
    if not required.issubset(fields):
        raise RuntimeError(f"{table} lacks required timestamp/identity fields")
    select = ", ".join(f'"{field}"' for field in fields)
    rows = [dict(row) for row in conn.execute(f'SELECT {select} FROM "{table}" ORDER BY id')]
    return fields, rows


def extract(db_path: Path, out_dir: Path, decision_dates: list[date], lookback_days: int) -> dict:
    if lookback_days < 1:
        raise ValueError("lookback calendar days must be >= 1")
    if len(decision_dates) != len(set(decision_dates)):
        raise ValueError("duplicate decision dates are not allowed")
    decision_dates = sorted(decision_dates)
    db_path = validate_snapshot_path(db_path)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"output directory must be new or empty: {out_dir}")
    if out_dir.is_symlink():
        raise ValueError(f"output directory may not be a symlink: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot_sha256_before = file_sha256(db_path)
    conn = sqlite3.connect(sqlite_uri(db_path), uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    if conn.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise RuntimeError("SQLite query_only did not enable")

    rows_by_table: dict[str, list[dict]] = {}
    fields_by_table: dict[str, list[str]] = {}
    for table in TABLE_FIELDS:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists:
            fields_by_table[table], rows_by_table[table] = load_table(conn, table)
        else:
            fields_by_table[table], rows_by_table[table] = [], []
    conn.close()

    report_by_date = {}
    audit: Counter[str] = Counter()
    selected: dict[tuple[str, str], dict] = {}
    total_source_rows = {table: len(rows) for table, rows in rows_by_table.items()}

    for decision_day in decision_dates:
        cutoff = datetime.combine(decision_day, time.min, TZ)
        window_start = cutoff - timedelta(days=lookback_days)
        eligible_symbols: set[str] = set()
        eligible_item_keys: set[tuple[str, str]] = set()
        local_counts: Counter[str] = Counter()
        for table, rows in rows_by_table.items():
            for row in rows:
                audit[f"{table}_rows_scanned"] += 1
                market = row.get("market")
                if market != "CN":
                    audit[f"{table}_excluded_non_cn_or_unknown_market"] += 1
                    continue
                symbol = row.get("symbol")
                if not isinstance(symbol, str) or not re.fullmatch(r"\d{6}", symbol):
                    audit[f"{table}_excluded_invalid_cn_symbol"] += 1
                    continue
                pub = parse_timestamp(row.get("published_at"))
                fetched = parse_timestamp(row.get("fetched_at"))
                if pub is None:
                    audit[f"{table}_invalid_or_missing_published_at"] += 1
                    continue
                if not (window_start <= pub < cutoff):
                    continue
                local_counts[f"{table}_in_published_lookback"] += 1
                if fetched is None:
                    audit[f"{table}_missing_or_invalid_fetched_at_in_window"] += 1
                    continue
                if fetched < pub:
                    audit[f"{table}_fetched_before_published_rejected"] += 1
                    continue
                if fetched >= cutoff:
                    audit[f"{table}_fetched_at_or_after_cutoff"] += 1
                    continue
                key = (table, str(row["id"]))
                eligible_symbols.add(symbol)
                eligible_item_keys.add(key)
                item = selected.setdefault(
                    key,
                    {
                        "source_table": table,
                        "source_row_id": str(row["id"]),
                        "raw_fields": row,
                        "memberships": [],
                    },
                )
                membership = {
                    "symbol": symbol,
                    "decision_date": decision_day.isoformat(),
                    "cutoff_exclusive_local": cutoff.isoformat(),
                    "lookback_start_inclusive_local": window_start.isoformat(),
                    "published_at_local": pub.isoformat(),
                    "fetched_at_local": fetched.isoformat(),
                }
                item["memberships"].append(membership)
                local_counts[f"{table}_eligible_memberships"] += 1
        report_by_date[decision_day.isoformat()] = {
            "cutoff_exclusive_local": cutoff.isoformat(),
            "lookback_start_inclusive_local": window_start.isoformat(),
            "symbols_with_eligible_news": sorted(eligible_symbols),
            "symbol_day_count": len(eligible_symbols),
            "unique_source_rows": len(eligible_item_keys),
            "counts": dict(sorted(local_counts.items())),
            "missing_symbols_are_not_zero_scores": True,
        }

    records = []
    for key in sorted(selected):
        record = selected[key]
        record["memberships"].sort(key=lambda m: (m["decision_date"], m["symbol"]))
        record["record_sha256"] = sha256(
            canonical_bytes(
                {
                    "source_table": record["source_table"],
                    "source_row_id": record["source_row_id"],
                    "raw_fields": record["raw_fields"],
                    "memberships": record["memberships"],
                }
            )
        ).hexdigest()
        record["raw_fields_sha256"] = sha256(canonical_bytes(record["raw_fields"])).hexdigest()
        records.append(record)

    snapshot_sha256_after = file_sha256(db_path)
    if snapshot_sha256_before != snapshot_sha256_after:
        raise RuntimeError(
            "SQLite source snapshot changed during extraction; refusing to emit artifacts"
        )

    records_path = out_dir / "raw_inputs.jsonl"
    with records_path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )

    membership_count = sum(len(record["memberships"]) for record in records)
    unique_records = len(records)
    overlap_repeats = membership_count - unique_records
    overlap_fraction = (overlap_repeats / membership_count) if membership_count else None
    arms = ["legacy-fast", "v2-full", "v2-pyramid"]
    manifest = {
        "schema": "mingcang_historical_news_raw_inputs.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model_run": False,
        "source_calls": False,
        "business_database_write": False,
        "snapshot": {
            "path": str(db_path.resolve()),
            "sha256_before": snapshot_sha256_before,
            "sha256_after": snapshot_sha256_after,
            "sha256": snapshot_sha256_after,
            "sqlite_mode": "ro&immutable=1",
            "query_only": True,
        },
        "extractor": {
            "script_path": str(Path(__file__).resolve()),
            "script_sha256": file_sha256(Path(__file__).resolve()),
            "parameters": {
                "decision_dates": [d.isoformat() for d in decision_dates],
                "lookback_calendar_days": lookback_days,
            },
        },
        "time_policy": {
            "timezone": "Asia/Shanghai",
            "naive_source_timestamps_assumed_timezone": "Asia/Shanghai",
            "cutoff": "strictly before local 00:00 at the decision date (prior local natural day ends)",
            "eligibility": "published_at in [cutoff-lookback_calendar_days, cutoff) AND fetched_at < cutoff",
            "lookback_calendar_days": lookback_days,
            "publication_and_fetch_timestamps_are_preserved_not_backdated": True,
            "pit_certification": "not certified; revision/first-visibility history and model-training contamination unknown",
        },
        "trial_window": {
            "decision_dates": [d.isoformat() for d in decision_dates],
            "by_decision_date": report_by_date,
        },
        "records": {
            "tables_scanned": total_source_rows,
            "unique_database_rows_exported": unique_records,
            "symbol_day_memberships": membership_count,
            "overlapping_window_memberships_removed_by_shared_package": overlap_repeats,
            "overlap_duplicate_membership_fraction": overlap_fraction,
            "raw_input_copies_if_each_arm_received_one_identical_full_package": {
                "arms": arms,
                "package_copies_before_shared_input": len(arms),
                "package_copies_after_shared_input": 1,
                "copies_removed": len(arms) - 1,
                "fraction_of_identical_raw_package_copies_removed": 2 / 3,
                "interpretation": "record-copy accounting only; not token, latency, or billing savings",
            },
            "exported_source_tables": sorted(rows_by_table),
            "exported_fields_by_table": fields_by_table,
            "audit_counts": dict(sorted(audit.items())),
            "missing_news_symbol_days_are_absent_not_filled": True,
        },
        "artifacts": {
            "raw_inputs_jsonl": records_path.name,
            "raw_inputs_jsonl_sha256": file_sha256(records_path),
            "record_hash": "SHA-256 over canonical JSON of source table, source row id, raw fields, and memberships",
            "raw_fields_hash": "SHA-256 over canonical JSON of the exact selected SQLite row fields, including original content and source timestamp strings",
        },
        "arm_identity_and_adapter_readiness": {
            "legacy-fast": {
                "input": "titles only in current implementation",
                "scorer": "backend.analysis.sentiment.analyze_news; current code requests fast tier",
                "known_issue": "model/provider resolved identity is configuration-dependent; old cache identity is insufficient",
            },
            "v2-full": {
                "input": "clustered NewsEvidence; content included when stored, otherwise title-only/degradation behavior",
                "scorer": "backend.data.news_extraction configured provider adapter, usually capable tier",
                "known_issue": "actual provider/model/prompt/schema/call receipts must be frozen; OOS CLI writes score cache DB",
            },
            "v2-pyramid": {
                "input": "v2 evidence plus deterministic trigger/domain-digest/budget gates and process-local reuse",
                "scorer": "same configured v2 extraction adapter for triggered windows; non-triggered windows may reuse last signal",
                "known_issue": "must report triggered, non-triggered, failures and full fixed denominator; never treat missing as neutral",
            },
            "adapter_preparation_needed": [
                "offline adapter that reads this JSONL only and emits a separately versioned request payload per arm",
                "prompt whitelist: symbol, title, URL, source/provider, published_at, fetched_at, and content; preserve content exactly, do not send sentiment_score or other precomputed score fields",
                "frozen requested and resolved model/provider identity, prompt/code/schema hashes, temperature and token limits",
                "one immutable common candidate/symbol-day manifest and explicit per-arm eligibility/missing statuses",
                "isolated scratch result store outside production DB; deterministic idempotency key including arm, model, prompt, input hash and cutoff",
                "per-request raw payload/response bytes and hashes, token/billing receipts, explicit no-retry/no-fallback failure handling",
                "mask training/label references from all three input adapters and freeze time-split/holdout before outcome access",
            ],
        },
    }
    manifest_path = out_dir / "manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="immutable SQLite source snapshot")
    parser.add_argument("--out-dir", type=Path, required=True, help="new or empty output directory")
    parser.add_argument(
        "--decision-date",
        action="append",
        required=True,
        help="local decision date YYYY-MM-DD; repeat for each date",
    )
    parser.add_argument("--lookback-calendar-days", type=int, default=3)
    args = parser.parse_args()
    if args.lookback_calendar_days < 1:
        parser.error("--lookback-calendar-days must be >= 1")
    try:
        decision_dates = parse_dates(args.decision_date)
    except ValueError as exc:
        parser.error(str(exc))
    manifest = extract(args.db, args.out_dir, decision_dates, args.lookback_calendar_days)
    print(
        json.dumps(
            {
                "manifest": str((args.out_dir / "manifest.json").resolve()),
                "records": str((args.out_dir / "raw_inputs.jsonl").resolve()),
                "model_run": manifest["model_run"],
                "symbol_day_counts": {
                    day: item["symbol_day_count"]
                    for day, item in manifest["trial_window"]["by_decision_date"].items()
                },
                "unique_database_rows_exported": manifest["records"][
                    "unique_database_rows_exported"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
