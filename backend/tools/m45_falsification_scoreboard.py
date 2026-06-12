"""Dry-run-first M45 falsification scoreboard recorder.

The scoreboard writes only review-loop state when explicitly executed:

- one ReviewCase row per symbol/as_of scoreboard event;
- optionally one pending MemoryPromotionCandidate row.

It does not touch official signals, decision runs, positions, production
weights, M29 artifacts, scheduler jobs, or trusted memory.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.research.research_evidence_defs import SourceTier

LANES = {
    "falsification",
    "invalidation_catch",
    "defensive_value",
    "breadth_hit",
}

LANE_RESULTS = {
    "falsification": {"hit", "miss", "caught_before_loss", "missed", "no_trigger", "not_due"},
    "invalidation_catch": {"hit", "miss", "caught_before_loss", "missed", "no_trigger", "not_due"},
    "defensive_value": {"helped", "hurt", "neutral", "not_due"},
    "breadth_hit": {"hit", "miss", "neutral", "not_due"},
}

LANE_REQUIRED_PAYLOAD_FIELDS = {
    "invalidation_catch": [
        "alarm_fired_at",
        "loss_materialized_at",
        "max_drawdown_pct",
    ],
    "defensive_value": [
        "system_on_drawdown_pct",
        "system_off_drawdown_pct",
        "sample_size",
    ],
    "breadth_hit": [
        "surfaced_by",
        "adopted_by_human",
        "outcome_observed_at",
    ],
}

SAFETY_FLAGS = {
    "production_unchanged": True,
    "calls_llm_or_api": False,
    "touches_official_signal": False,
    "touches_decision_run": False,
    "touches_position": False,
    "touches_m29_artifacts": False,
    "touches_test2": False,
    "touches_scheduler": False,
    "writes_trusted_memory": False,
    "writes_production_profile": False,
    "allowed_write_tables": ["review_cases", "memory_promotion_candidates"],
}

DEFAULT_JSON_OUTPUT = Path("/private/tmp/mingcang_m45_falsification_scoreboard.json")
DEFAULT_MARKDOWN_OUTPUT = Path("/private/tmp/mingcang_m45_falsification_scoreboard.md")
SOURCE_TIER_VALUES = {tier.value for tier in SourceTier}
SOURCE_TIER_ALIASES = {"social": SourceTier.social_lead.value}


@dataclass(frozen=True)
class ScoreboardCandidateSummary:
    summary: str
    memory_type: str
    importance: int = 3
    confidence: float = 0.5


@dataclass(frozen=True)
class ScoreboardItem:
    symbol: str
    as_of: str
    lane: str
    result: str
    source_ref: str
    evidence_summary: str
    thesis_ref: str | None = None
    evidence_ref: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    source_tier: str | None = None
    evidence_level: str | None = None
    source_verified: bool = False
    source_verified_by: str | None = None
    review_payload: dict[str, Any] | None = None
    candidate_summary: ScoreboardCandidateSummary | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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


def _candidate_summary(raw: Any) -> ScoreboardCandidateSummary | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("candidate_summary must be an object")
    summary = _required_str(raw, "summary")
    memory_type = _required_str(raw, "memory_type")
    importance = raw.get("importance", 3)
    confidence = raw.get("confidence", 0.5)
    if not isinstance(importance, int):
        raise ValueError("candidate_summary.importance must be an integer")
    if not isinstance(confidence, int | float):
        raise ValueError("candidate_summary.confidence must be a number")
    return ScoreboardCandidateSummary(
        summary=summary,
        memory_type=memory_type,
        importance=max(1, min(5, int(importance))),
        confidence=max(0.0, min(1.0, float(confidence))),
    )


def _ledger_required_fields(lane: str, result: str) -> list[str]:
    if result == "not_due":
        return []
    return LANE_REQUIRED_PAYLOAD_FIELDS.get(lane, [])


def _validate_lane_contract(*, lane: str, result: str, review_payload: dict[str, Any] | None) -> None:
    required = _ledger_required_fields(lane, result)
    if not required:
        return
    payload = review_payload or {}
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(
            "review_payload missing required fields for "
            f"{lane!r}: {', '.join(missing)}"
        )


def normalize_item(raw: dict[str, Any]) -> ScoreboardItem:
    if not isinstance(raw, dict):
        raise ValueError("each scoreboard item must be an object")

    lane = _required_str(raw, "lane")
    if lane not in LANES:
        raise ValueError(f"invalid lane: {lane!r}; must be one of {sorted(LANES)}")

    result = _required_str(raw, "result")
    if result not in LANE_RESULTS[lane]:
        raise ValueError(
            f"invalid result: {result!r}; must be one of {sorted(LANE_RESULTS[lane])} "
            f"for lane {lane!r}"
        )

    review_payload = raw.get("review_payload")
    if review_payload is not None and not isinstance(review_payload, dict):
        raise ValueError("review_payload must be an object")
    _validate_lane_contract(
        lane=lane,
        result=result,
        review_payload=review_payload,
    )
    candidate_summary = _candidate_summary(raw.get("candidate_summary"))
    if result == "not_due" and candidate_summary is not None:
        raise ValueError("not_due events cannot create memory candidates")

    return ScoreboardItem(
        symbol=_required_str(raw, "symbol"),
        as_of=_required_str(raw, "as_of"),
        lane=lane,
        result=result,
        source_ref=_required_str(raw, "source_ref"),
        evidence_summary=_required_str(raw, "evidence_summary"),
        thesis_ref=_optional_str(raw, "thesis_ref"),
        evidence_ref=_optional_str(raw, "evidence_ref"),
        source_url=_optional_str(raw, "source_url"),
        source_kind=_optional_str(raw, "source_kind"),
        source_tier=_optional_source_tier(raw),
        evidence_level=_optional_str(raw, "evidence_level"),
        source_verified=_optional_bool(raw, "source_verified"),
        source_verified_by=_optional_str(raw, "source_verified_by"),
        review_payload=review_payload,
        candidate_summary=candidate_summary,
    )


def load_items(path: Path) -> list[ScoreboardItem]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    raw_items: Any
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("events")
    else:
        raw_items = None
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("input must be a non-empty list or object with items/events")
    return [normalize_item(raw) for raw in raw_items]


def _scoreboard_payload(item: ScoreboardItem) -> dict[str, Any]:
    return {
        "source_ref": item.source_ref,
        "as_of": item.as_of,
        "thesis_ref": item.thesis_ref,
        "evidence_ref": item.evidence_ref,
        "source_url": item.source_url,
        "source_kind": item.source_kind,
        "source_tier": item.source_tier,
        "evidence_level": item.evidence_level,
        "source_verified": item.source_verified,
        "source_verified_by": item.source_verified_by,
        "lane": item.lane,
        "result": item.result,
        "evidence_summary": item.evidence_summary,
        "review_payload": item.review_payload or {},
        "ledger_contract": {
            "lane": item.lane,
            "required_fields": _ledger_required_fields(item.lane, item.result),
        },
    }


def _review_case_payload(item: ScoreboardItem) -> dict[str, Any]:
    scoreboard = _scoreboard_payload(item)
    return {
        "m45_scoreboard": scoreboard,
        "m45_scoreboard_events": [scoreboard],
        "correct": None,
        "recommendation": None,
        "attribution": [
            f"M45 {item.lane}: {item.result}",
            item.evidence_summary,
        ],
    }


def _scoreboard_key(item: ScoreboardItem) -> dict[str, str]:
    return {
        "source_ref": item.source_ref,
        "lane": item.lane,
        "as_of": item.as_of,
    }


def _loads_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _scoreboard_event_key(event: dict[str, Any]) -> tuple[Any, Any, Any]:
    return event.get("source_ref"), event.get("lane"), event.get("as_of")


def _merge_scoreboard_events(existing_payload: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    raw_events = existing_payload.get("m45_scoreboard_events")
    if isinstance(raw_events, list):
        events = [dict(row) for row in raw_events if isinstance(row, dict)]
    else:
        previous = existing_payload.get("m45_scoreboard")
        events = [dict(previous)] if isinstance(previous, dict) else []

    event_key = _scoreboard_event_key(event)
    for index, existing in enumerate(events):
        if _scoreboard_event_key(existing) == event_key:
            events[index] = event
            break
    else:
        events.append(event)
    return events


def _forward_lookup_refs(item: ScoreboardItem) -> set[str]:
    return {ref for ref in (item.thesis_ref, item.source_ref) if ref}


def _source_fidelity_blockers(item: ScoreboardItem) -> list[str]:
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
    if not item.source_url and not item.evidence_ref:
        blockers.append("missing_source_locator")
    return blockers


def _find_forward_thesis(db, item: ScoreboardItem) -> dict[str, Any] | None:
    if db is None:
        return None

    from backend.data.database import ForwardThesis

    refs = _forward_lookup_refs(item)
    for row in db.query(ForwardThesis).filter(ForwardThesis.symbol == item.symbol).all():
        manifest = _loads_json(row.evidence_manifest_json, [])
        if not isinstance(manifest, list):
            continue
        for entry in manifest:
            if isinstance(entry, dict) and entry.get("ref") in refs:
                return {
                    "id": int(row.id),
                    "symbol": row.symbol,
                    "statement": row.statement,
                    "status": row.status,
                    "lookup_path": "evidence_manifest",
                    "matched_source_ref": entry.get("ref"),
                }

    from backend.data.database import MemoryAtom

    atom = (
        db.query(MemoryAtom)
        .filter(MemoryAtom.source_ref.in_(refs))
        .order_by(MemoryAtom.id.asc())
        .first()
        if refs
        else None
    )
    if atom is None:
        return None

    evidence = _loads_json(atom.evidence_json, None)
    forward_thesis_id = evidence.get("forward_thesis_id") if isinstance(evidence, dict) else None
    if forward_thesis_id is not None:
        row = db.query(ForwardThesis).filter(ForwardThesis.id == int(forward_thesis_id)).first()
        if row is not None:
            return {
                "id": int(row.id),
                "symbol": row.symbol,
                "statement": row.statement,
                "status": row.status,
                "lookup_path": "l0_source_ref",
                "matched_source_ref": atom.source_ref,
                "l0_trust_state": atom.trust_state,
            }

    row = (
        db.query(ForwardThesis)
        .filter(ForwardThesis.symbol == item.symbol, ForwardThesis.statement == atom.summary)
        .first()
    )
    if row is not None:
        return {
            "id": int(row.id),
            "symbol": row.symbol,
            "statement": row.statement,
            "status": row.status,
            "lookup_path": "l0_source_ref",
            "matched_source_ref": atom.source_ref,
            "l0_trust_state": atom.trust_state,
        }
    return None


def _execute_blockers(item: ScoreboardItem, forward_thesis: dict[str, Any] | None) -> list[dict[str, Any]]:
    blockers = []
    if forward_thesis is None:
        blockers.append({
            "scoreboard_key": _scoreboard_key(item),
            "blocker": "forward_thesis_not_found",
            "lookup_refs": sorted(_forward_lookup_refs(item)),
        })
    for blocker in _source_fidelity_blockers(item):
        blockers.append({
            "scoreboard_key": _scoreboard_key(item),
            "blocker": blocker,
        })
    return blockers


def preview_scoreboard(items: list[ScoreboardItem], db=None) -> dict[str, Any]:
    planned = []
    blockers = []
    for item in items:
        forward_thesis = _find_forward_thesis(db, item)
        blockers.extend(_execute_blockers(item, forward_thesis))
        planned.append({
            "scoreboard_key": _scoreboard_key(item),
            "forward_thesis": forward_thesis,
            "review_case": {
                "symbol": item.symbol,
                "as_of": item.as_of,
                "review_payload": _review_case_payload(item),
            },
            "memory_candidate": (
                {
                    "summary": item.candidate_summary.summary,
                    "memory_type": item.candidate_summary.memory_type,
                    "source_ref": f"m45-scoreboard:{item.source_ref}:{item.lane}:{item.as_of}",
                    "source_trust": "pending",
                }
                if item.candidate_summary
                else None
            ),
        })
    return {
        "mode": "dry_run",
        "execute": False,
        "count": len(planned),
        "blocked_count": len(blockers),
        "safety": {**SAFETY_FLAGS, "writes_db": False},
        "production_impact": "none",
        "blockers": blockers,
        "writes": [],
        "planned": planned,
    }


def _upsert_review_case(db, item: ScoreboardItem) -> dict[str, Any]:
    from backend.data.database import ReviewCase
    from backend.memory.audit_log import audit_write
    from backend.research.review_loop import create_review_case

    forward_thesis = _find_forward_thesis(db, item)
    thesis_id = forward_thesis["id"] if forward_thesis else None
    payload = _review_case_payload(item)
    payload["m45_scoreboard"]["forward_thesis"] = forward_thesis
    existing = (
        db.query(ReviewCase)
        .filter(ReviewCase.symbol == item.symbol, ReviewCase.as_of == item.as_of)
        .first()
    )
    if existing is None:
        payload["m45_scoreboard_events"] = [payload["m45_scoreboard"]]
        return create_review_case(
            db,
            symbol=item.symbol,
            as_of=item.as_of,
            thesis_id=thesis_id,
            review_payload=payload,
        )

    existing_payload = _loads_json(existing.review_payload_json, {})
    if not isinstance(existing_payload, dict):
        existing_payload = {}
    payload["m45_scoreboard_events"] = _merge_scoreboard_events(
        existing_payload,
        payload["m45_scoreboard"],
    )
    existing.thesis_id = existing.thesis_id or thesis_id
    existing.review_payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    existing.attribution_json = json.dumps(payload["attribution"], ensure_ascii=False)
    existing.updated_at = _utc_now()
    db.flush()
    audit_write(
        db,
        "m45_scoreboard.review_case",
        (
            f"scoreboard updated symbol={item.symbol} as_of={item.as_of} "
            f"lane={item.lane} source_ref={item.source_ref}"
        ),
        related_symbol=item.symbol,
    )
    db.commit()
    return {
        "id": existing.id,
        "symbol": existing.symbol,
        "as_of": existing.as_of,
        "thesis_id": existing.thesis_id,
        "review_payload": payload,
    }


def execute_scoreboard(db, items: list[ScoreboardItem], *, execute: bool = False) -> dict[str, Any]:
    if not execute:
        return preview_scoreboard(items, db=db)

    from backend.research.review_loop import create_memory_candidate

    writes = []
    blockers = []
    for item in items:
        forward_thesis = _find_forward_thesis(db, item)
        blockers.extend(_execute_blockers(item, forward_thesis))
    if blockers:
        raise ValueError(
            "scoreboard execute blockers: "
            + ", ".join(str(blocker["blocker"]) for blocker in blockers)
        )

    for item in items:
        review = _upsert_review_case(db, item)
        candidate_id = None
        if item.candidate_summary is not None:
            source_ref = f"m45-scoreboard:{item.source_ref}:{item.lane}:{item.as_of}"
            candidate = create_memory_candidate(
                db,
                review_case_id=int(review["id"]),
                symbol=item.symbol,
                summary=item.candidate_summary.summary,
                memory_type=item.candidate_summary.memory_type,
                importance=item.candidate_summary.importance,
                confidence=item.candidate_summary.confidence,
                source_ref=source_ref,
                note=item.evidence_summary,
            )
            candidate_id = candidate["id"]
        writes.append({
            "scoreboard_key": _scoreboard_key(item),
            "review_case_id": review["id"],
            "memory_candidate_id": candidate_id,
            "memory_candidate_trust": "pending" if candidate_id is not None else None,
        })

    return {
        "mode": "execute",
        "execute": True,
        "count": len(writes),
        "blocked_count": len(blockers),
        "safety": {**SAFETY_FLAGS, "writes_db": True},
        "production_impact": "none",
        "blockers": blockers,
        "writes": writes,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# M45 Falsification Scoreboard",
        "",
        f"- mode: `{result['mode']}`",
        f"- count: `{result['count']}`",
        f"- production_impact: `{result['production_impact']}`",
        f"- writes_trusted_memory: `{result['safety']['writes_trusted_memory']}`",
        f"- touches_m29_artifacts: `{result['safety']['touches_m29_artifacts']}`",
        "",
    ]
    rows = result.get("writes") or result.get("planned") or []
    for row in rows:
        key = row.get("scoreboard_key", {})
        lines.append(
            f"- `{key.get('as_of')}` `{key.get('lane')}` "
            f"`{key.get('source_ref')}`"
        )
    blockers = result.get("blockers") or []
    if blockers:
        lines.extend(["", "## Lookup Blockers", ""])
        for blocker in blockers:
            key = blocker.get("scoreboard_key", {})
            lines.append(
                f"- `{key.get('source_ref')}` `{key.get('lane')}`: {blocker.get('blocker')}"
            )
    return "\n".join(lines) + "\n"


def write_artifacts(result: dict[str, Any], *, json_output: Path, markdown_output: Path) -> None:
    json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    json_output.expanduser().write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_output.expanduser().write_text(render_markdown(result), encoding="utf-8")


def write_default_artifacts(result: dict[str, Any], *, as_of: str | None = None) -> None:
    if as_of is None:
        write_artifacts(result, json_output=DEFAULT_JSON_OUTPUT, markdown_output=DEFAULT_MARKDOWN_OUTPUT)
        return
    stamp = as_of.replace("-", "")
    base = Path(f"/private/tmp/mingcang_m45_scoreboard_{stamp}")
    write_artifacts(result, json_output=base.with_suffix(".json"), markdown_output=base.with_suffix(".md"))


def _session_for_url(db_url: str):
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    return sessionmaker(bind=engine)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON file with items/events")
    parser.add_argument("--db-url", default=settings.database_url)
    parser.add_argument("--execute", action="store_true", help="write ReviewCase + optional pending candidate")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--no-artifacts", action="store_true", help="skip JSON/Markdown artifact writes")
    parser.add_argument("--write-default-artifacts", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    items = load_items(args.input)
    db = _session_for_url(args.db_url)
    try:
        result = execute_scoreboard(db, items, execute=args.execute)
    finally:
        db.close()

    if not args.no_artifacts:
        write_artifacts(result, json_output=args.json_output, markdown_output=args.markdown_output)

    rendered = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.expanduser().write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
