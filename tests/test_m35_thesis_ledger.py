"""M35 Thesis Ledger — hermetic storage-layer tests."""
from __future__ import annotations

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────

def _create(db, symbol="600519", title="贵州茅台高端白酒护城河", **kw):
    from backend.research.thesis_ledger import create_thesis
    return create_thesis(
        db,
        symbol=symbol,
        title=title,
        kill_conditions=kw.pop("kill_conditions", ["ROE drops below 25%"]),
        **kw,
    )


# ── create_thesis ─────────────────────────────────────────────────────────────

def test_create_returns_dict_with_expected_keys(test_db):
    t = _create(test_db)
    assert t["id"] is not None
    assert t["symbol"] == "600519"
    assert t["status"] == "active"
    assert t["kill_conditions"] == ["ROE drops below 25%"]
    assert t["created_at"] is not None


def test_create_idempotent_on_duplicate_symbol_title(test_db):
    t1 = _create(test_db)
    t2 = _create(test_db)  # same symbol+title
    assert t1["id"] == t2["id"]  # no duplicate inserted


def test_create_rejects_invalid_status(test_db):
    with pytest.raises(ValueError, match="invalid status"):
        _create(test_db, status="pending")


def test_create_links_research_case_as_of(test_db):
    t = _create(test_db, research_case_as_of="2026-06-01")
    assert t["research_case_as_of"] == "2026-06-01"
    assert t["research_case_symbol"] == t["symbol"]


def test_create_review_case_ref_is_none_by_default(test_db):
    t = _create(test_db)
    assert t["review_case_ref"] is None


# ── get_thesis ────────────────────────────────────────────────────────────────

def test_get_thesis_returns_row(test_db):
    created = _create(test_db)
    fetched = _get(test_db, created["id"])
    assert fetched["id"] == created["id"]


def test_get_thesis_returns_none_for_missing_id(test_db):
    from backend.research.thesis_ledger import get_thesis
    assert get_thesis(test_db, 9999) is None


def _get(db, tid):
    from backend.research.thesis_ledger import get_thesis
    return get_thesis(db, tid)


# ── list_theses ───────────────────────────────────────────────────────────────

def test_list_theses_returns_all_for_symbol(test_db):
    from backend.research.thesis_ledger import list_theses
    _create(test_db, title="thesis A")
    _create(test_db, title="thesis B")
    _create(test_db, symbol="300308", title="thesis C")
    results = list_theses(test_db, symbol="600519")
    assert len(results) == 2


def test_list_theses_filters_by_status(test_db):
    from backend.research.thesis_ledger import list_theses, update_thesis_status
    t = _create(test_db, title="watch thesis")
    update_thesis_status(test_db, t["id"], "watch")
    active = list_theses(test_db, symbol="600519", status="active")
    watching = list_theses(test_db, symbol="600519", status="watch")
    assert len(active) == 0
    assert len(watching) == 1


# ── update_thesis_status ──────────────────────────────────────────────────────

def test_update_status_valid_transition(test_db):
    from backend.research.thesis_ledger import update_thesis_status
    t = _create(test_db)
    updated = update_thesis_status(test_db, t["id"], "watch")
    assert updated["status"] == "watch"


def test_update_status_rejects_illegal_transition(test_db):
    from backend.research.thesis_ledger import update_thesis_status
    t = _create(test_db)
    update_thesis_status(test_db, t["id"], "broken")
    # broken -> active is not in allowed transitions
    with pytest.raises(ValueError, match="transition"):
        update_thesis_status(test_db, t["id"], "active")


def test_update_status_rejects_invalid_status_string(test_db):
    from backend.research.thesis_ledger import update_thesis_status
    t = _create(test_db)
    with pytest.raises(ValueError, match="invalid status"):
        update_thesis_status(test_db, t["id"], "invalidated")


def test_update_status_retired_is_terminal(test_db):
    from backend.research.thesis_ledger import update_thesis_status
    t = _create(test_db)
    update_thesis_status(test_db, t["id"], "retired")
    with pytest.raises(ValueError, match="transition"):
        update_thesis_status(test_db, t["id"], "active")


# ── append_confidence ─────────────────────────────────────────────────────────

def test_append_confidence_creates_entry(test_db):
    from backend.research.thesis_ledger import append_confidence
    t = _create(test_db)
    entry = append_confidence(test_db, t["id"], score=0.8, as_of="2026-06-01", note="initial")
    assert entry["thesis_id"] == t["id"]
    assert entry["score"] == pytest.approx(0.8)
    assert entry["as_of"] == "2026-06-01"


def test_append_confidence_clamps_score(test_db):
    from backend.research.thesis_ledger import append_confidence
    t = _create(test_db)
    e_high = append_confidence(test_db, t["id"], score=1.5, as_of="2026-06-01")
    e_low = append_confidence(test_db, t["id"], score=-0.2, as_of="2026-06-02")
    assert e_high["score"] == pytest.approx(1.0)
    assert e_low["score"] == pytest.approx(0.0)


def test_append_confidence_is_append_only(test_db):
    from backend.research.thesis_ledger import append_confidence
    t = _create(test_db)
    e1 = append_confidence(test_db, t["id"], score=0.6, as_of="2026-05-01")
    e2 = append_confidence(test_db, t["id"], score=0.4, as_of="2026-06-01")
    assert e1["id"] != e2["id"]  # separate rows, not overwritten


def test_append_confidence_rejects_unknown_thesis(test_db):
    from backend.research.thesis_ledger import append_confidence
    with pytest.raises(ValueError, match="not found"):
        append_confidence(test_db, 9999, score=0.5, as_of="2026-06-01")
