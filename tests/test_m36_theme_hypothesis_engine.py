"""M36 Theme Hypothesis Engine — hermetic storage-layer tests."""
from __future__ import annotations

import pytest


# helpers
def _theme(db, name="光模块/CPO", **kw):
    from backend.research.theme_hypothesis_engine import create_theme
    return create_theme(db, theme_name=name, **kw)


def _hyp(db, theme_id, statement="CPO渗透率2026年超50%", **kw):
    from backend.research.theme_hypothesis_engine import create_hypothesis
    return create_hypothesis(db, theme_id=theme_id, statement=statement, **kw)


# create_theme
def test_create_theme_returns_dict(test_db):
    t = _theme(test_db)
    assert t["id"] is not None
    assert t["theme_name"] == "光模块/CPO"
    assert t["status"] == "active"


def test_create_theme_idempotent(test_db):
    t1 = _theme(test_db)
    t2 = _theme(test_db)
    assert t1["id"] == t2["id"]


def test_create_theme_rejects_invalid_status(test_db):
    with pytest.raises(ValueError, match="invalid status"):
        _theme(test_db, status="pending")


# get_theme / list_themes
def test_get_theme_returns_row(test_db):
    from backend.research.theme_hypothesis_engine import get_theme
    created = _theme(test_db)
    fetched = get_theme(test_db, created["id"])
    assert fetched["id"] == created["id"]


def test_get_theme_returns_none_for_missing(test_db):
    from backend.research.theme_hypothesis_engine import get_theme
    assert get_theme(test_db, 9999) is None


def test_list_themes_filters_by_status(test_db):
    from backend.research.theme_hypothesis_engine import list_themes
    _theme(test_db, name="AI算力")
    _theme(test_db, name="存储周期", status="watch")
    active = list_themes(test_db, status="active")
    assert len(active) == 1
    assert active[0]["theme_name"] == "AI算力"


# create_hypothesis
def test_create_hypothesis_returns_dict(test_db):
    t = _theme(test_db)
    h = _hyp(test_db, t["id"])
    assert h["id"] is not None
    assert h["theme_id"] == t["id"]
    assert h["status"] == "proposed"
    assert h["ai_supply_chain"] is None


def test_create_hypothesis_idempotent(test_db):
    t = _theme(test_db)
    h1 = _hyp(test_db, t["id"])
    h2 = _hyp(test_db, t["id"])
    assert h1["id"] == h2["id"]


def test_create_hypothesis_rejects_bad_status(test_db):
    t = _theme(test_db)
    with pytest.raises(ValueError, match="invalid status"):
        _hyp(test_db, t["id"], status="maybe")


def test_create_hypothesis_rejects_unknown_theme(test_db):
    with pytest.raises(ValueError, match="not found"):
        _hyp(test_db, 9999)


def test_forward_evidence_ref_is_none_by_default(test_db):
    t = _theme(test_db)
    h = _hyp(test_db, t["id"])
    assert h["forward_evidence_ref"] is None


def test_beneficiary_tiers_stored_and_retrieved(test_db):
    t = _theme(test_db)
    tiers = [{"symbol": "300308", "tier": 1, "rationale": "直接受益"}]
    h = _hyp(test_db, t["id"], beneficiary_tiers=tiers)
    assert h["beneficiary_tiers"][0]["symbol"] == "300308"
    assert h["beneficiary_tiers"][0]["tier"] == 1


def test_evidence_gaps_and_invalidation_conditions(test_db):
    t = _theme(test_db)
    h = _hyp(
        test_db,
        t["id"],
        evidence_gaps=["需要Q2出货数据"],
        invalidation_conditions=["CPO渗透率低于20%"],
    )
    assert "需要Q2出货数据" in h["evidence_gaps"]
    assert "CPO渗透率低于20%" in h["invalidation_conditions"]


def test_create_hypothesis_with_ai_supply_chain_template(test_db):
    from backend.research.theme_hypothesis_engine import create_hypothesis

    t = _theme(test_db, name="AI算力")
    h = create_hypothesis(
        test_db,
        theme_id=t["id"],
        statement="AI推理需求会拉动上游瓶颈资产",
        ai_supply_chain={
            "new_capability": "推理成本下降",
            "new_bottleneck": "HBM 与数据中心电力",
            "payer": "云厂商",
            "evidence_cards": [{
                "claim": "HBM 供需紧张",
                "source": "company_call",
                "gap": "缺少交期数据",
                "linked_symbols": ["300308"],
            }],
            "beneficiary_tiers": [{"symbol": "300308", "tier": 1, "rationale": "直接受益"}],
            "invalidation_conditions": ["云厂商下修 capex"],
        },
    )
    assert h["ai_supply_chain"]["observe_only"] is True
    assert h["ai_supply_chain"]["signal_impact"] == "none"
    assert h["beneficiary_tiers"][0]["symbol"] == "300308"
    assert "缺少交期数据" in h["evidence_gaps"]
    assert "云厂商下修 capex" in h["invalidation_conditions"]


def test_create_hypothesis_ai_supply_chain_rejects_score_like_fields(test_db):
    from backend.research.theme_hypothesis_engine import create_hypothesis

    t = _theme(test_db, name="AI算力")
    with pytest.raises(ValueError, match="position_pct"):
        create_hypothesis(
            test_db,
            theme_id=t["id"],
            statement="bad scoring payload",
            ai_supply_chain={
                "new_capability": "推理成本下降",
                "nested": {"position_pct": 0.2},
            },
        )


# update_hypothesis_status
def test_update_hypothesis_status_valid(test_db):
    from backend.research.theme_hypothesis_engine import update_hypothesis_status
    t = _theme(test_db)
    h = _hyp(test_db, t["id"])
    updated = update_hypothesis_status(test_db, h["id"], "supported")
    assert updated["status"] == "supported"


def test_update_hypothesis_status_illegal_transition(test_db):
    from backend.research.theme_hypothesis_engine import update_hypothesis_status
    t = _theme(test_db)
    h = _hyp(test_db, t["id"])
    update_hypothesis_status(test_db, h["id"], "invalidated")
    with pytest.raises(ValueError, match="transition"):
        update_hypothesis_status(test_db, h["id"], "proposed")


def test_update_hypothesis_status_rejects_invalid_string(test_db):
    from backend.research.theme_hypothesis_engine import update_hypothesis_status
    t = _theme(test_db)
    h = _hyp(test_db, t["id"])
    with pytest.raises(ValueError, match="invalid status"):
        update_hypothesis_status(test_db, h["id"], "approved")


# set_beneficiary_tiers
def test_set_beneficiary_tiers_replaces(test_db):
    from backend.research.theme_hypothesis_engine import set_beneficiary_tiers
    t = _theme(test_db)
    h = _hyp(test_db, t["id"], beneficiary_tiers=[{"symbol": "300308", "tier": 1, "rationale": "old"}])
    updated = set_beneficiary_tiers(test_db, h["id"], tiers=[{"symbol": "603986", "tier": 2, "rationale": "new"}])
    assert updated["beneficiary_tiers"][0]["symbol"] == "603986"
    assert len(updated["beneficiary_tiers"]) == 1


def test_set_beneficiary_tiers_rejects_invalid_tier(test_db):
    from backend.research.theme_hypothesis_engine import set_beneficiary_tiers
    t = _theme(test_db)
    h = _hyp(test_db, t["id"])
    with pytest.raises(ValueError, match="tier must be 1, 2, or 3"):
        set_beneficiary_tiers(test_db, h["id"], tiers=[{"symbol": "X", "tier": 5, "rationale": "bad"}])


def test_set_beneficiary_tiers_rejects_unknown_hypothesis(test_db):
    from backend.research.theme_hypothesis_engine import set_beneficiary_tiers
    with pytest.raises(ValueError, match="not found"):
        set_beneficiary_tiers(test_db, 9999, tiers=[])


# list_hypotheses
def test_list_hypotheses_filters_by_theme(test_db):
    from backend.research.theme_hypothesis_engine import list_hypotheses
    t1 = _theme(test_db, name="AI算力")
    t2 = _theme(test_db, name="存储")
    _hyp(test_db, t1["id"], statement="H1")
    _hyp(test_db, t1["id"], statement="H2")
    _hyp(test_db, t2["id"], statement="H3")
    assert len(list_hypotheses(test_db, theme_id=t1["id"])) == 2
    assert len(list_hypotheses(test_db, theme_id=t2["id"])) == 1
