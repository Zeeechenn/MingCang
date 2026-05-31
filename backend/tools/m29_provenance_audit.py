"""Audit M29 price/artifact provenance readiness without side effects."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.data.database import IndexPrice, MarketSnapshot, Price
from backend.tools import m29_evidence_ledger

DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m29_provenance_audit.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m29_provenance_audit.md"
DAILY_PRICE_PROVENANCE_FIELDS = {"source", "fetched_at", "adjustment"}
ARTIFACT_PROVENANCE_FIELDS = set(m29_evidence_ledger.PROVENANCE_REQUIRED_FIELDS)


def _table_columns(model: Any) -> set[str]:
    return {column.name for column in model.__table__.columns}


def _schema_gap(model: Any, required: set[str]) -> dict[str, Any]:
    columns = _table_columns(model)
    missing = sorted(required - columns)
    return {
        "table": model.__tablename__,
        "present": sorted(required & columns),
        "missing": missing,
        "can_prove_required_provenance": not missing,
    }


def _entry_missing_summary(ledger: dict[str, Any]) -> dict[str, Any]:
    entries = ledger.get("entries") or []
    by_field = {field: 0 for field in sorted(ARTIFACT_PROVENANCE_FIELDS)}
    examples: list[dict[str, Any]] = []
    for entry in entries:
        missing = list((entry.get("provenance") or {}).get("missing_provenance_fields") or [])
        for field in missing:
            by_field[field] = by_field.get(field, 0) + 1
        if missing and len(examples) < 5:
            examples.append({
                "candidate": entry.get("candidate"),
                "variant": entry.get("variant"),
                "source_artifact": entry.get("source_artifact"),
                "missing_provenance_fields": missing,
            })
    return {
        "entries": len(entries),
        "entries_with_missing_provenance": sum(
            1 for entry in entries if (entry.get("provenance") or {}).get("missing_provenance_fields")
        ),
        "missing_by_field": by_field,
        "examples": examples,
    }


def build_audit(artifact_paths: list[Path] | None = None) -> dict[str, Any]:
    paths = artifact_paths or m29_evidence_ledger.DEFAULT_ARTIFACTS
    ledger = m29_evidence_ledger.build_ledger(paths)
    price_schema = _schema_gap(Price, DAILY_PRICE_PROVENANCE_FIELDS)
    index_schema = _schema_gap(IndexPrice, DAILY_PRICE_PROVENANCE_FIELDS)
    snapshot_schema = _schema_gap(MarketSnapshot, {"source", "fetched_at"})
    entry_summary = _entry_missing_summary(ledger)
    blockers: list[str] = []
    if price_schema["missing"]:
        blockers.append("daily_price_provenance_not_in_schema")
    if index_schema["missing"]:
        blockers.append("index_price_provenance_not_in_schema")
    if entry_summary["entries_with_missing_provenance"]:
        blockers.append("artifact_provenance_incomplete")
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": "m29_provenance_audit.v1",
        "milestone": "M29.3",
        "purpose": "read-only audit of price and artifact provenance readiness",
        "run_mode": "read_only_provenance_audit",
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "price_schema": price_schema,
        "index_price_schema": index_schema,
        "market_snapshot_schema": snapshot_schema,
        "artifact_provenance": entry_summary,
        "blockers": blockers,
        "recommended_next_actions": [
            "keep M29 alpha evidence non-promoting while provenance blockers remain",
            "record universe_hash and train_label_realized_end in every new forward-shadow artifact",
            "verify future price/index ingestion writes source, fetched_at, and adjustment",
            "do not backfill unknown provenance by guessing existing DB row sources",
        ],
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    artifact = report["artifact_provenance"]
    lines = [
        "# M29 Provenance Audit",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- run_mode: {report['run_mode']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- saves_model: {report['saves_model']}",
        "",
        "## Schema Gaps",
        "",
        "| table | present | missing | can_prove_required_provenance |",
        "|---|---|---|---:|",
    ]
    for key in ("price_schema", "index_price_schema", "market_snapshot_schema"):
        row = report[key]
        lines.append(
            "| {table} | {present} | {missing} | {can_prove} |".format(
                table=row["table"],
                present=", ".join(row["present"]) or "none",
                missing=", ".join(row["missing"]) or "none",
                can_prove=row["can_prove_required_provenance"],
            )
        )
    lines.extend([
        "",
        "## Artifact Provenance",
        "",
        f"- entries: {artifact['entries']}",
        f"- entries_with_missing_provenance: {artifact['entries_with_missing_provenance']}",
        "",
        "## Blockers",
        "",
    ])
    lines.extend(f"- {blocker}" for blocker in report["blockers"])
    lines.extend(["", "## Recommended Next Actions", ""])
    lines.extend(f"- {item}" for item in report["recommended_next_actions"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", type=Path, help="JSON artifact to audit; repeatable")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_audit(args.artifact)
    args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.expanduser().write_text(report_to_markdown(report), encoding="utf-8")
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
