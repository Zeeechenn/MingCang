"""M37 Review / Calibration / Memory Loop — hermetic storage-layer tests."""
from __future__ import annotations

import pytest
from sqlalchemy import text

# ── helpers ───────────────────────────────────────────────────────────────────

def _rc(db, symbol: str = "600519", as_of: str = "2026-06-01", **kw):
    """Create a ReviewCase via the storage layer."""
    from backend.research.review_loop import create_review_case
    return create_review_case(db, symbol=symbol, as_of=as_of, **kw)


def _cand(db, symbol: str = "600519", memory_type: str = "outcome",
          review_case_id: int | None = None, **kw):
    """Create a MemoryPromotionCandidate via the storage layer."""
    from backend.research.review_loop import create_memory_candidate
    return create_memory_candidate(
        db,
        symbol=symbol,
        memory_type=memory_type,
        summary="test summary",
        review_case_id=review_case_id,
        **kw,
    )


# ── create_review_case ────────────────────────────────────────────────────────

def test_create_review_case_returns_dict_with_expected_keys(test_db):
    rc = _rc(test_db)
    assert rc["id"] is not None
    assert rc["symbol"] == "600519"
    assert rc["as_of"] == "2026-06-01"
    assert rc["outcome_correct"] is None
    assert rc["created_at"] is not None


def test_create_review_case_idempotent_on_symbol_as_of(test_db):
    rc1 = _rc(test_db)
    rc2 = _rc(test_db)  # same symbol+as_of
    assert rc1["id"] == rc2["id"]


def test_create_review_case_stores_review_payload(test_db):
    payload = {
        "signal_date": "2026-06-01",
        "recommendation": "BUY",
        "composite_score": 0.75,
        "next_day_return": 1.23,
        "correct": True,
        "attribution": ["量化信号强", "技术面突破"],
    }
    rc = _rc(test_db, review_payload=payload)
    # Fields promoted to first-class columns
    assert rc["recommendation"] == "BUY"
    assert rc["composite_score"] == pytest.approx(0.75)
    assert rc["next_day_return"] == pytest.approx(1.23)
    assert rc["outcome_correct"] is True
    # Attribution list stored separately
    assert rc["attribution"] == ["量化信号强", "技术面突破"]
    # Full payload round-trips
    assert rc["review_payload"]["signal_date"] == "2026-06-01"


def test_create_review_case_links_thesis_id(test_db):
    rc = _rc(test_db, thesis_id=42)
    assert rc["thesis_id"] == 42


# ── get_review_case ───────────────────────────────────────────────────────────

def test_get_review_case_returns_row(test_db):
    from backend.research.review_loop import get_review_case
    created = _rc(test_db)
    fetched = get_review_case(test_db, created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]


def test_get_review_case_returns_none_for_missing_id(test_db):
    from backend.research.review_loop import get_review_case
    assert get_review_case(test_db, 9999) is None


# ── list_review_cases ─────────────────────────────────────────────────────────

def test_list_review_cases_filters_by_symbol(test_db):
    from backend.research.review_loop import list_review_cases
    _rc(test_db, symbol="600519", as_of="2026-06-01")
    _rc(test_db, symbol="600519", as_of="2026-06-02")
    _rc(test_db, symbol="300308", as_of="2026-06-01")
    results = list_review_cases(test_db, symbol="600519")
    assert len(results) == 2
    assert all(r["symbol"] == "600519" for r in results)


def test_list_review_cases_ordered_by_as_of_desc(test_db):
    from backend.research.review_loop import list_review_cases
    _rc(test_db, symbol="600519", as_of="2026-05-01")
    _rc(test_db, symbol="600519", as_of="2026-06-01")
    results = list_review_cases(test_db, symbol="600519")
    assert results[0]["as_of"] == "2026-06-01"


# ── create_memory_candidate ───────────────────────────────────────────────────

def test_create_memory_candidate_source_trust_is_pending(test_db):
    c = _cand(test_db)
    assert c["source_trust"] == "pending"


def test_create_memory_candidate_rejects_invalid_memory_type(test_db):
    with pytest.raises(ValueError, match="invalid memory_type"):
        _cand(test_db, memory_type="invented_type_xyz")


def test_create_memory_candidate_idempotent_on_source_ref(test_db):
    rc = _rc(test_db)
    c1 = _cand(test_db, review_case_id=rc["id"], source_ref="test-ref-001")
    c2 = _cand(test_db, review_case_id=rc["id"], source_ref="test-ref-001")
    assert c1["id"] == c2["id"]


def test_create_memory_candidate_without_explicit_key_does_not_merge(test_db):
    c1 = _cand(test_db)
    c2 = _cand(test_db)
    assert c1["id"] != c2["id"]


def test_create_memory_candidate_idempotent_on_review_case_id(test_db):
    rc = _rc(test_db)
    c1 = _cand(test_db, review_case_id=rc["id"])
    c2 = _cand(test_db, review_case_id=rc["id"])
    assert c1["id"] == c2["id"]


def test_create_memory_candidate_source_ref_null_is_part_of_key(test_db):
    rc = _rc(test_db)
    c1 = _cand(test_db, review_case_id=rc["id"], source_ref="test-ref-001")
    c2 = _cand(test_db, review_case_id=rc["id"])
    assert c1["id"] != c2["id"]


def test_create_memory_candidate_review_case_null_is_part_of_key(test_db):
    rc = _rc(test_db)
    c1 = _cand(test_db, source_ref="test-ref-001")
    c2 = _cand(test_db, review_case_id=rc["id"], source_ref="test-ref-001")
    assert c1["id"] != c2["id"]


def test_no_direct_trusted_write_path(test_db):
    """create_memory_candidate must not accept source_trust as a parameter."""
    import inspect

    from backend.research.review_loop import create_memory_candidate
    sig = inspect.signature(create_memory_candidate)
    assert "source_trust" not in sig.parameters, (
        "create_memory_candidate must not expose source_trust as a parameter — "
        "this would allow callers to bypass the pending-only invariant"
    )
    assert "memory_atom_id" not in sig.parameters, (
        "create_memory_candidate must not let callers link or pre-trust L0 atoms"
    )


# ── get/list memory candidates ────────────────────────────────────────────────

def test_get_memory_candidate_returns_row(test_db):
    from backend.research.review_loop import get_memory_candidate
    c = _cand(test_db)
    fetched = get_memory_candidate(test_db, c["id"])
    assert fetched is not None
    assert fetched["id"] == c["id"]


def test_get_memory_candidate_returns_none_for_missing_id(test_db):
    from backend.research.review_loop import get_memory_candidate
    assert get_memory_candidate(test_db, 9999) is None


def test_list_memory_candidates_filters_by_source_trust(test_db):
    from backend.research.review_loop import list_memory_candidates, promote_memory
    c1 = _cand(test_db, symbol="600519", memory_type="outcome", source_ref="ref-a")
    _cand(test_db, symbol="600519", memory_type="lesson", source_ref="ref-b")

    pending = list_memory_candidates(test_db, symbol="600519", source_trust="pending")
    assert len(pending) == 2

    promote_memory(test_db, c1["id"], confirmed_by="test_user")

    pending_after = list_memory_candidates(test_db, symbol="600519", source_trust="pending")
    trusted_after = list_memory_candidates(test_db, symbol="600519", source_trust="trusted")
    assert len(pending_after) == 1
    assert len(trusted_after) == 1
    assert trusted_after[0]["id"] == c1["id"]


# ── promote_memory ────────────────────────────────────────────────────────────

def test_promote_memory_moves_pending_to_trusted(test_db):
    from backend.research.review_loop import promote_memory
    c = _cand(test_db)
    result = promote_memory(test_db, c["id"], confirmed_by="human_reviewer")
    assert result["source_trust"] == "trusted"
    assert result["promoted_at"] is not None


def test_promote_memory_creates_stock_memory_item(test_db):
    from backend.memory.stock_memory import list_stock_memories
    from backend.research.review_loop import promote_memory
    c = _cand(test_db, symbol="600519", memory_type="outcome")
    result = promote_memory(test_db, c["id"], confirmed_by="human_reviewer")
    assert result["stock_memory_item_id"] is not None
    memories = list_stock_memories(test_db, symbol="600519", status="active")
    ids = [m["id"] for m in memories]
    assert result["stock_memory_item_id"] in ids


def test_promote_memory_creates_trusted_l0_atom(test_db):
    from backend.api.schemas import MemoryCandidateOut
    from backend.memory.l0_memory import list_memory_atoms
    from backend.research.review_loop import promote_memory

    c = _cand(test_db, symbol="600519", memory_type="lesson", source_ref="lesson-ref")
    result = promote_memory(test_db, c["id"], confirmed_by="human_reviewer")

    assert result["memory_atom_id"] is not None
    atoms = list_memory_atoms(test_db, scope_type="stock", scope_key="600519")
    assert len(atoms) == 1
    assert atoms[0]["id"] == result["memory_atom_id"]
    assert atoms[0]["trust_state"] == "trusted"
    assert atoms[0]["stock_memory_item_id"] == result["stock_memory_item_id"]
    assert atoms[0]["review_case_id"] == result["review_case_id"]
    serialized = MemoryCandidateOut(**result).model_dump()
    assert serialized["memory_atom_id"] == result["memory_atom_id"]
    assert serialized["stock_memory_item_id"] == result["stock_memory_item_id"]


def test_promote_memory_raises_on_non_pending(test_db):
    from backend.research.review_loop import promote_memory
    c = _cand(test_db)
    promote_memory(test_db, c["id"], confirmed_by="human_reviewer")
    with pytest.raises(ValueError, match="already in state"):
        promote_memory(test_db, c["id"], confirmed_by="human_reviewer")


def test_double_promote_raises(test_db):
    from backend.research.review_loop import promote_memory
    c = _cand(test_db)
    promote_memory(test_db, c["id"], confirmed_by="human_reviewer")
    with pytest.raises(ValueError):
        promote_memory(test_db, c["id"], confirmed_by="human_reviewer")
    rows = test_db.execute(text("SELECT count(*) FROM memory_atoms")).scalar()
    assert rows == 1


def test_promote_is_audited(test_db):
    from backend.memory.audit_log import audit_search
    from backend.research.review_loop import promote_memory
    c = _cand(test_db)
    promote_memory(test_db, c["id"], confirmed_by="test_auditor")
    hits = audit_search(test_db, "memory_promotion.confirm")
    assert len(hits) >= 1
    assert any("memory_promotion.confirm" in h["event_type"] for h in hits)


# ── reject_memory_candidate ───────────────────────────────────────────────────

def test_reject_memory_candidate_moves_pending_to_rejected(test_db):
    from backend.research.review_loop import reject_memory_candidate
    c = _cand(test_db)
    result = reject_memory_candidate(test_db, c["id"], confirmed_by="human_reviewer")
    assert result["source_trust"] == "rejected"
    assert result["rejected_at"] is not None


def test_reject_memory_candidate_creates_refuted_l0_atom_without_stock_memory(test_db):
    from backend.api.schemas import MemoryCandidateOut
    from backend.memory.l0_memory import list_memory_atoms
    from backend.memory.stock_memory import list_stock_memories
    from backend.research.review_loop import reject_memory_candidate

    c = _cand(test_db, symbol="600519", memory_type="risk", source_ref="bad-risk")
    result = reject_memory_candidate(
        test_db,
        c["id"],
        confirmed_by="human_reviewer",
        note="后续证据不支持",
    )

    assert result["memory_atom_id"] is not None
    assert result["stock_memory_item_id"] is None
    atoms = list_memory_atoms(
        test_db,
        scope_type="stock",
        scope_key="600519",
        trust_state="refuted",
    )
    assert len(atoms) == 1
    assert atoms[0]["id"] == result["memory_atom_id"]
    assert atoms[0]["refutation_reason"] == "后续证据不支持"
    assert list_stock_memories(test_db, symbol="600519") == []
    serialized = MemoryCandidateOut(**result).model_dump()
    assert serialized["memory_atom_id"] == result["memory_atom_id"]
    assert serialized["rejected_at"] == result["rejected_at"]


def test_reject_memory_candidate_raises_on_non_pending(test_db):
    from backend.research.review_loop import reject_memory_candidate
    c = _cand(test_db)
    reject_memory_candidate(test_db, c["id"], confirmed_by="human_reviewer")
    with pytest.raises(ValueError, match="already in state"):
        reject_memory_candidate(test_db, c["id"], confirmed_by="human_reviewer")


def test_reject_is_audited(test_db):
    from backend.memory.audit_log import audit_search
    from backend.research.review_loop import reject_memory_candidate
    c = _cand(test_db)
    reject_memory_candidate(test_db, c["id"], confirmed_by="test_auditor", note="not relevant")
    hits = audit_search(test_db, "memory_promotion.reject")
    assert len(hits) >= 1
    assert any("memory_promotion.reject" in h["event_type"] for h in hits)


# ── attach_review_case (thesis_ledger) ────────────────────────────────────────

def test_attach_review_case_populates_thesis_review_case_ref(test_db):
    from backend.research.thesis_ledger import attach_review_case, create_thesis, get_thesis
    thesis = create_thesis(
        test_db,
        symbol="600519",
        title="Test thesis for M37",
        kill_conditions=["ROE < 20%"],
    )
    payload = {"signal_date": "2026-06-01", "recommendation": "BUY", "correct": True}
    result = attach_review_case(
        test_db,
        thesis["id"],
        review_payload=payload,
        as_of="2026-06-01",
    )
    assert result["review_case_ref"] is not None
    assert result["review_case_ref"]["recommendation"] == "BUY"

    # Verify persisted
    fetched = get_thesis(test_db, thesis["id"])
    assert fetched["review_case_ref"] is not None


def test_attach_review_case_raises_on_unknown_thesis(test_db):
    from backend.research.thesis_ledger import attach_review_case
    with pytest.raises(ValueError, match="thesis 9999 not found"):
        attach_review_case(
            test_db, 9999, review_payload={"foo": "bar"}, as_of="2026-06-01"
        )


def test_attach_review_case_is_audited(test_db):
    from backend.memory.audit_log import audit_search
    from backend.research.thesis_ledger import attach_review_case, create_thesis
    thesis = create_thesis(
        test_db,
        symbol="600519",
        title="Audit test thesis",
        kill_conditions=["some condition"],
    )
    attach_review_case(
        test_db,
        thesis["id"],
        review_payload={"recommendation": "HOLD"},
        as_of="2026-06-02",
    )
    hits = audit_search(test_db, "thesis_ledger.review_case")
    assert len(hits) >= 1


# ── governance invariant ──────────────────────────────────────────────────────

def test_promote_memory_raises_on_rejected_candidate(test_db):
    """A rejected candidate cannot be promoted (terminal state)."""
    from backend.research.review_loop import promote_memory, reject_memory_candidate
    c = _cand(test_db)
    reject_memory_candidate(test_db, c["id"], confirmed_by="human_reviewer")
    with pytest.raises(ValueError):
        promote_memory(test_db, c["id"], confirmed_by="human_reviewer")
