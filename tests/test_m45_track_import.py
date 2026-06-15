"""M45 track-analyst thesis import tests.

The importer is dry-run-first and writes only ForwardThesis + L0 pending atoms
when explicitly executed.
"""
from __future__ import annotations

import ast


def _item(**overrides):
    base = {
        "symbol": "300308",
        "theme": "optical modules",
        "statement": "Optical module leaders benefit from AI capex pull-forward.",
        "source": "track-analyst",
        "source_ref": "track-2026-06-05-optical",
        "source_url": "local://track-analyst/2026-06-05",
        "source_kind": "direct_source",
        "source_tier": "filing",
        "evidence_level": "verified",
        "source_verified": True,
        "source_verified_by": "tester",
        "as_of": "2026-06-05",
        "horizon_date": "2026-12-31",
        "invalidation_conditions": [
            "Cloud capex guide is cut",
            "Order checks fail to confirm incremental demand",
        ],
        "follow_up_metrics": ["capex guide", "order checks"],
        "review_cadence_days": 14,
        "next_review_date": "2026-06-19",
    }
    base.update(overrides)
    return base


def test_m45_track_import_dry_run_does_not_write(test_db):
    from backend.data.database import ForwardThesis
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    result = execute_import(None, [normalize_item(_item())], execute=False)

    assert result["mode"] == "dry_run"
    assert result["production_impact"] == "none"
    assert result["safety"]["writes_db"] is False
    assert result["safety"]["touches_official_signal"] is False
    assert result["safety"]["touches_test2"] is False
    assert result["count"] == 1
    assert result["planned"][0]["source_fidelity"] == {
        "source_kind": "direct_source",
        "source_tier": "filing",
        "evidence_level": "verified",
        "source_verified": True,
        "source_verified_by": "tester",
        "source_verified_at": None,
        "execute_ready": True,
        "execute_blockers": [],
    }
    assert result["planned"][0]["l0_memory_atom"]["trust_state"] == "pending"
    assert result["planned"][0]["forward_thesis"]["status"] == "draft"
    assert test_db.query(ForwardThesis).count() == 0


def test_m45_track_import_execute_writes_forward_thesis_and_l0_pending(test_db):
    from backend.data.database import ForwardThesis, MemoryPromotionCandidate, StockMemoryItem
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    result = execute_import(test_db, [normalize_item(_item())], execute=True)

    assert result["mode"] == "execute"
    assert result["production_impact"] == "none"
    assert result["safety"]["writes_db"] is True
    assert result["safety"]["writes_trusted_memory"] is False
    assert result["writes"][0]["memory_trust_state"] == "pending"

    thesis = test_db.query(ForwardThesis).one()
    assert thesis.symbol == "300308"
    assert thesis.statement == "Optical module leaders benefit from AI capex pull-forward."
    assert thesis.status == "draft"
    assert thesis.review_cadence_days == 14

    atoms = list_memory_atoms(test_db, scope_type="stock", scope_key="300308", trust_state="pending")
    assert len(atoms) == 1
    atom = atoms[0]
    assert atom["source_type"] == "track_import"
    assert atom["source_ref"] == "track-2026-06-05-optical"
    assert atom["memory_type"] == "imported_human_thesis"
    assert atom["evidence"]["decision_owner"] == "human"
    assert atom["evidence"]["source_kind"] == "direct_source"
    assert atom["evidence"]["source_verified"] is True
    assert atom["evidence"]["source_verified_by"] == "tester"
    assert atom["evidence"]["production_impact"] == "none"
    assert atom["evidence"]["forward_thesis_id"] == thesis.id
    assert test_db.query(MemoryPromotionCandidate).count() == 0
    assert test_db.query(StockMemoryItem).count() == 0


def test_m45_track_import_is_idempotent(test_db):
    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    item = normalize_item(_item())
    first = execute_import(test_db, [item], execute=True)
    second = execute_import(test_db, [item], execute=True)

    assert first["writes"][0]["forward_thesis_id"] == second["writes"][0]["forward_thesis_id"]
    assert first["writes"][0]["memory_atom_id"] == second["writes"][0]["memory_atom_id"]
    assert test_db.query(ForwardThesis).count() == 1
    assert len(list_memory_atoms(test_db, q="Optical module leaders", include_archived=True)) == 1


def test_m45_track_import_appends_manifest_for_new_source_ref_same_thesis(test_db):
    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    first = normalize_item(_item(source_ref="source-a"))
    second = normalize_item(_item(source_ref="source-b", source_note="second confirmation"))

    first_result = execute_import(test_db, [first], execute=True)
    second_result = execute_import(test_db, [second], execute=True)

    assert first_result["writes"][0]["forward_thesis_id"] == second_result["writes"][0]["forward_thesis_id"]
    thesis = test_db.query(ForwardThesis).one()
    assert thesis.evidence_manifest_json is not None
    assert "source-a" in thesis.evidence_manifest_json
    assert "source-b" in thesis.evidence_manifest_json
    atoms = list_memory_atoms(test_db, scope_type="stock", scope_key="300308", trust_state="pending")
    assert {atom["source_ref"] for atom in atoms} == {"source-a", "source-b"}


def test_m45_track_import_refuses_protected_l0_source_ref_before_forward_write(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import create_memory_atom, promote_atom
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    atom = create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="imported_human_thesis",
        summary="already trusted",
        source_type="track_import",
        source_ref="protected-source",
        trust_state="pending",
    )
    promote_atom(test_db, atom["id"], confirmed_by="tester")

    with pytest.raises(ValueError, match="protected L0 trust_state"):
        execute_import(test_db, [normalize_item(_item(source_ref="protected-source"))], execute=True)

    assert test_db.query(ForwardThesis).count() == 0


def test_m45_track_import_requires_forward_thesis_enabled(test_db, monkeypatch):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools import m45_import_track_theses as tool

    monkeypatch.setattr(tool.settings, "forward_thesis_enabled", False, raising=False)

    with pytest.raises(ValueError, match="forward_thesis_enabled"):
        tool.execute_import(test_db, [tool.normalize_item(_item())], execute=True)

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_dry_run_flags_unverified_source(test_db):
    from backend.data.database import ForwardThesis
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    result = execute_import(
        None,
        [normalize_item(_item(source_verified=False))],
        execute=False,
    )

    assert result["mode"] == "dry_run"
    assert result["safety"]["writes_db"] is False
    assert result["planned"][0]["source_fidelity"] == {
        "source_kind": "direct_source",
        "source_tier": "filing",
        "evidence_level": "verified",
        "source_verified": False,
        "source_verified_by": "tester",
        "source_verified_at": None,
        "execute_ready": False,
        "execute_blockers": ["source_not_verified"],
    }
    assert test_db.query(ForwardThesis).count() == 0


def test_m45_track_import_execute_refuses_unverified_source(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="source_not_verified"):
        execute_import(
            test_db,
            [normalize_item(_item(source_verified=False))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_requires_direct_source_kind(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="source_kind_not_direct_source"):
        execute_import(
            test_db,
            [normalize_item(_item(source_kind="handoff_context"))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_rejects_derived_summary_source_kind(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="source_kind_not_direct_source"):
        execute_import(
            test_db,
            [normalize_item(_item(source_kind="derived_summary"))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_rejects_social_only_source_tier(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="source_tier_social_only"):
        execute_import(
            test_db,
            [normalize_item(_item(source_tier="social_lead"))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_rejects_needs_check_evidence_level(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="evidence_level_needs_check"):
        execute_import(
            test_db,
            [normalize_item(_item(evidence_level="needs_check"))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_requires_source_tier(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="missing_source_tier"):
        execute_import(
            test_db,
            [normalize_item(_item(source_tier=None))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_requires_source_verified_by(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="missing_source_verified_by"):
        execute_import(
            test_db,
            [normalize_item(_item(source_verified_by=None))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_requires_explicit_source_ref(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="missing_explicit_source_ref"):
        execute_import(
            test_db,
            [normalize_item(_item(source_ref=None))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_execute_requires_source_locator(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    with pytest.raises(ValueError, match="missing_source_locator"):
        execute_import(
            test_db,
            [normalize_item(_item(source_url=None, source_note=None))],
            execute=True,
        )

    assert test_db.query(ForwardThesis).count() == 0
    assert list_memory_atoms(test_db, include_archived=True) == []


def test_m45_track_import_refuses_pending_source_ref_identity_mismatch(test_db):
    import pytest

    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import create_memory_atom, list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    create_memory_atom(
        test_db,
        scope_type="stock",
        scope_key="300308",
        memory_type="imported_human_thesis",
        summary="different pending summary",
        source_type="track_import",
        source_ref="track-2026-06-05-optical",
        trust_state="pending",
    )

    with pytest.raises(ValueError, match="different M45 identity fields"):
        execute_import(test_db, [normalize_item(_item())], execute=True)

    assert test_db.query(ForwardThesis).count() == 0
    atoms = list_memory_atoms(test_db, include_archived=True)
    assert len(atoms) == 1
    assert atoms[0]["summary"] == "different pending summary"


def test_m45_track_import_does_not_touch_signal_decision_or_position(test_db):
    from backend.data.database import DecisionRun, Position, Signal
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    test_db.add(Signal(
        symbol="300308",
        date="2026-06-05",
        composite_score=10.0,
        recommendation="观望",
        confidence="低",
    ))
    test_db.add(DecisionRun(run_id="m45-side-effect-guard", run_type="test", symbol="300308"))
    test_db.add(Position(
        symbol="300308",
        quantity=100,
        avg_cost=10,
        opened_at="2026-06-05",
    ))
    test_db.commit()

    execute_import(test_db, [normalize_item(_item())], execute=True)

    assert test_db.query(Signal).count() == 1
    assert test_db.query(DecisionRun).count() == 1
    assert test_db.query(Position).count() == 1


def test_m45_track_import_theme_scope_without_symbol(test_db):
    from backend.data.database import ForwardThesis
    from backend.memory.l0_memory import list_memory_atoms
    from backend.tools.m45_import_track_theses import execute_import, normalize_item

    raw = _item(symbol=None, theme="memory cycle")
    result = execute_import(test_db, [normalize_item(raw)], execute=True)

    assert result["writes"][0]["scope"] == {"type": "theme", "key": "memory cycle"}
    assert test_db.query(ForwardThesis).one().statement.startswith("[theme:memory cycle]")
    atoms = list_memory_atoms(test_db, scope_type="theme", scope_key="memory cycle", trust_state="pending")
    assert len(atoms) == 1


def test_m45_track_import_requires_invalidation_conditions():
    import pytest

    from backend.tools.m45_import_track_theses import normalize_item

    with pytest.raises(ValueError, match="invalidation_conditions"):
        normalize_item(_item(invalidation_conditions=[]))


def test_m45_track_import_requires_review_cadence_days():
    import pytest

    from backend.tools.m45_import_track_theses import normalize_item

    with pytest.raises(ValueError, match="review_cadence_days"):
        normalize_item(_item(review_cadence_days=None))


def test_m45_track_import_rejects_trading_fields():
    import pytest

    from backend.tools.m45_import_track_theses import normalize_item

    with pytest.raises(ValueError, match="forbidden trading fields"):
        normalize_item(_item(price_target=88.0, position_size=0.2))


def test_m45_track_import_source_verified_must_be_boolean():
    import pytest

    from backend.tools.m45_import_track_theses import normalize_item

    with pytest.raises(ValueError, match="source_verified must be a boolean"):
        normalize_item(_item(source_verified="yes"))


def test_m45_track_import_rejects_unknown_source_kind():
    import pytest

    from backend.tools.m45_import_track_theses import normalize_item

    with pytest.raises(ValueError, match="source_kind"):
        normalize_item(_item(source_kind="chat_recap"))


def test_m45_importer_has_no_official_signal_test2_or_scheduler_imports():
    module_path = "backend/tools/m45_import_track_theses.py"
    tree = ast.parse(open(module_path, encoding="utf-8").read())
    forbidden_prefixes = (
        "backend.decision",
        "backend.jobs",
        "backend.scheduler",
        "paper_trading",
    )

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    assert not [
        name for name in imports
        if name.startswith(forbidden_prefixes)
    ]
