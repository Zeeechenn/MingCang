"""Dry-run-first importer for M45 track-analyst-class thesis records.

The importer writes only shadow research state when explicitly executed:

- one ForwardThesis row per imported external judgment;
- one L0 pending memory atom per imported judgment.

It does not touch official signals, test2 state, scheduler jobs, positions,
production weights, M29 artifacts, or trusted memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.research.research_evidence_defs import SourceTier

FORBIDDEN_TRADING_FIELDS = {
    "buy_score",
    "composite_score",
    "direction",
    "entry_signal",
    "position_size",
    "price_target",
    "recommendation",
    "signal_score",
    "stop_loss",
    "take_profit",
}

SAFETY_FLAGS = {
    "production_unchanged": True,
    "calls_llm_or_api": False,
    "touches_official_signal": False,
    "touches_test2": False,
    "touches_scheduler": False,
    "writes_trusted_memory": False,
}

CALLER_MUTABLE_MEMORY_STATES = {"raw", "pending", "legacy_import_pending"}
SOURCE_KINDS = {"direct_source", "handoff_context", "derived_summary"}
SOURCE_TIER_VALUES = {tier.value for tier in SourceTier}
SOURCE_TIER_ALIASES = {"social": SourceTier.social_lead.value}


@dataclass(frozen=True)
class TrackThesisInput:
    statement: str
    source: str
    as_of: str
    invalidation_conditions: list[str]
    symbol: str | None = None
    theme: str | None = None
    horizon_date: str | None = None
    follow_up_metrics: list[str] | None = None
    review_cadence_days: int | None = None
    next_review_date: str | None = None
    source_ref: str | None = None
    source_url: str | None = None
    source_note: str | None = None
    source_kind: str = "handoff_context"
    source_tier: str | None = None
    evidence_level: str | None = None
    source_verified: bool = False
    source_verified_by: str | None = None
    source_verified_at: str | None = None
    confidence_low: float | None = None
    confidence_high: float | None = None

    @property
    def scope_type(self) -> str:
        return "stock" if self.symbol else "theme"

    @property
    def scope_key(self) -> str:
        return self.symbol or self.theme or ""


def _as_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _required_str(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_str(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    return value or None


def _optional_int(raw: dict[str, Any], field: str) -> int | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _optional_float(raw: dict[str, Any], field: str) -> float | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"{field} must be a number")
    return float(value)


def _optional_bool(raw: dict[str, Any], field: str) -> bool:
    value = raw.get(field)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _optional_source_tier(raw: dict[str, Any]) -> str | None:
    value = _optional_str(raw, "source_tier")
    if value is None:
        return None
    normalized = SOURCE_TIER_ALIASES.get(value.lower(), value.lower())
    if normalized not in SOURCE_TIER_VALUES:
        raise ValueError(f"source_tier must be one of {sorted(SOURCE_TIER_VALUES)}")
    return normalized


def _stable_source_ref(item: TrackThesisInput) -> str:
    if item.source_ref:
        return item.source_ref
    digest_input = "|".join([
        item.source,
        item.as_of,
        item.scope_type,
        item.scope_key,
        item.statement,
        item.horizon_date or "",
    ])
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
    return f"m45:track:{digest}"


def normalize_item(raw: dict[str, Any]) -> TrackThesisInput:
    if not isinstance(raw, dict):
        raise ValueError("each thesis item must be an object")
    forbidden = sorted(FORBIDDEN_TRADING_FIELDS.intersection(raw))
    if forbidden:
        raise ValueError(
            "M45 import records external theses only; forbidden trading fields: "
            + ", ".join(forbidden)
        )

    symbol = _optional_str(raw, "symbol")
    theme = _optional_str(raw, "theme")
    if not symbol and not theme:
        raise ValueError("each thesis item requires symbol or theme")

    invalidation_conditions = _as_list(
        raw.get("invalidation_conditions"),
        field="invalidation_conditions",
    )
    if not invalidation_conditions:
        raise ValueError("invalidation_conditions must contain at least one item")

    normalized = TrackThesisInput(
        statement=_required_str(raw, "statement"),
        source=_required_str(raw, "source"),
        as_of=_required_str(raw, "as_of"),
        invalidation_conditions=invalidation_conditions,
        symbol=symbol,
        theme=theme,
        horizon_date=_optional_str(raw, "horizon_date"),
        follow_up_metrics=_as_list(raw.get("follow_up_metrics"), field="follow_up_metrics"),
        review_cadence_days=_optional_int(raw, "review_cadence_days"),
        next_review_date=_optional_str(raw, "next_review_date"),
        source_ref=_optional_str(raw, "source_ref"),
        source_url=_optional_str(raw, "source_url"),
        source_note=_optional_str(raw, "source_note"),
        source_kind=_optional_str(raw, "source_kind") or "handoff_context",
        source_tier=_optional_source_tier(raw),
        evidence_level=_optional_str(raw, "evidence_level"),
        source_verified=_optional_bool(raw, "source_verified"),
        source_verified_by=_optional_str(raw, "source_verified_by"),
        source_verified_at=_optional_str(raw, "source_verified_at"),
        confidence_low=_optional_float(raw, "confidence_low"),
        confidence_high=_optional_float(raw, "confidence_high"),
    )
    if normalized.review_cadence_days is None:
        raise ValueError("review_cadence_days is required")
    if normalized.source_kind not in SOURCE_KINDS:
        raise ValueError(
            f"source_kind must be one of {sorted(SOURCE_KINDS)}"
        )
    return normalized


def load_items(path: Path) -> list[TrackThesisInput]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    raw_items: Any
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("theses")
    else:
        raw_items = None
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("input must be a non-empty list or object with items/theses")
    return [normalize_item(raw) for raw in raw_items]


def _evidence_manifest(item: TrackThesisInput, source_ref: str) -> list[dict[str, str | None]]:
    return [{
        "kind": "ledger_snapshot",
        "ref": source_ref,
        "as_of": item.as_of,
        "summary": f"{item.source}: {item.source_note or item.statement}",
        "source_tier": item.source_tier,
        "evidence_level": item.evidence_level,
    }]


def _forward_statement(item: TrackThesisInput) -> str:
    if item.symbol or not item.theme:
        return item.statement
    return f"[theme:{item.theme}] {item.statement}"


def _forward_thesis_args(item: TrackThesisInput, source_ref: str) -> dict[str, Any]:
    return {
        "statement": _forward_statement(item),
        "horizon_date": item.horizon_date,
        "confidence_low": item.confidence_low,
        "confidence_high": item.confidence_high,
        "invalidation_conditions": item.invalidation_conditions,
        "follow_up_metrics": item.follow_up_metrics or [],
        "evidence_manifest": _evidence_manifest(item, source_ref),
        "next_review_date": item.next_review_date,
        "review_cadence_days": item.review_cadence_days,
        "symbol": item.symbol,
        "status": "draft",
    }


def _memory_atom_args(item: TrackThesisInput, source_ref: str, thesis_id: int | None) -> dict[str, Any]:
    evidence = {
        "source": item.source,
        "source_ref": source_ref,
        "source_url": item.source_url,
        "source_note": item.source_note,
        "source_kind": item.source_kind,
        "source_tier": item.source_tier,
        "evidence_level": item.evidence_level,
        "source_verified": item.source_verified,
        "source_verified_by": item.source_verified_by,
        "source_verified_at": item.source_verified_at,
        "as_of": item.as_of,
        "statement": item.statement,
        "invalidation_conditions": item.invalidation_conditions,
        "follow_up_metrics": item.follow_up_metrics or [],
        "review_cadence_days": item.review_cadence_days,
        "next_review_date": item.next_review_date,
        "decision_owner": "human",
        "forward_thesis_id": thesis_id,
        "production_impact": "none",
    }
    return {
        "scope_type": item.scope_type,
        "scope_key": item.scope_key,
        "memory_type": "imported_human_thesis",
        "summary": item.statement,
        "source_type": "track_import",
        "source_ref": source_ref,
        "trust_state": "pending",
        "evidence": evidence,
        "importance": 4,
        "confidence": 0.5,
        "valid_from": item.as_of,
    }


def _memory_atom_by_source_ref(db, source_ref: str):
    from backend.memory import l0_memory

    l0_memory._ensure_schema(db)
    return db.execute(
        text("""
            SELECT scope_type, scope_key, memory_type, summary, source_type, trust_state
            FROM memory_atoms
            WHERE source_ref = :source_ref
            LIMIT 1
        """),
        {"source_ref": source_ref},
    ).first()


def _source_fidelity_blockers(item: TrackThesisInput) -> list[str]:
    blockers: list[str] = []
    if not item.source_verified:
        blockers.append("source_not_verified")
    if item.source_kind != "direct_source":
        blockers.append("source_kind_not_direct_source")
    if not item.source_tier:
        blockers.append("missing_source_tier")
    elif item.source_tier == SourceTier.social_lead.value:
        blockers.append("source_tier_social_only")
    if item.evidence_level == "needs_check":
        blockers.append("evidence_level_needs_check")
    if not item.source_verified_by:
        blockers.append("missing_source_verified_by")
    if not item.source_ref:
        blockers.append("missing_explicit_source_ref")
    if not item.source_url and not item.source_note:
        blockers.append("missing_source_locator")
    return blockers


def _assert_existing_atom_matches_item(existing, item: TrackThesisInput, source_ref: str) -> None:
    expected = {
        "source_type": "track_import",
        "scope_type": item.scope_type,
        "scope_key": item.scope_key,
        "memory_type": "imported_human_thesis",
        "summary": item.statement,
    }
    actual = {key: getattr(existing, key) for key in expected}
    mismatches = sorted(
        key for key, value in expected.items()
        if (actual[key] or "") != (value or "")
    )
    if mismatches:
        raise ValueError(
            f"source_ref {source_ref!r} already exists with different "
            f"M45 identity fields: {', '.join(mismatches)}"
        )


def _preflight_execute(db, items: list[TrackThesisInput]) -> None:
    if not settings.forward_thesis_enabled:
        raise ValueError("forward_thesis_enabled must be true before M45 import execute")
    for item in items:
        source_ref = _stable_source_ref(item)
        blockers = _source_fidelity_blockers(item)
        if blockers:
            raise ValueError(
                f"source_ref {source_ref!r} is not execute-ready: "
                + ", ".join(blockers)
            )
        existing_atom = _memory_atom_by_source_ref(db, source_ref)
        trust_state = str(existing_atom.trust_state) if existing_atom is not None else None
        if trust_state is not None and trust_state not in CALLER_MUTABLE_MEMORY_STATES:
            raise ValueError(
                f"source_ref {source_ref!r} already has protected L0 trust_state "
                f"{trust_state!r}; refusing partial import"
            )
        if existing_atom is not None:
            _assert_existing_atom_matches_item(existing_atom, item, source_ref)


def _ensure_manifest_contains_source(db, thesis: dict[str, Any], item: TrackThesisInput, source_ref: str) -> dict[str, Any]:
    manifest = list(thesis.get("evidence_manifest") or [])
    if any(entry.get("ref") == source_ref for entry in manifest if isinstance(entry, dict)):
        return thesis

    from backend.research.forward_thesis import attach_evidence_manifest

    merged = [*manifest, *_evidence_manifest(item, source_ref)]
    return attach_evidence_manifest(
        db,
        int(thesis["id"]),
        manifest=merged,
        as_of=item.as_of,
    )


def preview_import(items: list[TrackThesisInput]) -> dict[str, Any]:
    planned: list[dict[str, Any]] = []
    for item in items:
        source_ref = _stable_source_ref(item)
        execute_blockers = _source_fidelity_blockers(item)
        planned.append({
            "source_ref": source_ref,
            "scope": {"type": item.scope_type, "key": item.scope_key},
            "source_fidelity": {
                "source_kind": item.source_kind,
                "source_tier": item.source_tier,
                "evidence_level": item.evidence_level,
                "source_verified": item.source_verified,
                "source_verified_by": item.source_verified_by,
                "source_verified_at": item.source_verified_at,
                "execute_ready": not execute_blockers,
                "execute_blockers": execute_blockers,
            },
            "forward_thesis": _forward_thesis_args(item, source_ref),
            "l0_memory_atom": _memory_atom_args(item, source_ref, thesis_id=None),
        })
    return {
        "mode": "dry_run",
        "execute": False,
        "count": len(planned),
        "safety": {**SAFETY_FLAGS, "writes_db": False},
        "production_impact": "none",
        "writes": [],
        "planned": planned,
    }


def execute_import(db, items: list[TrackThesisInput], *, execute: bool = False) -> dict[str, Any]:
    if not execute:
        return preview_import(items)

    from backend.memory.l0_memory import create_memory_atom
    from backend.research.forward_thesis import create_forward_thesis

    _preflight_execute(db, items)
    writes: list[dict[str, Any]] = []
    for item in items:
        source_ref = _stable_source_ref(item)
        thesis = create_forward_thesis(db, **_forward_thesis_args(item, source_ref))
        thesis = _ensure_manifest_contains_source(db, thesis, item, source_ref)
        atom = create_memory_atom(
            db,
            **_memory_atom_args(
                item,
                source_ref,
                thesis_id=thesis.get("id") if thesis else None,
            ),
        )
        writes.append({
            "source_ref": source_ref,
            "forward_thesis_id": thesis.get("id") if thesis else None,
            "memory_atom_id": atom.get("id"),
            "memory_trust_state": atom.get("trust_state"),
            "scope": {"type": item.scope_type, "key": item.scope_key},
        })

    return {
        "mode": "execute",
        "execute": True,
        "count": len(writes),
        "safety": {**SAFETY_FLAGS, "writes_db": True},
        "production_impact": "none",
        "writes": writes,
    }


def _session_for_url(db_url: str):
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    return sessionmaker(bind=engine)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON file with items/theses")
    parser.add_argument("--db-url", default=settings.database_url)
    parser.add_argument("--execute", action="store_true", help="write ForwardThesis + L0 pending atoms")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    items = load_items(args.input)
    if args.execute:
        db = _session_for_url(args.db_url)
        try:
            result = execute_import(db, items, execute=True)
        finally:
            db.close()
    else:
        result = execute_import(None, items, execute=False)

    rendered = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.expanduser().write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
