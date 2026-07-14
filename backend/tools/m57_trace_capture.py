"""Capture bounded, deduplicated M57 traces from completed deep-research runs.

The command is dry-run by default. ``--apply`` writes only ``evolution_traces``;
it never creates candidates or changes trust, signals, positions, or schedules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from sqlalchemy import bindparam, text

TRACE_TYPE = "research.deep_research.complete"
SOURCE_TYPE = "decision_run_report"


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_ref(report_path: str, as_of: str) -> str:
    digest = hashlib.sha256(f"{report_path}|{as_of}".encode()).hexdigest()[:20]
    return f"decision_run_report:{digest}"


def capture_decision_runs(
    db,
    decision_run_ids: list[int],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Build or persist one trace per unique ``(report_path, as_of)``."""
    if not decision_run_ids:
        raise ValueError("at least one --decision-run-id is required")
    rows = db.execute(text("""
        SELECT id, run_type, symbol, as_of, notes, input_snapshot_json
        FROM decision_runs
        WHERE id IN :ids
        ORDER BY id ASC
    """).bindparams(bindparam("ids", expanding=True)), {"ids": decision_run_ids}).mappings().all()
    found_ids = {int(row["id"]) for row in rows}
    missing_ids = sorted(set(decision_run_ids) - found_ids)
    if missing_ids:
        raise ValueError(f"decision_runs not found: {missing_ids}")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw_row in rows:
        row = dict(raw_row)
        if row["run_type"] != "deep_research":
            raise ValueError(f"decision_run {row['id']} is not deep_research")
        snapshot = _json_dict(row.get("input_snapshot_json"))
        report_path = str(snapshot.get("report_path") or "").strip()
        as_of = str(row.get("as_of") or "").strip()
        if not report_path or not as_of:
            raise ValueError(f"decision_run {row['id']} lacks report_path/as_of")
        row["snapshot"] = snapshot
        grouped.setdefault((report_path, as_of), []).append(row)

    from backend.memory.evolution_trace import NAMESPACE_RESEARCH_THESIS, record_trace

    items: list[dict[str, Any]] = []
    created = 0
    for (report_path, as_of), group in grouped.items():
        source_ref = _source_ref(report_path, as_of)
        existing = db.execute(text("""
            SELECT id FROM evolution_traces
            WHERE trace_type = :trace_type AND source_ref = :source_ref
            LIMIT 1
        """), {"trace_type": TRACE_TYPE, "source_ref": source_ref}).scalar()
        first = group[0]
        snapshot = first["snapshot"]
        symbols = sorted({
            str(symbol)
            for row in group
            for symbol in (row["snapshot"].get("symbols") or [row.get("symbol")])
            if symbol
        })
        sections = snapshot.get("sections") if isinstance(snapshot.get("sections"), list) else []
        payload = {
            "decision_run_ids": [int(row["id"]) for row in group],
            "report_path": report_path,
            "gate_status": snapshot.get("gate_status"),
            "source_count": snapshot.get("source_count"),
            "section_roles": [
                str(section.get("role"))
                for section in sections[:12]
                if isinstance(section, dict) and section.get("role")
            ],
        }
        preview: dict[str, Any] = {
            "source_ref": source_ref,
            "existing_trace_id": int(existing) if existing is not None else None,
            "as_of": as_of,
            "topic": str(snapshot.get("topic") or "深度研究")[:180],
            "symbols": symbols[:30],
            "payload": payload,
        }
        if apply and existing is None:
            trace = record_trace(
                db,
                trace_type=TRACE_TYPE,
                namespace=NAMESPACE_RESEARCH_THESIS,
                subject=preview["topic"],
                content=str(first.get("notes") or preview["topic"])[:500],
                symbols=preview["symbols"],
                themes=[preview["topic"]],
                payload=payload,
                source_type=SOURCE_TYPE,
                source_ref=source_ref,
                as_of=as_of,
            )
            preview["trace_id"] = trace["id"]
            created += 1
        items.append(preview)
    return {"apply": apply, "created": created, "unique_reports": len(items), "items": items}


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture real deep-research traces for M57")
    parser.add_argument("--decision-run-id", type=int, action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="write evolution_traces; default is dry-run")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        result = capture_decision_runs(db, args.decision_run_id, apply=args.apply)
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, default=str))


if __name__ == "__main__":
    main()
