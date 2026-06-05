"""HTTP-layer tests for M40 research routes.

Exercises routes through FastAPI TestClient so response_model serialization
is validated (the existing test_m40_research_routes.py calls route functions
directly and bypasses that validation layer — this file closes that gap).

All tests are hermetic: each uses a fresh sqlite:///:memory: engine with
StaticPool. The real stock-sage.db is never touched.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.data.database import Base, get_db
from backend.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_client(db_session):
    """Return a TestClient whose get_db dependency is overridden to use db_session."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Do NOT use context-manager form so we skip the lifespan init_db() call
    # which would try to open the real database_url.
    return TestClient(app, raise_server_exceptions=True)


def _clear_override():
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def http_db():
    """Fresh in-memory SQLite session for HTTP tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(http_db):
    """TestClient with isolated DB, override cleared in teardown."""
    c = _make_client(http_db)
    try:
        yield c
    finally:
        _clear_override()


@pytest.fixture(autouse=True)
def enable_atlas_routes(monkeypatch):
    """M40 route tests exercise Atlas routes explicitly."""
    monkeypatch.setattr("backend.config.settings.atlas_enabled", True, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A safe symbol that won't collide with literal route segments
_SYM = "600519"


def test_atlas_total_switch_disables_new_routes_but_keeps_legacy_research_state(client, monkeypatch):
    """Atlas routes are dormant by default; legacy research state route stays live."""
    monkeypatch.setattr("backend.config.settings.atlas_enabled", False, raising=False)

    atlas_resp = client.get("/api/research/themes")
    assert atlas_resp.status_code == 503
    assert atlas_resp.json()["detail"] == "atlas feature is disabled"

    legacy_resp = client.get(f"/api/research/{_SYM}")
    assert legacy_resp.status_code == 200, legacy_resp.text
    assert legacy_resp.json()["symbol"] == _SYM

    dossier_resp = client.get(f"/api/research/{_SYM}/dossier")
    assert dossier_resp.status_code == 200, dossier_resp.text
    assert dossier_resp.json()["case"] is None

    adapter_resp = client.get(f"/api/research/{_SYM}/adapter-review")
    assert adapter_resp.status_code == 503
    assert adapter_resp.json()["detail"] == "atlas feature is disabled"


# ---------------------------------------------------------------------------
# Thesis round-trip
# ---------------------------------------------------------------------------


def test_thesis_create_and_get_http(client):
    """POST minimal thesis then GET by id — validates ThesisOut serialization.

    ThesisCreateRequest requires 'symbol' in the body (schema-level validation),
    even though the route also accepts symbol from the URL path.
    """
    post_resp = client.post(
        f"/api/research/{_SYM}/theses",
        json={"symbol": _SYM, "title": "HTTP thesis test"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    # response_model ThesisOut required fields
    assert body["id"]
    assert body["symbol"] == _SYM
    assert body["title"] == "HTTP thesis test"

    thesis_id = body["id"]
    get_resp = client.get(f"/api/research/theses/{thesis_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == thesis_id


def test_thesis_list_http(client):
    """GET /research/{symbol}/theses returns ThesisListOut with items + total."""
    client.post(f"/api/research/{_SYM}/theses", json={"symbol": _SYM, "title": "list test thesis"})
    resp = client.get(f"/api/research/{_SYM}/theses")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 1


def test_thesis_confidence_returns_entry_http(client):
    """POST /confidence returns ThesisConfidenceOut, not ThesisOut."""
    thesis_id = client.post(
        f"/api/research/{_SYM}/theses",
        json={"symbol": _SYM, "title": "confidence response model thesis"},
    ).json()["id"]

    resp = client.post(
        f"/api/research/theses/{thesis_id}/confidence",
        json={"score": 0.72, "as_of": "2026-03-01", "note": "HTTP confidence"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["thesis_id"] == thesis_id
    assert body["score"] == pytest.approx(0.72)
    assert body["as_of"] == "2026-03-01"
    assert body["note"] == "HTTP confidence"
    assert "title" not in body


def test_thesis_attach_review_case_returns_and_gets_ref_http(client):
    """POST attach-review-case and GET thesis both expose review_case_ref."""
    thesis_id = client.post(
        f"/api/research/{_SYM}/theses",
        json={"symbol": _SYM, "title": "review case ref thesis"},
    ).json()["id"]
    payload = {"recommendation": "BUY", "correct": True, "source": "http-test"}

    attach_resp = client.post(
        f"/api/research/theses/{thesis_id}/attach-review-case",
        json={"review_payload": payload, "as_of": "2026-03-02"},
    )
    assert attach_resp.status_code == 200, attach_resp.text
    assert attach_resp.json()["review_case_ref"] == payload

    get_resp = client.get(f"/api/research/theses/{thesis_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["review_case_ref"] == payload


# ---------------------------------------------------------------------------
# Theme round-trip
# ---------------------------------------------------------------------------


def test_theme_create_and_get_http(client):
    """POST minimal theme then GET by id — validates ThemeOut serialization."""
    post_resp = client.post(
        "/api/research/themes",
        json={"theme_name": "AI Wave"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["id"]
    assert body["theme_name"] == "AI Wave"

    theme_id = body["id"]
    get_resp = client.get(f"/api/research/themes/{theme_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == theme_id


def test_theme_list_http(client):
    """GET /research/themes returns ThemeListOut (not shadowed by /research/{symbol}).

    Regression for the route-ordering bug where the catch-all GET /research/{symbol}
    shadowed the static /research/themes list route and returned ResearchStateOut.
    """
    client.post("/api/research/themes", json={"theme_name": "Infra"})
    resp = client.get("/api/research/themes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "total" in body, f"shadowed by /research/{{symbol}}? got {list(body)}"
    assert any(t["theme_name"] == "Infra" for t in body["items"])


# ---------------------------------------------------------------------------
# Hypothesis round-trip
# ---------------------------------------------------------------------------


def test_hypothesis_create_and_get_http(client):
    """POST minimal hypothesis then GET by id — validates HypothesisOut serialization."""
    theme_resp = client.post("/api/research/themes", json={"theme_name": "Hypo Theme"})
    theme_id = theme_resp.json()["id"]

    post_resp = client.post(
        f"/api/research/themes/{theme_id}/hypotheses",
        json={"statement": "Capex will accelerate in H2"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["id"]
    assert body["theme_id"] == theme_id
    assert body["statement"] == "Capex will accelerate in H2"

    hypo_id = body["id"]
    get_resp = client.get(f"/api/research/hypotheses/{hypo_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == hypo_id


def test_hypothesis_list_for_theme_http(client):
    """GET /research/themes/{theme_id}/hypotheses returns HypothesisListOut."""
    theme_id = client.post("/api/research/themes", json={"theme_name": "List Hypo Theme"}).json()["id"]
    client.post(
        f"/api/research/themes/{theme_id}/hypotheses",
        json={"statement": "Supply chain decoupling"},
    )
    resp = client.get(f"/api/research/themes/{theme_id}/hypotheses")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert body["total"] >= 1


def test_hypothesis_attach_forward_evidence_returns_and_gets_ref_http(client):
    """POST forward-evidence and GET hypothesis both expose forward_evidence_ref."""
    theme_id = client.post("/api/research/themes", json={"theme_name": "Forward Evidence Theme"}).json()["id"]
    hypo_id = client.post(
        f"/api/research/themes/{theme_id}/hypotheses",
        json={"statement": "Forward evidence survives response model"},
    ).json()["id"]
    payload = {
        "forward_thesis_id": 11,
        "universe_snapshot_id": 22,
        "schema_version": "m39.v1",
    }

    attach_resp = client.post(
        f"/api/research/hypotheses/{hypo_id}/forward-evidence",
        json={"evidence_payload": payload, "as_of": "2026-03-03"},
    )
    assert attach_resp.status_code == 200, attach_resp.text
    assert attach_resp.json()["forward_evidence_ref"] == payload

    get_resp = client.get(f"/api/research/hypotheses/{hypo_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["forward_evidence_ref"] == payload


def _ai_supply_chain_payload(symbol=_SYM):
    return {
        "new_capability": "推理成本下降带来企业应用调用量上升",
        "new_bottleneck": "HBM 与数据中心电力",
        "payer": "云厂商与企业客户",
        "spend_source": "AI capex 与推理预算",
        "profit_pool": "具备认证与产能约束的上游供应链",
        "pricing_gap": "市场仍按训练算力叙事定价",
        "catalysts_30d": ["云厂商 capex 指引"],
        "catalysts_90d": ["HBM 合约价"],
        "catalysts_180d": ["800G/1.6T 订单兑现"],
        "evidence_cards": [{
            "claim": "HBM 供需继续紧张",
            "source": "company_call",
            "source_date": "2026-06-01",
            "status": "needs_verification",
            "gap": "缺少交期与客户集中度数据",
            "linked_symbols": [symbol],
        }],
        "evidence_gaps": ["缺少客户订单明细"],
        "invalidation_conditions": ["云厂商下修 capex"],
        "follow_up_metrics": ["HBM contract price"],
        "beneficiary_tiers": [{"symbol": symbol, "tier": 1, "rationale": "直接受益"}],
    }


def test_hypothesis_ai_supply_chain_http_round_trip(client):
    """Template payload is visible on hypothesis and maps into existing display fields."""
    theme_id = client.post("/api/research/themes", json={"theme_name": "AI Supply Chain"}).json()["id"]

    post_resp = client.post(
        f"/api/research/themes/{theme_id}/hypotheses",
        json={
            "statement": "AI推理需求会拉动上游瓶颈资产",
            "template": "ai_supply_chain",
            "template_payload": _ai_supply_chain_payload(),
        },
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["ai_supply_chain"]["observe_only"] is True
    assert body["ai_supply_chain"]["signal_impact"] == "none"
    assert body["ai_supply_chain"]["not_a_buy_score"] is True
    assert body["beneficiary_tiers"][0]["symbol"] == _SYM
    assert "缺少交期与客户集中度数据" in body["evidence_gaps"]
    assert "云厂商下修 capex" in body["invalidation_conditions"]

    get_resp = client.get(f"/api/research/hypotheses/{body['id']}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["ai_supply_chain"]["chain"]["new_bottleneck"] == "HBM 与数据中心电力"


def test_case_view_exposes_ai_supply_chain_fields_for_symbol(client):
    """case-view should show template fields through the existing symbol tier linkage."""
    theme_id = client.post("/api/research/themes", json={"theme_name": "AI Case View"}).json()["id"]
    client.post(
        f"/api/research/themes/{theme_id}/hypotheses",
        json={
            "statement": "AI产业链瓶颈有可跟踪性",
            "template": "ai_supply_chain",
            "template_payload": _ai_supply_chain_payload(),
        },
    )

    resp = client.get(f"/api/research/{_SYM}/case-view?include_dossier=false")
    assert resp.status_code == 200, resp.text
    hypotheses = resp.json()["case_view"]["theme_hypotheses"]
    assert hypotheses
    assert hypotheses[0]["ai_supply_chain"]["catalysts"]["90d"] == ["HBM 合约价"]


def test_ai_supply_chain_case_view_is_display_only_no_signal_side_effects(client, http_db, monkeypatch):
    """Template creation + case-view must not invoke scoring or write official signal state."""
    def fail_if_called(*_, **__):
        raise AssertionError("scoring path must not be called")

    monkeypatch.setattr("backend.decision.aggregator.aggregate", fail_if_called)
    monkeypatch.setattr("backend.decision.aggregator.aggregate_v2", fail_if_called)
    monkeypatch.setattr("backend.agents.pipeline.run_pipeline", fail_if_called)
    monkeypatch.setattr("backend.decision.research_constraints.apply_research_constraints", fail_if_called)
    monkeypatch.setattr("backend.portfolio.single_position.suggest_position_pct", fail_if_called)

    theme_id = client.post("/api/research/themes", json={"theme_name": "No Signal Side Effects"}).json()["id"]
    resp = client.post(
        f"/api/research/themes/{theme_id}/hypotheses",
        json={
            "statement": "模板只用于展示",
            "template": "ai_supply_chain",
            "template_payload": _ai_supply_chain_payload(),
        },
    )
    assert resp.status_code == 200, resp.text
    case_view = client.get(f"/api/research/{_SYM}/case-view?include_dossier=false")
    assert case_view.status_code == 200, case_view.text

    from backend.data.database import DecisionRun, ResearchState, Signal

    assert http_db.query(Signal).count() == 0
    assert http_db.query(DecisionRun).count() == 0
    assert http_db.query(ResearchState).count() == 0


# ---------------------------------------------------------------------------
# Review case round-trip
# ---------------------------------------------------------------------------


def test_review_case_create_and_get_http(client):
    """POST minimal review case then GET by id — validates ReviewCaseOut serialization."""
    post_resp = client.post(
        f"/api/research/{_SYM}/review-cases",
        json={"symbol": _SYM, "as_of": "2026-01-15"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["id"]
    assert body["symbol"] == _SYM
    assert body["as_of"] == "2026-01-15"
    # review_payload defaults to None — serialization must not blow up
    assert "review_payload" in body

    rc_id = body["id"]
    get_resp = client.get(f"/api/research/review-cases/{rc_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == rc_id


def test_review_case_list_http(client):
    """GET /research/{symbol}/review-cases returns ReviewCaseListOut."""
    client.post(
        f"/api/research/{_SYM}/review-cases",
        json={"symbol": _SYM, "as_of": "2026-02-01"},
    )
    resp = client.get(f"/api/research/{_SYM}/review-cases")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "total" in body


# ---------------------------------------------------------------------------
# Memory candidate round-trip + gated promote/reject
# ---------------------------------------------------------------------------


def test_memory_candidate_create_and_get_http(client):
    """POST minimal memory candidate then GET by id — validates MemoryCandidateOut.

    memory_type must be one of the valid values in MEMORY_TYPES (e.g. 'risk', 'lesson', etc.).
    """
    post_resp = client.post(
        "/api/research/memory-candidates",
        json={"symbol": _SYM, "summary": "Strong moat in liquor", "memory_type": "risk"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["id"]
    assert body["symbol"] == _SYM
    assert body["source_trust"] == "pending"  # always pending on create

    cid = body["id"]
    get_resp = client.get(f"/api/research/memory-candidates/{cid}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == cid


def test_memory_candidate_list_http(client):
    """GET /research/memory-candidates returns MemoryCandidateListOut (not shadowed).

    Regression for the route-ordering bug where GET /research/{symbol} shadowed
    the static /research/memory-candidates list route.
    """
    client.post(
        "/api/research/memory-candidates",
        json={"symbol": _SYM, "summary": "Listed for listing test", "memory_type": "risk"},
    )
    resp = client.get("/api/research/memory-candidates")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "total" in body, f"shadowed by /research/{{symbol}}? got {list(body)}"
    assert any(c["summary"] == "Listed for listing test" for c in body["items"])


def test_promote_without_confirmed_by_rejected(client):
    """POST promote without confirmed_by must be rejected (non-200)."""
    cid = client.post(
        "/api/research/memory-candidates",
        json={"symbol": _SYM, "summary": "Promote test", "memory_type": "lesson"},
    ).json()["id"]

    # Empty confirmed_by — route does .strip() check and raises 400
    bad_resp = client.post(
        f"/api/research/memory-candidates/{cid}/promote",
        json={"confirmed_by": "   "},
    )
    assert bad_resp.status_code != 200, "promote with blank confirmed_by must not return 200"


def test_promote_with_confirmed_by_returns_trusted(client):
    """POST promote WITH valid confirmed_by must return 200 and source_trust='trusted'."""
    cid = client.post(
        "/api/research/memory-candidates",
        json={"symbol": _SYM, "summary": "Promotable lesson", "memory_type": "lesson"},
    ).json()["id"]

    promote_resp = client.post(
        f"/api/research/memory-candidates/{cid}/promote",
        json={"confirmed_by": "human-tester"},
    )
    assert promote_resp.status_code == 200, promote_resp.text
    assert promote_resp.json()["source_trust"] == "trusted"


# ---------------------------------------------------------------------------
# Universe snapshot round-trip
# ---------------------------------------------------------------------------


def test_universe_snapshot_create_and_get_http(client):
    """POST minimal snapshot then GET by id — validates UniverseSnapshotOut."""
    post_resp = client.post(
        "/api/research/universe-snapshots",
        json={"symbols": [_SYM, "300308"], "cutoff_date": "2026-01-01"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["id"]
    assert _SYM in body["symbols"]

    snap_id = body["id"]
    get_resp = client.get(f"/api/research/universe-snapshots/{snap_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == snap_id


def test_universe_snapshot_list_http(client):
    """GET /research/universe-snapshots returns UniverseSnapshotListOut (not shadowed).

    Regression for the route-ordering bug where GET /research/{symbol} shadowed
    the static /research/universe-snapshots list route.
    """
    resp = client.get("/api/research/universe-snapshots")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body and "total" in body, f"shadowed by /research/{{symbol}}? got {list(body)}"


# ---------------------------------------------------------------------------
# Forward thesis round-trip
# ---------------------------------------------------------------------------


def test_forward_thesis_create_and_get_http(client):
    """POST minimal forward thesis then GET by id — validates ForwardThesisOut."""
    post_resp = client.post(
        f"/api/research/{_SYM}/forward-theses",
        json={"statement": "Revenue to compound 20% over 3 years"},
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["id"]
    assert body["statement"] == "Revenue to compound 20% over 3 years"

    ft_id = body["id"]
    get_resp = client.get(f"/api/research/forward-theses/{ft_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == ft_id


def test_forward_thesis_list_http(client):
    """GET /research/{symbol}/forward-theses returns ForwardThesisListOut."""
    client.post(
        f"/api/research/{_SYM}/forward-theses",
        json={"statement": "Listed forward thesis"},
    )
    resp = client.get(f"/api/research/{_SYM}/forward-theses")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert "total" in body


def test_forward_thesis_ai_supply_chain_template_maps_manifest_and_metrics(client):
    """Forward thesis template input maps into pointer-only evidence and tracking fields."""
    post_resp = client.post(
        f"/api/research/{_SYM}/forward-theses",
        json={
            "statement": "AI推理瓶颈 thesis",
            "template": "ai_supply_chain",
            "template_payload": _ai_supply_chain_payload(),
        },
    )
    assert post_resp.status_code == 200, post_resp.text
    body = post_resp.json()
    assert body["evidence_manifest"][0]["kind"] == "ai_supply_chain_evidence_card"
    assert body["evidence_manifest"][0]["summary"] == "HBM 供需继续紧张"
    assert "HBM contract price" in body["follow_up_metrics"]
    assert "云厂商下修 capex" in body["invalidation_conditions"]


# ---------------------------------------------------------------------------
# Case-view aggregate endpoint
# ---------------------------------------------------------------------------


def test_case_view_returns_expected_keys(client):
    """GET /research/{symbol}/case-view?include_dossier=false returns CaseViewOut structure."""
    resp = client.get(f"/api/research/{_SYM}/case-view?include_dossier=false")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "symbol" in body
    assert "dossier" in body
    assert "case_view" in body
    assert body["symbol"] == _SYM
    # CaseViewInner keys
    case_view = body["case_view"]
    assert "theses" in case_view
    assert "review_cases" in case_view
    assert "forward_theses" in case_view
    assert "theme_hypotheses" in case_view


# ---------------------------------------------------------------------------
# Dossier route — original contract preserved
# ---------------------------------------------------------------------------


def test_dossier_returns_200_with_top_level_keys(client):
    """GET /research/{symbol}/dossier returns 200 with expected top-level keys."""
    resp = client.get(f"/api/research/{_SYM}/dossier")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # ResearchDossierOut required fields
    assert "symbol" in body
    assert "research_state" in body
    assert body["symbol"] == _SYM


def test_adapter_review_returns_readonly_phase4_contract(client, http_db):
    """GET /research/{symbol}/adapter-review returns the Phase 4 read-only adapter contract."""
    from backend.data.database import Stock

    http_db.add(Stock(symbol=_SYM, name="贵州茅台", market="CN", industry="食品饮料", active=True))
    http_db.commit()

    resp = client.get(f"/api/research/{_SYM}/adapter-review?as_of=2026-06-05")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["adapter"] == "dossier_readonly_v0"
    assert body["symbol"] == _SYM
    assert body["read_only"] is True
    assert body["research_case"]["symbol"] == _SYM
    assert body["memory_candidate_preview"]["source_trust_after_create"] == "pending"
    assert body["promotion_gate"]["auto_promotes_trusted_memory"] is False
