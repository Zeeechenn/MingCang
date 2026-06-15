"""M45 track-analyst hook-update adapter tests."""
from __future__ import annotations


def _hook_update(**overrides):
    base = {
        "symbol": "MRVL",
        "theme": "connectivity",
        "hook_update": "track-analyst repeats that connectivity switching demand remains the key thesis.",
        "source": "track-analyst hook",
        "source_ref": "track-hook-2026-06-06-mrvl-connectivity",
        "source_url": "local://track-analyst/hook/2026-06-06",
        "source_kind": "direct_source",
        "source_tier": "filing",
        "evidence_level": "verified",
        "source_verified": True,
        "source_verified_by": "tester",
        "as_of": "2026-06-06",
        "horizon_date": "2026-12-31",
        "invalidation_conditions": [
            "Switching backlog fails to confirm incremental demand",
            "Connectivity margin guide is cut",
        ],
        "follow_up_metrics": ["switching backlog", "margin guide"],
        "review_cadence_days": 14,
        "next_review_date": "2026-06-20",
    }
    base.update(overrides)
    return base


def test_m45_track_hook_update_dry_run_routes_to_import_contract(test_db):
    from backend.data.database import ForwardThesis
    from backend.tools.m45_track_hook_update import execute_hook_updates, normalize_hook_update

    result = execute_hook_updates(None, [normalize_hook_update(_hook_update())], execute=False)

    assert result["mode"] == "dry_run"
    assert result["safety"]["writes_db"] is False
    assert result["production_impact"] == "none"
    assert result["planned"][0]["source_ref"] == "track-hook-2026-06-06-mrvl-connectivity"
    assert result["planned"][0]["forward_thesis"]["statement"] == (
        "track-analyst repeats that connectivity switching demand remains the key thesis."
    )
    assert result["planned"][0]["l0_memory_atom"]["trust_state"] == "pending"
    assert test_db.query(ForwardThesis).count() == 0


def test_m45_track_hook_update_execute_writes_draft_and_l0_pending_only(test_db):
    from backend.data.database import ForwardThesis, MemoryPromotionCandidate, StockMemoryItem
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_track_hook_update import execute_hook_updates, normalize_hook_update

    result = execute_hook_updates(test_db, [normalize_hook_update(_hook_update())], execute=True)

    assert result["mode"] == "execute"
    assert result["safety"]["writes_trusted_memory"] is False
    thesis = test_db.query(ForwardThesis).one()
    assert thesis.symbol == "MRVL"
    assert thesis.status == "draft"
    atoms = list_memory_atoms(test_db, scope_type="stock", scope_key="MRVL", trust_state="pending")
    assert len(atoms) == 1
    assert atoms[0]["source_type"] == "track_import"
    assert atoms[0]["evidence"]["source"] == "track-analyst hook"
    assert atoms[0]["evidence"]["production_impact"] == "none"
    assert test_db.query(MemoryPromotionCandidate).count() == 0
    assert test_db.query(StockMemoryItem).count() == 0


def test_m45_track_hook_update_rejects_markdown_only_note():
    import pytest

    from backend.tools.m45_track_hook_update import normalize_hook_update

    with pytest.raises(ValueError, match="hook_update is required"):
        normalize_hook_update(_hook_update(hook_update=None, markdown_note="loose note"))


def test_m45_track_hook_update_rejects_trading_fields():
    import pytest

    from backend.tools.m45_track_hook_update import normalize_hook_update

    with pytest.raises(ValueError, match="forbidden trading fields"):
        normalize_hook_update(_hook_update(price_target=88.0))


def test_m45_track_hook_update_execute_inherits_source_gate(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_track_hook_update import execute_hook_updates, normalize_hook_update

    with pytest.raises(ValueError, match="evidence_level_needs_check"):
        execute_hook_updates(
            test_db,
            [normalize_hook_update(_hook_update(evidence_level="needs_check"))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []
