"""Read-only M63 report and M59 discretion card routes."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.data.database import get_db
from backend.workflows.m63_daily import DEFAULT_QUEUE_PATH, OUTPUT_DIR, load_queue

router = APIRouter()

_MODE_RE = re.compile(r"^[a-z]+$")
_SAFE_FILENAME_RE = re.compile(
    r"^[a-z]+(?:_[A-Za-z0-9-]+)*_(?:\d{4}-\d{2}-\d{2}|\d{8})(?:_\d+)?\.md$"
)


def _normalize_date(raw: str) -> str:
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _parse_report_filename(filename: str) -> dict[str, str] | None:
    if "/" in filename or "\\" in filename or not _SAFE_FILENAME_RE.fullmatch(filename):
        return None
    stem = filename[:-3]
    parts = stem.split("_")
    if len(parts) < 2:
        return None
    mode = parts[0]
    as_of = _normalize_date(parts[-1])
    if not _MODE_RE.fullmatch(mode) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        return None
    return {"mode": mode, "as_of": as_of, "filename": filename}


def _report_entries() -> list[dict[str, str]]:
    if not OUTPUT_DIR.exists() or not OUTPUT_DIR.is_dir():
        return []
    entries: list[dict[str, str]] = []
    for path in OUTPUT_DIR.iterdir():
        if not path.is_file() or path.suffix != ".md":
            continue
        parsed = _parse_report_filename(path.name)
        if parsed:
            entries.append(parsed)
    return sorted(entries, key=lambda item: (item["as_of"], item["filename"]), reverse=True)


def _safe_report_path(filename: str) -> Path:
    parsed = _parse_report_filename(filename)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid report filename")
    path = OUTPUT_DIR / filename
    try:
        path.relative_to(OUTPUT_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid report filename") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    return path


@router.get("/m63/reports")
def list_m63_reports(mode: str | None = Query(default=None)) -> list[dict[str, str]]:
    """List local M63 markdown reports."""
    if mode is not None and (not _MODE_RE.fullmatch(mode) or "/" in mode or "\\" in mode):
        raise HTTPException(status_code=400, detail="invalid report mode")
    entries = _report_entries()
    if mode:
        entries = [item for item in entries if item["mode"] == mode]
    return entries


@router.get("/m63/reports/{mode}/latest")
def latest_m63_report(mode: str) -> dict[str, str]:
    """Return the newest report for a mode."""
    if not _MODE_RE.fullmatch(mode):
        raise HTTPException(status_code=400, detail="invalid report mode")
    match = next((item for item in _report_entries() if item["mode"] == mode), None)
    if match is None:
        raise HTTPException(status_code=404, detail="report not found")
    text_body = _safe_report_path(match["filename"]).read_text(encoding="utf-8")
    return {"mode": match["mode"], "as_of": match["as_of"], "text": text_body}


@router.get("/m63/reports/file/{filename}")
def get_m63_report_file(filename: str) -> dict[str, str]:
    """Return one whitelisted local M63 report file."""
    path = _safe_report_path(filename)
    parsed = _parse_report_filename(filename)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid report filename")
    return {"mode": parsed["mode"], "as_of": parsed["as_of"], "text": path.read_text(encoding="utf-8")}


def _sort_key(item: dict[str, Any]) -> str:
    return str(item.get("done_at") or item.get("updated_at") or item.get("created_at") or "")


@router.get("/m63/queue")
def get_m63_queue() -> dict[str, list[dict[str, Any]]]:
    """Return pending research queue entries and the latest completed entries."""
    queue = load_queue(DEFAULT_QUEUE_PATH)
    pending = [item for item in queue if item.get("status", "pending") == "pending"]
    done = [item for item in queue if item.get("status") == "done"]
    done = sorted(done, key=_sort_key, reverse=True)[:10]
    return {"pending": pending, "done": done}


@router.get("/m59/discretion/latest")
def latest_m59_discretion_cards(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return latest observe-only M59 discretion cards, if the table exists."""
    try:
        latest = db.execute(text("SELECT MAX(as_of) FROM m59_discretion_cards")).scalar()
    except SQLAlchemyError:
        return []
    if not latest:
        return []
    try:
        rows = db.execute(
            text(
                """
                SELECT as_of, symbol, slot, card_json, provider, created_at
                FROM m59_discretion_cards
                WHERE as_of = :as_of
                ORDER BY symbol ASC, slot ASC, id ASC
                """
            ),
            {"as_of": latest},
        ).mappings().all()
    except SQLAlchemyError:
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            card = json.loads(row["card_json"] or "{}")
        except json.JSONDecodeError:
            card = {}
        items.append(
            {
                "as_of": row["as_of"],
                "symbol": row["symbol"],
                "slot": row["slot"],
                "provider": row["provider"],
                "created_at": row["created_at"],
                "card": card,
            }
        )
    return items
