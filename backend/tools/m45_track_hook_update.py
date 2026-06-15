"""Dry-run-first M45 adapter for track-analyst hook updates.

This tool turns structured track-analyst hook updates into the existing M45
ForwardThesis + L0 pending import path. It does not call the track-analyst analyst,
LLMs, scheduler jobs, official signals, positions, production profiles, or
trusted-memory promotion.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.tools.m45_import_track_theses import (
    TrackThesisInput,
    execute_import,
    normalize_item,
)


@dataclass(frozen=True)
class TrackHookUpdate:
    import_item: TrackThesisInput


def _required_str(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def normalize_hook_update(raw: dict[str, Any]) -> TrackHookUpdate:
    """Normalize a hook update into the canonical M45 import contract."""
    if not isinstance(raw, dict):
        raise ValueError("each hook update must be an object")
    hook_update = _required_str(raw, "hook_update")
    item = dict(raw)
    item["statement"] = hook_update
    item.pop("hook_update", None)
    item.pop("markdown_note", None)
    return TrackHookUpdate(import_item=normalize_item(item))


def load_hook_updates(path: Path) -> list[TrackHookUpdate]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    raw_items: Any
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("updates") or payload.get("hook_updates")
    else:
        raw_items = None
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("input must be a non-empty list or object with items/updates/hook_updates")
    return [normalize_hook_update(raw) for raw in raw_items]


def execute_hook_updates(db, updates: list[TrackHookUpdate], *, execute: bool = False) -> dict[str, Any]:
    items = [update.import_item for update in updates]
    return execute_import(db, items, execute=execute)


def _session_for_url(db_url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    return sessionmaker(bind=engine)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON file with structured hook updates")
    parser.add_argument("--db-url", default=settings.database_url)
    parser.add_argument("--execute", action="store_true", help="write ForwardThesis + L0 pending atoms")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    updates = load_hook_updates(args.input)
    if args.execute:
        db = _session_for_url(args.db_url)
        try:
            result = execute_hook_updates(db, updates, execute=True)
        finally:
            db.close()
    else:
        result = execute_hook_updates(None, updates, execute=False)

    rendered = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.expanduser().write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
