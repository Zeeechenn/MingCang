"""M60 Watchtower Phase 0 — observation watchlist schema (file-based, zero LLM).

Schema decision (owner asked to evaluate reuse-vs-new-file before building):

    Reuse candidate was ``backend.research.forward_thesis`` (M39 ForwardThesis)
    plus ``backend.data.models.theme`` (M36 ThemeRecord / ThemeHypothesis).
    Rejected for direct reuse because:

    1. ``ForwardThesis`` is one row per *symbol* (``symbol: str | None``,
       ``statement: str``) — there is no ``symbols: list[str]`` field. A "创新药"
       watch-list entry with three tickers would need three duplicate rows
       sharing the same theme text, so any thesis edit becomes an N-row write
       instead of a single-file edit, and the "one theme = one entry" shape the
       spec asks for does not exist as a first-class row.
    2. ``ThemeHypothesis`` (M36) is closer in *shape* — it has
       ``theme_id``/``statement``/``invalidation_conditions_json`` and even a
       ``beneficiary_tiers_json`` field that can hold ``{symbol, tier,
       rationale}`` triples — but it has no distinct "validation_conditions"
       field (the spec's "验证条件" vs "失效条件" split), and it is a live M36
       table with its own status state machine, API routes, and
       ``forward_evidence_ref_json`` hook reserved for the M39 promotion gate.
       Bending it to a different M60 semantic (a flat symbol watch-list rather
       than a scored theme hypothesis) risks colliding with that pipeline's own
       invariants for a feature this module does not otherwise touch.
    3. M60 Phase 0 is explicitly a hand-edited, owner-iterated artifact ("看多
       论点...细节待 owner 补充") — a plain JSON file under version control is
       easier for the owner to edit directly than DB rows, and matches how
       other paper-trading universes already live as files
       (``paper_trading/test2_universe.json`` and friends).

    Net: this module defines a minimal, explicit JSON schema
    (``paper_trading/watchlists/*.json``) instead of adding columns to
    ``forward_theses``. No ORM/DB migration, no risk to M36/M39 invariants,
    and the schema matches the spec's field list exactly:
    ``theme_key / title / thesis / symbols[] / validation_conditions[] /
    invalidation_conditions[] / created_at / source_ref``.

This module is pure storage/schema plumbing: no LLM calls, no scoring, no
writes to Signal/DecisionRun/ForwardThesis/theme_hypotheses. Detection
(Phase 1) and LLM discretion (Phase 2) are separate modules that only *read*
what this module loads.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

WATCHLIST_DIR = Path("paper_trading/watchlists")

REQUIRED_FIELDS: tuple[str, ...] = (
    "theme_key",
    "title",
    "thesis",
    "symbols",
    "validation_conditions",
    "invalidation_conditions",
    "created_at",
    "source_ref",
)


def validate_watchlist_entry(entry: Any) -> list[str]:
    """Validate one watchlist entry against the M60 schema.

    Returns a list of human-readable error strings; an empty list means the
    entry is valid. Never raises — callers decide whether to skip or fail
    loudly on non-empty errors.
    """
    if not isinstance(entry, dict):
        return ["entry is not a JSON object"]

    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in entry:
            errors.append(f"missing field: {field}")
    if errors:
        # Remaining checks assume the fields exist; report the missing set first.
        return errors

    if not isinstance(entry["theme_key"], str) or not entry["theme_key"].strip():
        errors.append("theme_key must be a non-empty string")
    if not isinstance(entry["title"], str) or not entry["title"].strip():
        errors.append("title must be a non-empty string")
    if not isinstance(entry["thesis"], str) or not entry["thesis"].strip():
        errors.append("thesis must be a non-empty string")

    symbols = entry["symbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or not all(isinstance(item, str) and item.strip() for item in symbols)
    ):
        errors.append("symbols must be a non-empty list of non-empty strings")

    for cond_field in ("validation_conditions", "invalidation_conditions"):
        value = entry[cond_field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{cond_field} must be a list of strings")

    created_at = entry["created_at"]
    if not isinstance(created_at, str) or not created_at.strip():
        errors.append("created_at must be a non-empty ISO date string")
    else:
        try:
            date.fromisoformat(created_at[:10])
        except ValueError:
            errors.append("created_at must be an ISO date string (YYYY-MM-DD...)")

    if not isinstance(entry["source_ref"], str) or not entry["source_ref"].strip():
        errors.append("source_ref must be a non-empty string")

    return errors


def load_watchlists(directory: Path | str = WATCHLIST_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    """Load and validate every ``*.json`` watchlist file under ``directory``.

    Returns ``(valid_entries, errors)``. A file may contain either a single
    entry object or a JSON array of entries. Invalid JSON, schema violations,
    and duplicate ``theme_key`` values are never silently dropped — they are
    reported as prefixed error strings while the remaining valid entries still
    load, matching this codebase's degrade-explicitly convention (see
    ``backend.tools.m59_panel``'s ``missing:*`` flags).
    """
    dir_path = Path(directory)
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    if not dir_path.exists():
        return entries, [f"missing:directory:{dir_path}"]

    seen_theme_keys: dict[str, str] = {}
    for file_path in sorted(dir_path.glob("*.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{file_path.name}: invalid JSON ({exc.msg})")
            continue

        candidates = payload if isinstance(payload, list) else [payload]
        for entry in candidates:
            entry_errors = validate_watchlist_entry(entry)
            if entry_errors:
                errors.append(f"{file_path.name}: " + "; ".join(entry_errors))
                continue
            theme_key = entry["theme_key"]
            if theme_key in seen_theme_keys:
                errors.append(
                    f"{file_path.name}: duplicate theme_key {theme_key!r} "
                    f"(already loaded from {seen_theme_keys[theme_key]})"
                )
                continue
            seen_theme_keys[theme_key] = file_path.name
            entries.append(entry)

    return entries, errors


def symbols_by_theme(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map theme_key -> symbols[] for already-validated entries."""
    return {entry["theme_key"]: list(entry["symbols"]) for entry in entries}


def themes_by_symbol(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map symbol -> [theme_key, ...] for already-validated entries.

    A symbol may legitimately appear in more than one theme; callers should
    not assume a single theme per symbol.
    """
    mapping: dict[str, list[str]] = {}
    for entry in entries:
        for symbol in entry["symbols"]:
            mapping.setdefault(symbol, []).append(entry["theme_key"])
    return mapping


def all_watchlist_symbols(entries: list[dict[str, Any]]) -> list[str]:
    """Return the de-duplicated, order-preserving union of symbols across entries."""
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in entries:
        for symbol in entry["symbols"]:
            if symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
    return ordered
