"""Stage4 read-only Run Card builder.

The Run Card is a linking envelope: it does not persist anything and it does
not alter DecisionRun, EvidenceCard, PIT, trade journal, or ReviewCase rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

RUN_CARD_GOVERNANCE = {
    "owner_domain": "backend.evidence",
    "unique_consumer": "daily_panel/review_loop",
    "input_contract": "RunEnvelope/DecisionRun/EvidenceCard/PIT/trade_journal/ReviewCase refs",
    "output_contract": "run_card.v1",
    "failure_mode": "missing refs are emitted as missing_refs instead of inferred",
    "degradation": "card remains read-only with degraded status and explicit gaps",
    "baseline": "existing evidence refs displayed independently",
    "success_metric": "all daily-panel cards can trace to at least one run/evidence/PIT ref",
    "minimum_sample": "20 daily Run Cards before promotion",
    "expiry_or_exit": "expires when RunEnvelope becomes the canonical panel payload",
    "rollback": "drop Run Card payload; no stored state to migrate",
    "replacement": "RunEnvelope-native panel contract after Stage5 acceptance",
    "lifecycle": "shadow",
    "signal_impact": "none",
}


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _ref(kind: str, value: Any, *, fallback: str | None = None) -> dict | None:
    if value is None:
        return None
    ref_id = (
        _get(value, "run_id")
        or _get(value, "id")
        or _get(value, "source_ref")
        or _get(value, "evidence_ref")
        or fallback
    )
    return {
        "kind": kind,
        "ref": str(ref_id) if ref_id is not None else None,
        "as_of": _get(value, "as_of") or _get(value, "date"),
        "status": _get(value, "status"),
        "provenance": _get(value, "provenance", {}) or _get(value, "input_snapshot", {}) or {},
    }


def _ref_is_missing(ref: Any) -> bool:
    if not ref:
        return True
    if isinstance(ref, dict):
        return ref.get("ref") is None
    return False


def _missing_ref_names(refs: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for name, ref in refs.items():
        if isinstance(ref, list):
            if not ref:
                missing.append(name)
                continue
            missing.extend(f"{name}[{idx}]" for idx, item in enumerate(ref) if _ref_is_missing(item))
            continue
        if _ref_is_missing(ref):
            missing.append(name)
    return missing


def build_run_card(
    *,
    as_of: str,
    symbol: str | None = None,
    run_envelope: dict | None = None,
    decision_run: Any | None = None,
    evidence_cards: list[Any] | None = None,
    pit_audit: dict | None = None,
    trade_journal_ref: Any | None = None,
    review_case_ref: Any | None = None,
    owner: str = "backend.evidence",
    consumer: str = "daily_panel/review_loop",
) -> dict:
    """Build a read-only trace card from already available references."""

    cards = evidence_cards or []
    refs = {
        "run_envelope": _ref("run_envelope", run_envelope),
        "decision_run": _ref("decision_run", decision_run),
        "evidence_cards": [
            _ref("evidence_card", card, fallback=f"evidence_card:{idx}")
            for idx, card in enumerate(cards)
        ],
        "pit": _ref("point_in_time", pit_audit),
        "trade_journal": _ref("trade_journal", trade_journal_ref),
        "review_case": _ref("review_case", review_case_ref),
    }
    missing_refs = _missing_ref_names(refs)
    pit_clean = bool(_get(pit_audit or {}, "pit_ok", _get(pit_audit or {}, "clean", False)))
    status = "ready" if not missing_refs and pit_clean else "degraded"

    return {
        "schema_version": "run_card.v1",
        "symbol": symbol or _get(decision_run or {}, "symbol") or _get(run_envelope or {}, "symbol"),
        "as_of": as_of,
        "status": status,
        "read_only": True,
        "write_policy": "no_database_writes",
        "signal_impact": "none",
        "owner": owner,
        "consumer": consumer,
        "refs": refs,
        "missing_refs": missing_refs,
        "provenance": {
            "built_from": "in_memory_refs",
            "generated_at": _stamp(),
            "builder": "backend.evidence.run_card.build_run_card",
        },
        "degradation_flags": [] if status == "ready" else ["missing_or_unclean_refs"],
        "governance": {**RUN_CARD_GOVERNANCE, "owner_domain": owner, "unique_consumer": consumer},
    }
