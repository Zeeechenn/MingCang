"""Sync M60 watchlist thesis fields into ForwardThesis authority.

R1 keeps ``paper_trading/watchlists/*.json`` as a theme grouping view while
``forward_theses`` owns the thesis text and falsification/validation fields.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.memory.audit_log import audit_write
from backend.research.forward_thesis import create_forward_thesis
from backend.research.watchlist import WATCHLIST_DIR, _prefixed_statement, load_watchlists


def _json(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, default=str)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _find_theme_hypothesis_id(db: Any, entry: dict[str, Any], statement: str) -> int | None:
    from backend.data.database import ThemeHypothesis, ThemeRecord

    names = {str(entry.get("theme_key") or ""), str(entry.get("title") or "")}
    names.discard("")
    if not names:
        return None
    themes = db.query(ThemeRecord).filter(ThemeRecord.theme_name.in_(sorted(names))).all()
    if not themes:
        return None
    theme_ids = [theme.id for theme in themes]
    raw_statement = str(entry.get("thesis") or "")
    row = (
        db.query(ThemeHypothesis)
        .filter(
            ThemeHypothesis.theme_id.in_(theme_ids),
            ThemeHypothesis.statement.in_([statement, raw_statement]),
        )
        .order_by(ThemeHypothesis.updated_at.desc(), ThemeHypothesis.id.desc())
        .first()
    )
    return int(row.id) if row is not None else None


def _find_existing_forward_thesis(db: Any, statement: str):
    from backend.data.database import ForwardThesis

    return (
        db.query(ForwardThesis)
        .filter(
            ForwardThesis.symbol.is_(None),
            ForwardThesis.statement == statement,
            ForwardThesis.horizon_date.is_(None),
        )
        .first()
    )


def _sync_entry(db: Any, entry: dict[str, Any]) -> dict[str, Any]:
    statement = _prefixed_statement(str(entry["theme_key"]), str(entry["thesis"]))
    invalidation_conditions = list(entry.get("invalidation_conditions") or [])
    follow_up_metrics = list(entry.get("validation_conditions") or [])
    theme_hypothesis_id = _find_theme_hypothesis_id(db, entry, statement)
    existing = _find_existing_forward_thesis(db, statement)

    if existing is None:
        created = create_forward_thesis(
            db,
            symbol=None,
            statement=statement,
            status="active",
            invalidation_conditions=invalidation_conditions,
            follow_up_metrics=follow_up_metrics,
            theme_hypothesis_id=theme_hypothesis_id,
        )
        return {
            "theme_key": entry["theme_key"],
            "action": "created",
            "forward_thesis_id": created.get("id"),
            "theme_hypothesis_id": created.get("theme_hypothesis_id"),
        }

    before = {
        "status": existing.status,
        "invalidation_conditions_json": existing.invalidation_conditions_json,
        "follow_up_metrics_json": existing.follow_up_metrics_json,
        "theme_hypothesis_id": existing.theme_hypothesis_id,
    }
    existing.status = "active"
    existing.invalidation_conditions_json = _json(invalidation_conditions)
    existing.follow_up_metrics_json = _json(follow_up_metrics)
    if theme_hypothesis_id is not None:
        existing.theme_hypothesis_id = theme_hypothesis_id
    after = {
        "status": existing.status,
        "invalidation_conditions_json": existing.invalidation_conditions_json,
        "follow_up_metrics_json": existing.follow_up_metrics_json,
        "theme_hypothesis_id": existing.theme_hypothesis_id,
    }
    if before == after:
        return {
            "theme_key": entry["theme_key"],
            "action": "unchanged",
            "forward_thesis_id": existing.id,
            "theme_hypothesis_id": existing.theme_hypothesis_id,
        }

    existing.updated_at = _utc_now()
    db.flush()
    audit_write(db, "m60_thesis_sync.update", f"watchlist thesis synced: {entry['theme_key']}")
    db.commit()
    return {
        "theme_key": entry["theme_key"],
        "action": "updated",
        "forward_thesis_id": existing.id,
        "theme_hypothesis_id": existing.theme_hypothesis_id,
    }


def sync_watchlists_to_forward_thesis(
    *,
    db: Any,
    watchlist_dir: Path | str = WATCHLIST_DIR,
) -> dict[str, Any]:
    if not settings.forward_thesis_enabled:
        return {
            "enabled": False,
            "watchlist_dir": str(watchlist_dir),
            "watchlist_errors": [],
            "items": [],
            "summary": {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0},
            "message": "settings.forward_thesis_enabled is false; no sync performed",
        }

    entries, errors = load_watchlists(watchlist_dir, db=db, authoritative_thesis=False)
    items: list[dict[str, Any]] = []
    for entry in entries:
        items.append(_sync_entry(db, entry))
    summary = {
        "created": sum(1 for item in items if item["action"] == "created"),
        "updated": sum(1 for item in items if item["action"] == "updated"),
        "unchanged": sum(1 for item in items if item["action"] == "unchanged"),
        "skipped": len(errors),
    }
    return {
        "enabled": True,
        "watchlist_dir": str(watchlist_dir),
        "watchlist_errors": errors,
        "items": items,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync M60 watchlist theses into forward_theses")
    parser.add_argument("--watchlist-dir", type=Path, default=WATCHLIST_DIR)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = parser.parse_args(argv)

    from backend.data.database import SessionLocal

    db = SessionLocal()
    try:
        report = sync_watchlists_to_forward_thesis(db=db, watchlist_dir=args.watchlist_dir)
    finally:
        db.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        if not report["enabled"]:
            print(report["message"])
            return 2
        summary = report["summary"]
        print(
            "m60_thesis_sync: "
            f"created={summary['created']} updated={summary['updated']} "
            f"unchanged={summary['unchanged']} skipped={summary['skipped']}"
        )
        for item in report["items"]:
            print(
                f"- {item['theme_key']}: {item['action']} "
                f"forward_thesis_id={item.get('forward_thesis_id')}"
            )
        for error in report["watchlist_errors"]:
            print(f"watchlist_error: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
