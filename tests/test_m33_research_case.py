"""M33 ResearchCase v0 — focused tests."""
from __future__ import annotations


def _minimal_dossier(symbol: str = "600519") -> dict:
    """A minimal dossier dict without any evidence — all fields missing."""
    return {
        "symbol": symbol,
        "stock": None,
        "latest_signal": None,
        "long_term_label": None,
        "research_state": {
            "symbol": symbol,
            "thesis": "",
            "risks": [],
            "open_questions": [],
            "copilot": None,
            "last_signal_summary": "",
            "last_review": None,
            "updated_at": None,
        },
        "evidence": [],
        "stock_memory": [],
        "deep_research": [],
        "pending_questions": [],
        "conflicts": [],
        "official_action": {"recommendation": None, "position_pct": None, "source": "none"},
        "missing": ["latest_signal", "long_term_label", "deep_research", "copilot"],
    }


def _full_dossier(symbol: str = "600519") -> dict:
    """A dossier dict with all key fields populated."""
    return {
        "symbol": symbol,
        "stock": {"symbol": symbol, "name": "贵州茅台", "market": "CN", "industry": "食品饮料", "active": True},
        "latest_signal": {
            "id": 1,
            "symbol": symbol,
            "date": "2026-06-01",
            "composite_score": 0.75,
            "recommendation": "买入",
            "confidence": "高",
            "stop_loss": 1600.0,
            "take_profit": 1900.0,
            "limit_status": None,
            "quant_score": None,
            "technical_score": 0.7,
            "sentiment_score": 0.6,
            "llm_arbitration": None,
        },
        "long_term_label": {
            "symbol": symbol,
            "date": "2026-05-01",
            "label": "值得持有",
            "score": 0.8,
            "votes": {},
            "key_findings": ["护城河深"],
            "expires_at": "2026-08-01",
            "quality": "trusted",
            "constraint_eligible": True,
            "quality_notes": [],
        },
        "research_state": {
            "symbol": symbol,
            "thesis": "白酒龙头",
            "risks": [],
            "open_questions": [],
            "copilot": {"validation_questions": []},
            "last_signal_summary": "",
            "last_review": None,
            "updated_at": "2026-06-01",
        },
        "evidence": [
            {
                "run_id": "r1",
                "run_type": "official",
                "symbol": symbol,
                "as_of": "2026-06-01",
                "input_snapshot": {
                    "data_source": "tushare",
                    "fetched_at": "2026-06-01T18:00:00",
                    "adjustment": "qfq",
                    "universe_hash": "abc123",
                },
                "agent_outputs": {},
                "trace": [],
                "risk_decision": {},
                "final_action": {},
                "recommendation": "买入",
                "composite_score": 0.75,
                "profile": None,
                "rule_version": None,
                "eval_result": None,
                "notes": None,
                "created_at": "2026-06-01T19:00:00",
            }
        ],
        "stock_memory": [],
        "deep_research": [{"memory_type": "research_pointer", "summary": "深度研报"}],
        "pending_questions": [],
        "conflicts": [],
        "official_action": {
            "recommendation": "买入",
            "position_pct": 0.1,
            "source": "decision_run",
            "is_constrained": False,
        },
        "missing": [],
    }


# ── QualityGate unit tests ──────────────────────────────────────────────────

def test_quality_gate_empty_dossier_fails():
    from backend.research.case import _build_quality_gate
    d = _minimal_dossier()
    gate = _build_quality_gate(d)
    assert gate["gate_pass"] is False
    assert "signal_present" in gate["blockers"]
    assert "label_present" in gate["blockers"]
    assert "deep_research_present" in gate["blockers"]
    assert "copilot_present" in gate["blockers"]
    assert "source_coverage_ok" in gate["blockers"]


def test_quality_gate_full_dossier_passes():
    from backend.research.case import _build_quality_gate
    d = _full_dossier()
    gate = _build_quality_gate(d)
    assert gate["gate_pass"] is True
    assert gate["blockers"] == []


def test_quality_gate_stale_signal_blocks():
    from backend.research.case import _build_quality_gate
    d = _full_dossier()
    d["latest_signal"] = dict(d["latest_signal"])
    d["latest_signal"]["date"] = "2020-01-01"  # very old
    gate = _build_quality_gate(d)
    assert "signal_fresh" in gate["blockers"]
    stale_warning_codes = [w["code"] for w in gate["warnings"]]
    assert "signal_stale" in stale_warning_codes


def test_quality_gate_pending_questions_blocks():
    from backend.research.case import _build_quality_gate
    d = _full_dossier()
    d["pending_questions"] = ["是否需要关注政策风险?"]
    gate = _build_quality_gate(d)
    assert "no_pending_questions" in gate["blockers"]


def test_quality_gate_cutoff_respected():
    from backend.research.case import _build_quality_gate
    d = _full_dossier()
    # signal date is 2026-06-01; as_of is 2026-05-01 → cutoff violation
    gate = _build_quality_gate(d, as_of="2026-05-01")
    assert "cutoff_ok" in gate["blockers"]


# ── StructuralValidityCard unit tests ──────────────────────────────────────

def test_validity_card_no_evidence_fails():
    from backend.research.case import _build_structural_validity_card
    d = _minimal_dossier()
    card = _build_structural_validity_card(d)
    assert card["card_pass"] is False
    assert "data_source" in card["missing_provenance"]
    assert "fetched_at" in card["missing_provenance"]
    assert "adjustment" in card["missing_provenance"]


def test_validity_card_full_evidence_passes():
    from backend.research.case import _build_structural_validity_card
    d = _full_dossier()
    card = _build_structural_validity_card(d)
    assert card["card_pass"] is True
    assert card["missing_provenance"] == []
    assert card["status"]["universe_hash_present"] is True
    assert card["status"]["calibration_status"] == "trusted"
    assert card["status"]["constraint_eligible"] is True


def test_validity_card_missing_universe_hash():
    from backend.research.case import _build_structural_validity_card
    d = _full_dossier()
    snapshot = dict(d["evidence"][0]["input_snapshot"])
    del snapshot["universe_hash"]
    d["evidence"][0] = dict(d["evidence"][0])
    d["evidence"][0]["input_snapshot"] = snapshot
    card = _build_structural_validity_card(d)
    assert card["status"]["universe_hash_present"] is False
    # card_pass only requires pit_ok + provenance_fields_present, not universe_hash
    assert card["card_pass"] is True


# ── build_case integration ──────────────────────────────────────────────────

def test_build_case_structure():
    from backend.research.case import build_case
    d = _full_dossier()
    case = build_case(d)
    assert case["symbol"] == "600519"
    assert "quality_gate" in case
    assert "validity_card" in case
    assert "ready" in case
    assert "generated_at" in case
    assert case["ready"] is True


def test_build_case_not_ready_when_dossier_empty():
    from backend.research.case import build_case
    d = _minimal_dossier()
    case = build_case(d)
    assert case["ready"] is False


def test_build_case_as_of_forwarded():
    from backend.research.case import build_case
    d = _full_dossier()
    case = build_case(d, as_of="2026-05-01")
    assert case["as_of"] == "2026-05-01"
    assert case["quality_gate"]["as_of"] == "2026-05-01"


def test_dossier_evidence_cards_are_read_only_l1_mapping():
    from backend.research.case import build_dossier_evidence_cards

    cards = build_dossier_evidence_cards(_full_dossier())
    kinds = {card["kind"] for card in cards}

    assert "decision_run_evidence" in kinds
    assert "long_term_label" in kinds
    assert "deep_research_pointer" in kinds
    assert all(card["source_layer"] == "L1" for card in cards)
    assert all(card["write_policy"] == "no_database_writes" for card in cards)
    assert all(card["signal_impact"] == "none" for card in cards)


def test_dossier_adapter_review_wires_l1_l2_and_pending_l0_preview():
    from backend.research.case import build_dossier_adapter_review

    review = build_dossier_adapter_review(_full_dossier(), as_of="2026-06-05")

    assert review["adapter"] == "dossier_readonly_v0"
    assert review["read_only"] is True
    assert review["research_case"]["as_of"] == "2026-06-05"
    assert review["research_case"]["ready"] is True
    assert review["evidence_cards"]
    preview = review["memory_candidate_preview"]
    assert preview["memory_type"] == "thesis"
    assert preview["source_trust_after_create"] == "pending"
    assert preview["eligible_for_creation"] is True
    assert preview["source_ref"] == "atlas:dossier_readonly_v0:600519:2026-06-05"
    assert review["promotion_gate"]["auto_promotes_trusted_memory"] is False


# ── Pydantic schema backward-compatibility tests ───────────────────────────

def test_research_dossier_out_case_field_optional():
    """ResearchDossierOut must accept a payload without 'case' and default it to None."""
    from backend.api.schemas import ResearchDossierOut
    payload = {
        "symbol": "600519",
        "research_state": {
            "symbol": "600519",
            "thesis": "",
            "risks": [],
            "open_questions": [],
            "copilot": None,
            "last_signal_summary": "",
            "last_review": None,
            "updated_at": None,
        },
    }
    out = ResearchDossierOut(**payload)
    assert out.case is None  # new field defaults to None
    assert out.symbol == "600519"
    assert out.missing == []


def test_research_dossier_out_case_field_populated():
    """ResearchDossierOut accepts a 'case' dict and exposes it via .case."""
    from backend.api.schemas import ResearchDossierOut
    from backend.research.case import build_case
    dossier_dict = _full_dossier()
    case_dict = build_case(dossier_dict)
    payload = {
        "symbol": "600519",
        "research_state": dossier_dict["research_state"],
        "case": case_dict,
    }
    out = ResearchDossierOut(**payload)
    assert out.case is not None
    assert out.case.symbol == "600519"
    assert isinstance(out.case.ready, bool)


def test_existing_clients_unaffected_by_extra_key():
    """Extra keys in builder dict are silently ignored by Pydantic v2 default (extra=ignore)."""
    from backend.api.schemas import ResearchDossierOut
    payload = {
        "symbol": "600519",
        "research_state": {
            "symbol": "600519",
            "thesis": "",
            "risks": [],
            "open_questions": [],
            "copilot": None,
            "last_signal_summary": "",
            "last_review": None,
            "updated_at": None,
        },
        "unknown_future_key": "should_be_ignored",
    }
    out = ResearchDossierOut(**payload)
    assert not hasattr(out, "unknown_future_key")


def test_signal_fresh_uses_as_of_not_wall_clock():
    """Regression: signal freshness must be measured against as_of (point-in-time),
    not datetime.utcnow(). The full-dossier signal is dated 2026-06-01.

    Before the fix, _build_quality_gate ignored as_of for freshness, so a replay
    at a far-future as_of would still look 'fresh' relative to the wall clock.
    """
    from backend.research.case import build_case

    d = _full_dossier()
    # as_of 4 days after the signal -> fresh (<= 7d threshold)
    near = build_case(d, as_of="2026-06-05")
    assert near["quality_gate"]["checks"]["signal_fresh"] is True
    # as_of ~44 days after the signal -> stale, regardless of today's wall clock
    far = build_case(d, as_of="2026-07-15")
    assert far["quality_gate"]["checks"]["signal_fresh"] is False
