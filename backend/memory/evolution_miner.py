"""Rule-based M57 memory evolution miner.

This module is deliberately deterministic: it reads evolution_traces and only
creates pending memory candidates. It never calls an LLM and never touches
signals, positions, or schedulers.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from backend.memory.evolution_trace import ensure_schema as ensure_trace_schema

MINER_SOURCE_TYPE = "m57_evolution_miner"
DEFAULT_COOLDOWN_DAYS = 7
DEFAULT_MIN_SUPPORT = 2


@dataclass(frozen=True)
class MinedCandidate:
    kind: str
    summary: str
    route: str
    memory_type: str
    source_event_ids: tuple[int, ...]
    symbol: str | None = None
    theme: str | None = None
    profile_type: str | None = None
    profile_key: str | None = None

    @property
    def source_ref(self) -> str:
        digest = hashlib.sha256(
            "|".join([self.kind, self.summary, self.symbol or "", self.theme or ""]).encode("utf-8")
        ).hexdigest()[:16]
        return f"m57_miner:{self.kind}:{digest}"


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return []


def _loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _canonical_text(value: str) -> str:
    text_value = re.sub(r"\s+", " ", value.strip())
    return text_value[:180]


def _read_traces(
    db,
    *,
    lookback_days: int | None = None,
    trace_types: tuple[str, ...] | None = None,
    source_types: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    ensure_trace_schema(db)
    params: dict[str, Any] = {}
    where = "WHERE invalidated_at IS NULL"
    if lookback_days is not None:
        params["lookback"] = f"-{int(lookback_days)} days"
        where += " AND datetime(ingestion_time) >= datetime('now', :lookback)"
    rows = db.execute(text(f"""
        SELECT id, trace_type, namespace, subject, symbols_json, themes_json,
               content, payload_json, source_type, source_ref, event_time,
               ingestion_time
        FROM evolution_traces
        {where}
        ORDER BY id ASC
    """), params).mappings().all()  # noqa: S608 - WHERE fragment is fixed.
    parsed = [
        {
            **dict(row),
            "symbols": _loads_list(row["symbols_json"]),
            "themes": _loads_list(row["themes_json"]),
            "payload": _loads_dict(row["payload_json"]),
        }
        for row in rows
    ]
    if trace_types:
        allowed_trace_types = set(trace_types)
        parsed = [row for row in parsed if row["trace_type"] in allowed_trace_types]
    if source_types:
        allowed_source_types = set(source_types)
        parsed = [row for row in parsed if row["source_type"] in allowed_source_types]
    return parsed


def _groups_by_text(rows: list[dict[str, Any]], predicate) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        content = _canonical_text(row["content"] or "")
        if not content or not predicate(row, content):
            continue
        grouped.setdefault(content, []).append(row)
    return grouped


def _candidates_from_groups(
    grouped: dict[str, list[dict[str, Any]]],
    *,
    min_support: int,
    kind: str,
    route: str,
    memory_type: str,
    profile_type: str | None = None,
    profile_key: str | None = None,
) -> list[MinedCandidate]:
    candidates: list[MinedCandidate] = []
    for summary, rows in grouped.items():
        ids = tuple(int(row["id"]) for row in rows)
        if len(set(ids)) < min_support:
            continue
        symbol = next((row["symbols"][0] for row in rows if row["symbols"]), None)
        theme = next((row["themes"][0] for row in rows if row["themes"]), None)
        candidates.append(MinedCandidate(
            kind=kind,
            summary=summary,
            route=route,
            memory_type=memory_type,
            source_event_ids=tuple(sorted(set(ids))),
            symbol=symbol,
            theme=theme,
            profile_type=profile_type,
            profile_key=profile_key,
        ))
    return candidates


def _mine_preferences(rows: list[dict[str, Any]], *, min_support: int) -> list[MinedCandidate]:
    pattern = re.compile(r"偏好|希望|更喜欢|习惯|请.*(保持|使用)")
    return _candidates_from_groups(
        _groups_by_text(rows, lambda _row, content: bool(pattern.search(content))),
        min_support=min_support,
        kind="repeated_explicit_preference",
        route="profile",
        memory_type="user_preference",
        profile_type="user_preference",
        profile_key="global",
    )


def _mine_rejections(rows: list[dict[str, Any]], *, min_support: int) -> list[MinedCandidate]:
    pattern = re.compile(r"不要|别|拒绝|不想|不需要")
    return _candidates_from_groups(
        _groups_by_text(rows, lambda _row, content: bool(pattern.search(content))),
        min_support=min_support,
        kind="repeated_rejection",
        route="profile",
        memory_type="lesson",
        profile_type="user_preference",
        profile_key="global",
    )


def _mine_risks(rows: list[dict[str, Any]], *, min_support: int) -> list[MinedCandidate]:
    pattern = re.compile(r"风险|止损|仓位|追高|回撤|亏损|暴露")
    return _candidates_from_groups(
        _groups_by_text(rows, lambda _row, content: bool(pattern.search(content))),
        min_support=min_support,
        kind="repeated_risk_phrase",
        route="atom",
        memory_type="risk",
    )


def _mine_references(rows: list[dict[str, Any]], *, min_support: int) -> list[MinedCandidate]:
    grouped: dict[tuple[str | None, str | None], list[dict[str, Any]]] = {}
    for row in rows:
        for symbol in row["symbols"]:
            grouped.setdefault((symbol, None), []).append(row)
        for theme in row["themes"]:
            grouped.setdefault((None, theme), []).append(row)
    candidates: list[MinedCandidate] = []
    for (symbol, theme), group in grouped.items():
        ids = tuple(sorted({int(row["id"]) for row in group}))
        if len(ids) < min_support:
            continue
        label = symbol or theme
        summary = f"重复提及 {label}: " + " / ".join(
            _canonical_text(row["content"] or "")[:60] for row in group[:3]
        )
        candidates.append(MinedCandidate(
            kind="repeated_stock_theme_reference",
            summary=summary,
            route="scenario",
            memory_type="research_pointer",
            source_event_ids=ids,
            symbol=symbol,
            theme=theme,
        ))
    return candidates


def _mine_confirmed_actions(rows: list[dict[str, Any]], *, min_support: int) -> list[MinedCandidate]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        trace_type = str(row["trace_type"] or "")
        payload = row["payload"]
        action = str(payload.get("action") or payload.get("action_name") or "")
        if "confirm" not in trace_type and "confirmed" not in trace_type and not action:
            continue
        key = action or _canonical_text(row["content"] or "")
        if key:
            grouped.setdefault(key, []).append(row)
    candidates: list[MinedCandidate] = []
    for action, group in grouped.items():
        ids = tuple(sorted({int(row["id"]) for row in group}))
        if len(ids) < min_support:
            continue
        candidates.append(MinedCandidate(
            kind="confirmed_action_pattern",
            summary=f"重复确认操作模式: {action}",
            route="atom",
            memory_type="lesson",
            source_event_ids=ids,
            symbol=next((row["symbols"][0] for row in group if row["symbols"]), None),
        ))
    return candidates


def _source_ref_exists(db, source_ref: str, *, cooldown_days: int) -> bool:
    params = {"source_ref": source_ref, "cooldown": f"-{int(cooldown_days)} days"}
    row = db.execute(text("""
        SELECT 1
        FROM memory_promotion_candidates
        WHERE source_ref = :source_ref
          AND (
            source_trust = 'pending'
            OR datetime(created_at) >= datetime('now', :cooldown)
          )
        LIMIT 1
    """), params).first()
    if row is not None:
        return True
    for table, state_col in (
        ("memory_atoms", "trust_state"),
        ("memory_profiles", "trust_state"),
        ("memory_scenarios", "trust_state"),
    ):
        row = db.execute(text(f"""
            SELECT 1
            FROM {table}
            WHERE source_ref = :source_ref
              AND (
                {state_col} = 'pending'
                OR datetime(created_at) >= datetime('now', :cooldown)
              )
            LIMIT 1
        """), params).first()  # noqa: S608 - table names are fixed allowlist.
        if row is not None:
            return True
    return False


def _evidence(candidate: MinedCandidate) -> dict[str, Any]:
    return {
        "miner": "m57_profile_miner",
        "candidate_kind": candidate.kind,
        "source_event_ids": list(candidate.source_event_ids),
        "symbol": candidate.symbol,
        "theme": candidate.theme,
        "route": candidate.route,
    }


def _insert_profile(db, candidate: MinedCandidate) -> int:
    from backend.memory.l0_memory import _ensure_schema as ensure_l0_schema

    ensure_l0_schema(db)
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    result = db.execute(text("""
        INSERT INTO memory_profiles(
            profile_type, profile_key, summary, atom_ids_json, trust_state,
            source_type, source_ref, created_at, updated_at
        )
        VALUES(
            :profile_type, :profile_key, :summary, :evidence_json, 'pending',
            :source_type, :source_ref, :now, :now
        )
    """), {
        "profile_type": candidate.profile_type or "user_preference",
        "profile_key": candidate.profile_key or "global",
        "summary": candidate.summary,
        "evidence_json": json.dumps(_evidence(candidate), ensure_ascii=False, sort_keys=True),
        "source_type": MINER_SOURCE_TYPE,
        "source_ref": candidate.source_ref,
        "now": now,
    })
    db.commit()
    return int(result.lastrowid)


def _insert_scenario(db, candidate: MinedCandidate) -> int:
    from backend.memory.l0_memory import _ensure_schema as ensure_l0_schema

    ensure_l0_schema(db)
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    scope_type = "stock" if candidate.symbol else "theme"
    scope_key = candidate.symbol or candidate.theme
    result = db.execute(text("""
        INSERT INTO memory_scenarios(
            scope_type, scope_key, title, summary, atom_ids_json, trust_state,
            source_type, source_ref, created_at, updated_at
        )
        VALUES(
            :scope_type, :scope_key, :title, :summary, :evidence_json, 'pending',
            :source_type, :source_ref, :now, :now
        )
    """), {
        "scope_type": scope_type,
        "scope_key": scope_key,
        "title": f"M57 候选: {scope_key}",
        "summary": candidate.summary,
        "evidence_json": json.dumps(_evidence(candidate), ensure_ascii=False, sort_keys=True),
        "source_type": MINER_SOURCE_TYPE,
        "source_ref": candidate.source_ref,
        "now": now,
    })
    db.commit()
    return int(result.lastrowid)


def _write_candidate(db, candidate: MinedCandidate) -> dict[str, Any]:
    from backend.memory.l0_memory import create_memory_atom
    from backend.research.review_loop import create_memory_candidate

    if candidate.route == "atom":
        target = create_memory_atom(
            db,
            scope_type="stock" if candidate.symbol else "global",
            scope_key=candidate.symbol,
            memory_type=candidate.memory_type,
            summary=candidate.summary,
            source_type=MINER_SOURCE_TYPE,
            source_ref=candidate.source_ref,
            trust_state="pending",
            evidence=_evidence(candidate),
        )
        target_ref = f"memory_atoms:{target['id']}"
    elif candidate.route == "profile":
        target_ref = f"memory_profiles:{_insert_profile(db, candidate)}"
    else:
        target_ref = f"memory_scenarios:{_insert_scenario(db, candidate)}"

    promotion = create_memory_candidate(
        db,
        symbol=candidate.symbol or "__GLOBAL__",
        summary=candidate.summary,
        memory_type=candidate.memory_type,
        source_ref=candidate.source_ref,
        note=f"{candidate.kind}; target={target_ref}",
    )
    return {"target": target_ref, "promotion_candidate_id": promotion["id"]}


def mine_candidates(
    db,
    *,
    min_support: int = DEFAULT_MIN_SUPPORT,
    lookback_days: int | None = None,
    trace_types: tuple[str, ...] | None = None,
    source_types: tuple[str, ...] | None = None,
) -> list[MinedCandidate]:
    rows = _read_traces(
        db,
        lookback_days=lookback_days,
        trace_types=trace_types,
        source_types=source_types,
    )
    candidates: list[MinedCandidate] = []
    candidates.extend(_mine_preferences(rows, min_support=min_support))
    candidates.extend(_mine_rejections(rows, min_support=min_support))
    candidates.extend(_mine_risks(rows, min_support=min_support))
    candidates.extend(_mine_references(rows, min_support=min_support))
    candidates.extend(_mine_confirmed_actions(rows, min_support=min_support))
    deduped: dict[str, MinedCandidate] = {}
    for candidate in candidates:
        if candidate.source_event_ids:
            deduped.setdefault(candidate.source_ref, candidate)
    return list(deduped.values())


def run_miner(
    db,
    *,
    min_support: int = DEFAULT_MIN_SUPPORT,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    lookback_days: int | None = None,
    trace_types: tuple[str, ...] | None = None,
    source_types: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    skipped = 0
    for candidate in mine_candidates(
        db,
        min_support=min_support,
        lookback_days=lookback_days,
        trace_types=trace_types,
        source_types=source_types,
    ):
        if _source_ref_exists(db, candidate.source_ref, cooldown_days=cooldown_days):
            skipped += 1
            continue
        created.append(_write_candidate(db, candidate))
    return {
        "created": len(created),
        "skipped": skipped,
        "items": created,
        "trace_types": list(trace_types or ()),
        "source_types": list(source_types or ()),
    }
