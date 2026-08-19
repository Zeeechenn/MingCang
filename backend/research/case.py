"""[M39-M55 论点与门] [gate-guarded] 消费者: backend/api/routes/research.py, backend/research/dossier.py, backend/research/gate_b_recorder.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_DATA_STALE_DAYS = 14
_SIGNAL_STALE_DAYS = 7

_STAGE4_RESEARCH_GOVERNANCE = {
    "owner_domain": "backend.research",
    "unique_consumer": "ResearchCase/report_gate",
    "input_contract": "assembled dossier dict plus optional gate/serenity summaries",
    "output_contract": "stage4_research_structure.v1",
    "failure_mode": "missing thesis/scenario/falsification inputs are surfaced as gaps",
    "degradation": "read-only structure remains available with status=missing/needs_evidence",
    "baseline": "existing ResearchCase quality_gate + structural_validity_card",
    "success_metric": "100% of generated cases expose thesis, anti_thesis, scenarios, checklist and falsification slots",
    "minimum_sample": "first 20 ResearchCase/report-gate outputs before any promotion discussion",
    "expiry_or_exit": "expires when Stage4 report gate fields are superseded by a durable research ontology",
    "rollback": "ignore stage4_research_structure; existing ResearchCase fields are unchanged",
    "replacement": "durable research ontology after leader review",
    "lifecycle": "shadow",
    "signal_impact": "none",
}


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


def _non_empty_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _first_text(*values: Any) -> str | None:
    for value in values:
        if text := _non_empty_text(value):
            return text
        items = _string_list(value)
        if items:
            return items[0]
    return None


def _scenario(
    scenario_id: str,
    *,
    summary: str | None,
    evidence_refs: list[str] | None = None,
    status: str | None = None,
) -> dict:
    resolved_status = status or ("present" if summary else "missing")
    return {
        "scenario": scenario_id,
        "status": resolved_status,
        "summary": summary or "待补充：需要显式情景假设与证据引用",
        "evidence_refs": evidence_refs or [],
        "signal_impact": "none",
        "scoring_policy": "not_scored",
    }


def _extract_forward_thesis(dossier: dict) -> dict:
    forward = dossier.get("forward_thesis") or {}
    research_state = dossier.get("research_state") or {}
    label = dossier.get("long_term_label") or {}
    return {
        "statement": _first_text(
            forward.get("thesis"),
            forward.get("statement"),
            research_state.get("thesis"),
            label.get("key_findings"),
        ),
        "anti_points": _string_list(forward.get("anti_thesis"))
        or _string_list(forward.get("risks"))
        or _string_list(research_state.get("risks")),
        "base": _first_text(forward.get("base_case"), forward.get("base_scenario")),
        "bull": _first_text(forward.get("bull_case"), forward.get("bull_scenario")),
        "bear": _first_text(forward.get("bear_case"), forward.get("bear_scenario")),
        "falsification": (
            _string_list(forward.get("falsification_conditions"))
            or _string_list(forward.get("invalidation_conditions"))
            or _string_list(research_state.get("open_questions"))
        ),
        "management": forward.get("management_checklist") or forward.get("management") or {},
        "moat": forward.get("moat_checklist") or forward.get("moat") or {},
    }


def build_stage4_research_structure(
    dossier: dict,
    *,
    report_gate: dict | None = None,
    serenity_layer: dict | None = None,
) -> dict:
    """Build Stage4 research structure as a pure, no-score, no-signal overlay.

    This does not query data, call LLMs, write memory, or mutate official signal
    fields.  Subjective management/moat items are surfaced as checklist evidence
    gaps only; they are deliberately not folded into numeric scoring.
    """

    forward = _extract_forward_thesis(dossier)
    serenity = serenity_layer or dossier.get("serenity_layer") or {}
    gate = report_gate or dossier.get("report_gate") or {}
    evidence_refs = [
        str(card.get("source_ref"))
        for card in build_dossier_evidence_cards(dossier)
        if card.get("source_ref")
    ][:8]

    anti_points = forward["anti_points"] or _string_list(serenity.get("bear_case"))
    falsification = forward["falsification"] or _string_list(serenity.get("falsification_questions"))
    gate_blockers = gate.get("reasons") if isinstance(gate, dict) else []
    if not falsification:
        falsification = _string_list(gate_blockers)

    checklist_inputs = {
        "management_quality": forward["management"],
        "moat_durability": forward["moat"],
        "customer_or_supply_chain_concentration": dossier.get("supply_chain") or {},
        "accounting_or_governance_red_flags": dossier.get("governance_red_flags") or [],
    }
    checklist = []
    for item_id, raw in checklist_inputs.items():
        present = bool(raw)
        checklist.append({
            "item": item_id,
            "status": "present" if present else "needs_evidence",
            "evidence": raw if present else None,
            "scoring_policy": "not_scored",
            "signal_impact": "none",
        })

    scenarios = [
        _scenario("base", summary=forward["base"] or forward["statement"], evidence_refs=evidence_refs),
        _scenario("bull", summary=forward["bull"], evidence_refs=evidence_refs),
        _scenario(
            "bear",
            summary=forward["bear"] or (anti_points[0] if anti_points else None),
            evidence_refs=evidence_refs,
        ),
    ]
    gaps: list[str] = []
    if not forward["statement"]:
        gaps.append("missing_thesis")
    if not anti_points:
        gaps.append("missing_anti_thesis")
    for scenario in scenarios:
        if scenario["status"] == "missing":
            gaps.append(f"missing_{scenario['scenario']}_scenario")
    if not falsification:
        gaps.append("missing_falsification_conditions")

    return {
        "schema_version": "stage4_research_structure.v1",
        "symbol": dossier.get("symbol", ""),
        "status": "ready" if not gaps else "needs_evidence",
        "signal_impact": "none",
        "thesis": {
            "status": "present" if forward["statement"] else "missing",
            "statement": forward["statement"] or "",
            "evidence_refs": evidence_refs,
            "signal_impact": "none",
        },
        "anti_thesis": {
            "status": "present" if anti_points else "missing",
            "points": anti_points,
            "signal_impact": "none",
        },
        "scenarios": scenarios,
        "management_moat_checklist": checklist,
        "falsification_conditions": [
            {"condition": condition, "status": "active", "signal_impact": "none"}
            for condition in falsification
        ],
        "gaps": sorted(set(gaps)),
        "governance": dict(_STAGE4_RESEARCH_GOVERNANCE),
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
    stage4_structure = build_stage4_research_structure(dossier)
    symbol = dossier.get("symbol", "")
    return {
        "symbol": symbol,
        "as_of": as_of,
        "quality_gate": quality_gate,
        "validity_card": validity_card,
        "stage4_research_structure": stage4_structure,
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
