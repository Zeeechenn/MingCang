from __future__ import annotations

from datetime import datetime
from typing import Any

_DATA_STALE_DAYS = 14
_SIGNAL_STALE_DAYS = 7


def _age_days(date_str: str | None, today: datetime | None = None) -> int | None:
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        ref = today or datetime.utcnow()
        return (ref - d).days
    except ValueError:
        return None


def _build_quality_gate(dossier: dict, as_of: str | None = None) -> dict:
    """
    QualityGate v0 — purely derived from the dossier dict, no new queries.

    Checks:
      signal_present      — latest_signal is not None
      label_present       — long_term_label is not None
      deep_research_present — deep_research list is non-empty
      copilot_present     — research_state.copilot is not None
      signal_fresh        — signal date <= _SIGNAL_STALE_DAYS old
      label_trusted       — long_term_label.quality == 'trusted'
      no_pending_questions — pending_questions is empty
      source_coverage_ok  — missing list is empty (all four evidence gaps filled)
    """
    signal = dossier.get("latest_signal") or {}
    label = dossier.get("long_term_label") or {}
    research_state = dossier.get("research_state") or {}
    missing = dossier.get("missing") or []
    pending_questions = dossier.get("pending_questions") or []

    signal_date = signal.get("date") if signal else None
    # Measure freshness relative to as_of when provided (point-in-time replay),
    # falling back to "now" only for live use (as_of is None). Without this, a
    # historical replay would measure every past signal against the wall clock.
    if as_of:
        try:
            _fresh_ref = datetime.strptime(as_of[:10], "%Y-%m-%d")
        except ValueError:
            _fresh_ref = None
    else:
        _fresh_ref = None
    signal_age = _age_days(signal_date, today=_fresh_ref)

    # cutoff/as_of check: if as_of supplied, verify signal date is not after it
    cutoff_ok: bool = True
    if as_of and signal_date:
        try:
            cutoff = datetime.strptime(as_of[:10], "%Y-%m-%d")
            sig_dt = datetime.strptime(signal_date[:10], "%Y-%m-%d")
            cutoff_ok = sig_dt <= cutoff
        except ValueError:
            cutoff_ok = False

    checks = {
        "signal_present": bool(signal),
        "label_present": bool(label),
        "deep_research_present": bool(dossier.get("deep_research")),
        "copilot_present": bool(research_state.get("copilot")),
        "signal_fresh": (signal_age is not None and signal_age <= _SIGNAL_STALE_DAYS)
                        if signal else False,
        "label_trusted": label.get("quality") == "trusted" if label else False,
        "no_pending_questions": not pending_questions,
        "source_coverage_ok": not missing,
        "cutoff_ok": cutoff_ok,
    }

    blockers = [k for k, v in checks.items() if not v]
    warnings = []
    if signal_age is not None and signal_age > _SIGNAL_STALE_DAYS:
        warnings.append({"code": "signal_stale",
                         "message": f"Signal is {signal_age} days old (threshold {_SIGNAL_STALE_DAYS})"})
    for gap in missing:
        warnings.append({"code": f"missing_{gap}",
                         "message": f"Evidence gap: {gap}"})
    if pending_questions:
        warnings.append({"code": "pending_questions",
                         "message": f"{len(pending_questions)} copilot question(s) unanswered"})

    return {
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "gate_pass": not blockers,
        "as_of": as_of,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _build_structural_validity_card(dossier: dict) -> dict:
    """
    StructuralValidityCard v0 — purely derived from dossier dict.

    Status fields:
      pit_ok              — evidence[0].as_of is populated (point-in-time tag present)
      universe_hash_present — evidence[0].input_snapshot contains 'universe_hash'
      provenance_fields_present — evidence[0].input_snapshot contains at least
                                  data_source, fetched_at, adjustment
      calibration_status  — long_term_label.quality tri-state ('trusted'/'degraded'/'failed'/'unknown')
      constraint_eligible — long_term_label.constraint_eligible bool
      cost_awareness      — dict with budget proxy info derived from evidence length
                            (actual CNY figures require DB; here we surface what's in the dossier)
      label_expires_at    — long_term_label.expires_at for freshness awareness
    """
    evidence = dossier.get("evidence") or []
    label = dossier.get("long_term_label") or {}
    official_action = dossier.get("official_action") or {}

    first_ev: dict[str, Any] = evidence[0] if evidence else {}
    input_snapshot: dict = first_ev.get("input_snapshot") or {}

    _PROVENANCE_MIN = {"data_source", "fetched_at", "adjustment"}
    provenance_present = _PROVENANCE_MIN.issubset(input_snapshot.keys())
    universe_hash_present = "universe_hash" in input_snapshot
    pit_ok = bool(first_ev.get("as_of"))

    calibration_status = label.get("quality", "unknown") if label else "unknown"
    constraint_eligible = label.get("constraint_eligible", False) if label else False

    # surface is_constrained from official_action as a cross-check
    is_constrained = official_action.get("is_constrained", False)

    status = {
        "pit_ok": pit_ok,
        "universe_hash_present": universe_hash_present,
        "provenance_fields_present": provenance_present,
        "calibration_status": calibration_status,
        "constraint_eligible": constraint_eligible,
        "is_constrained": is_constrained,
        "label_expires_at": label.get("expires_at") if label else None,
        "evidence_run_count": len(evidence),
    }

    missing_provenance = sorted(_PROVENANCE_MIN - set(input_snapshot.keys()))

    return {
        "status": status,
        "missing_provenance": missing_provenance,
        "card_pass": pit_ok and provenance_present,
        "generated_at": datetime.utcnow().isoformat(),
    }


def build_case(dossier: dict, as_of: str | None = None) -> dict:
    """
    Build a ResearchCase envelope from an already-assembled dossier dict.

    Pure function — no DB access, no LLM calls, no side effects.
    Returns a dict that matches ResearchCaseOut.
    """
    quality_gate = _build_quality_gate(dossier, as_of=as_of)
    validity_card = _build_structural_validity_card(dossier)
    symbol = dossier.get("symbol", "")
    return {
        "symbol": symbol,
        "as_of": as_of,
        "quality_gate": quality_gate,
        "validity_card": validity_card,
        "ready": quality_gate["gate_pass"] and validity_card["card_pass"],
        "generated_at": datetime.utcnow().isoformat(),
    }


def _case_as_of(dossier: dict, explicit_as_of: str | None = None) -> str | None:
    if explicit_as_of:
        return explicit_as_of
    signal = dossier.get("latest_signal") or {}
    if signal.get("date"):
        return signal["date"]
    evidence = dossier.get("evidence") or []
    if evidence and evidence[0].get("as_of"):
        return evidence[0]["as_of"]
    return None


def _compact_summary(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value:
        return "; ".join(str(item).strip() for item in value[:3] if str(item).strip()) or fallback
    return fallback


def build_dossier_evidence_cards(dossier: dict) -> list[dict]:
    """Map one legacy dossier into read-only L1 evidence cards.

    This adapter is intentionally pure: no DB access, no memory writes, no LLM
    calls, and no official signal mutation.
    """
    symbol = dossier.get("symbol", "")
    cards: list[dict[str, Any]] = []

    for idx, evidence in enumerate(dossier.get("evidence") or []):
        snapshot = evidence.get("input_snapshot") or {}
        cards.append({
            "kind": "decision_run_evidence",
            "source_layer": "L1",
            "source_type": evidence.get("run_type") or "decision_run",
            "source_ref": evidence.get("run_id") or f"{symbol}:decision_run:{idx}",
            "summary": _compact_summary(
                evidence.get("recommendation"),
                fallback="decision run evidence",
            ),
            "as_of": evidence.get("as_of"),
            "pit_ok": bool(evidence.get("as_of")),
            "provenance": {
                "data_source": snapshot.get("data_source"),
                "fetched_at": snapshot.get("fetched_at"),
                "adjustment": snapshot.get("adjustment"),
                "universe_hash": snapshot.get("universe_hash"),
            },
            "write_policy": "no_database_writes",
            "signal_impact": "none",
        })

    label = dossier.get("long_term_label") or {}
    if label:
        cards.append({
            "kind": "long_term_label",
            "source_layer": "L1",
            "source_type": "long_term_label",
            "source_ref": f"{symbol}:long_term_label:{label.get('date') or 'active'}",
            "summary": _compact_summary(label.get("key_findings"), fallback=label.get("label") or "long-term label"),
            "as_of": label.get("date"),
            "pit_ok": bool(label.get("date")),
            "provenance": {
                "quality": label.get("quality"),
                "constraint_eligible": label.get("constraint_eligible"),
                "expires_at": label.get("expires_at"),
            },
            "write_policy": "no_database_writes",
            "signal_impact": "none",
        })

    for idx, row in enumerate(dossier.get("deep_research") or []):
        evidence = row.get("evidence") or {}
        cards.append({
            "kind": "deep_research_pointer",
            "source_layer": "L1",
            "source_type": row.get("source_type") or "research_pointer",
            "source_ref": row.get("source_ref") or f"{symbol}:deep_research:{idx}",
            "summary": _compact_summary(row.get("summary"), fallback=evidence.get("topic") or "deep research pointer"),
            "as_of": row.get("created_at") or evidence.get("as_of"),
            "pit_ok": bool(row.get("created_at") or evidence.get("as_of")),
            "provenance": {
                "memory_type": row.get("memory_type"),
                "topic": evidence.get("topic"),
            },
            "write_policy": "no_database_writes",
            "signal_impact": "none",
        })

    return cards


def build_dossier_adapter_review(dossier: dict, as_of: str | None = None) -> dict:
    """Build the Phase 4 minimal read-only adapter review for one dossier.

    The output proves the dossier adapter can supply:
      L1 EvidenceCard-like rows,
      L2 ResearchCase,
      L0 memory-candidate preview.

    The preview is not a write. Existing gated routes remain the only way to
    create pending candidates or promote trusted memory.
    """
    resolved_as_of = _case_as_of(dossier, as_of)
    research_case = build_case(dossier, as_of=resolved_as_of)
    evidence_cards = build_dossier_evidence_cards(dossier)
    symbol = dossier.get("symbol", "")
    thesis = (dossier.get("research_state") or {}).get("thesis")
    candidate_summary = _compact_summary(
        thesis,
        fallback=f"{symbol} dossier adapter review: {len(evidence_cards)} read-only evidence card(s)",
    )
    source_ref_as_of = resolved_as_of or "live"
    candidate_preview = {
        "symbol": symbol,
        "summary": candidate_summary,
        "memory_type": "thesis",
        "importance": 3,
        "confidence": 0.5,
        "source_ref": f"atlas:dossier_readonly_v0:{symbol}:{source_ref_as_of}",
        "note": "Phase 4 read-only dossier adapter preview; create route must keep source_trust=pending.",
        "eligible_for_creation": bool(symbol and candidate_summary and evidence_cards),
        "source_trust_after_create": "pending",
    }
    return {
        "adapter": "dossier_readonly_v0",
        "symbol": symbol,
        "as_of": resolved_as_of,
        "read_only": True,
        "research_case": research_case,
        "evidence_cards": evidence_cards,
        "memory_candidate_preview": candidate_preview,
        "promotion_gate": {
            "candidate_create_route": "POST /api/research/memory-candidates",
            "trusted_promotion_route": "POST /api/research/memory-candidates/{candidate_id}/promote",
            "auto_promotes_trusted_memory": False,
            "trusted_requires": [
                "local_human_memory_gate",
                "agent_write_guard:research.memory.promote",
                "atlas_dormant_guard",
            ],
        },
    }
