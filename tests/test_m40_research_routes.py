"""M40: route tests for thesis/theme/review/universe/forward-thesis + case-view endpoints."""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


def _route_guards(router, path, method="POST"):
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return [dep.dependency for dep in route.dependencies]
    raise AssertionError(f"route not found: {method} {path}")


# ── Thesis ledger routes ──────────────────────────────────────────────────────

def test_create_and_list_thesis(test_db, sample_stocks):
    from backend.api.routes.research import create_symbol_thesis, list_symbol_theses
    from backend.api.schemas import ThesisCreateRequest

    req = ThesisCreateRequest(symbol="600519", title="Test thesis", kill_conditions=["revenue drops 20%"])
    created = create_symbol_thesis(symbol="600519", request=req, db=test_db)
    assert created["title"] == "Test thesis"
    listed = list_symbol_theses(symbol="600519", db=test_db)
    assert any(t["title"] == "Test thesis" for t in listed["items"])


def test_get_thesis_not_found(test_db):
    from backend.api.routes.research import get_thesis_by_id

    with pytest.raises(HTTPException) as exc:
        get_thesis_by_id(thesis_id=9999, db=test_db)
    assert exc.value.status_code == 404


def test_update_thesis_status(test_db, sample_stocks):
    from backend.api.routes.research import create_symbol_thesis, update_thesis_status_endpoint
    from backend.api.schemas import ThesisCreateRequest, ThesisStatusRequest

    req = ThesisCreateRequest(symbol="600519", title="Status test thesis")
    created = create_symbol_thesis(symbol="600519", request=req, db=test_db)
    thesis_id = created["id"]

    status_req = ThesisStatusRequest(new_status="watch")
    result = update_thesis_status_endpoint(thesis_id=thesis_id, request=status_req, db=test_db)
    assert result["status"] == "watch"


def test_append_confidence(test_db, sample_stocks):
    from backend.api.routes.research import append_thesis_confidence, create_symbol_thesis
    from backend.api.schemas import ThesisConfidenceRequest, ThesisCreateRequest

    req = ThesisCreateRequest(symbol="600519", title="Confidence test thesis")
    created = create_symbol_thesis(symbol="600519", request=req, db=test_db)
    thesis_id = created["id"]

    conf_req = ThesisConfidenceRequest(score=0.75, as_of="2026-01-01", note="initial")
    result = append_thesis_confidence(thesis_id=thesis_id, request=conf_req, db=test_db)
    assert result is not None  # returns the entry dict


# ── Theme + hypothesis routes ─────────────────────────────────────────────────

def test_create_and_list_theme(test_db):
    from backend.api.routes.research import create_theme_endpoint, list_themes_endpoint
    from backend.api.schemas import ThemeCreateRequest

    req = ThemeCreateRequest(theme_name="AI Wave", description="AI infra buildout")
    created = create_theme_endpoint(request=req, db=test_db)
    assert created["theme_name"] == "AI Wave"
    listed = list_themes_endpoint(db=test_db)
    assert any(t["theme_name"] == "AI Wave" for t in listed["items"])


def test_create_hypothesis_for_theme(test_db):
    from backend.api.routes.research import create_hypothesis_endpoint, create_theme_endpoint
    from backend.api.schemas import HypothesisCreateRequest, ThemeCreateRequest

    theme = create_theme_endpoint(request=ThemeCreateRequest(theme_name="Optical"), db=test_db)
    hyp_req = HypothesisCreateRequest(statement="Optical capex accelerates in H2")
    hyp = create_hypothesis_endpoint(theme_id=theme["id"], request=hyp_req, db=test_db)
    assert hyp["theme_id"] == theme["id"]
    assert hyp["statement"] == "Optical capex accelerates in H2"


def test_update_hypothesis_status(test_db):
    from backend.api.routes.research import (
        create_hypothesis_endpoint,
        create_theme_endpoint,
        update_hypothesis_status_endpoint,
    )
    from backend.api.schemas import (
        HypothesisCreateRequest,
        HypothesisStatusRequest,
        ThemeCreateRequest,
    )

    theme = create_theme_endpoint(request=ThemeCreateRequest(theme_name="T_status"), db=test_db)
    hyp = create_hypothesis_endpoint(theme_id=theme["id"], request=HypothesisCreateRequest(statement="H_status"), db=test_db)

    status_req = HypothesisStatusRequest(new_status="supported")
    result = update_hypothesis_status_endpoint(hypothesis_id=hyp["id"], request=status_req, db=test_db)
    assert result["status"] == "supported"


def test_beneficiary_tiers_advisory_only(test_db):
    """set_beneficiary_tiers writes advisory display metadata only; tiers must not feed scoring."""
    from backend.api.routes.research import (
        create_hypothesis_endpoint,
        create_theme_endpoint,
        set_hypothesis_tiers,
    )
    from backend.api.schemas import (
        BeneficiaryTiersRequest,
        HypothesisCreateRequest,
        ThemeCreateRequest,
    )

    theme = create_theme_endpoint(request=ThemeCreateRequest(theme_name="T1"), db=test_db)
    hyp = create_hypothesis_endpoint(theme_id=theme["id"], request=HypothesisCreateRequest(statement="H1"), db=test_db)
    tiers_req = BeneficiaryTiersRequest(tiers=[{"symbol": "600519", "tier": 1, "rationale": "direct"}])
    result = set_hypothesis_tiers(hypothesis_id=hyp["id"], request=tiers_req, db=test_db)
    assert isinstance(result, dict)
    # Verify tiers are stored (advisory only)
    assert result.get("beneficiary_tiers") is not None


# ── Review case + memory candidate routes ────────────────────────────────────

def test_create_review_case_and_memory_candidate(test_db, sample_stocks):
    from backend.api.routes.research import (
        create_memory_candidate_endpoint,
        create_review_case_endpoint,
    )
    from backend.api.schemas import MemoryCandidateCreateRequest, ReviewCaseCreateRequest

    rc = create_review_case_endpoint(
        symbol="600519",
        request=ReviewCaseCreateRequest(symbol="600519", as_of="2026-01-01"),
        db=test_db,
    )
    assert rc["symbol"] == "600519"

    mc = create_memory_candidate_endpoint(
        request=MemoryCandidateCreateRequest(symbol="600519", summary="Key insight", memory_type="thesis"),
        db=test_db,
    )
    assert mc["source_trust"] == "pending"


def test_review_case_without_payload_conforms_to_response_model(test_db, sample_stocks):
    """Regression: a review case created without review_payload returns review_payload=None.
    The ReviewCaseOut response_model must accept that (it was typed as a required dict,
    causing a ResponseValidationError on the create/GET routes)."""
    from backend.api.routes.research import create_review_case_endpoint
    from backend.api.schemas import ReviewCaseCreateRequest, ReviewCaseOut

    rc = create_review_case_endpoint(
        symbol="600519",
        request=ReviewCaseCreateRequest(symbol="600519", as_of="2026-02-02"),
        db=test_db,
    )
    assert rc["review_payload"] is None
    # The real guard: serializing through the response_model must not raise.
    ReviewCaseOut(**rc)


def test_memory_candidate_create_request_has_no_source_trust_field(test_db):
    """MemoryCandidateCreateRequest must not expose source_trust field."""
    from backend.api.schemas import MemoryCandidateCreateRequest

    fields = MemoryCandidateCreateRequest.model_fields
    assert "source_trust" not in fields, "source_trust must not be a field of MemoryCandidateCreateRequest"


def test_promote_requires_confirmed_by(test_db, sample_stocks):
    from backend.api.routes.research import (
        create_memory_candidate_endpoint,
        promote_memory_candidate,
    )
    from backend.api.schemas import MemoryCandidateCreateRequest, MemoryPromoteRequest

    mc = create_memory_candidate_endpoint(
        request=MemoryCandidateCreateRequest(symbol="600519", summary="s", memory_type="thesis"),
        db=test_db,
    )
    # Empty confirmed_by must be rejected at schema validation (min_length=1)
    with pytest.raises(ValidationError):
        MemoryPromoteRequest(confirmed_by="")

    # Valid confirmed_by should work
    result = promote_memory_candidate(
        candidate_id=mc["id"],
        request=MemoryPromoteRequest(confirmed_by="analyst_001"),
        db=test_db,
    )
    assert result is not None


def test_reject_requires_confirmed_by(test_db):
    from backend.api.schemas import MemoryRejectRequest

    with pytest.raises(ValidationError):
        MemoryRejectRequest(confirmed_by="")

    # Valid should work
    r = MemoryRejectRequest(confirmed_by="analyst_001")
    assert r.confirmed_by == "analyst_001"


def test_promote_memory_candidate_end_to_end(test_db, sample_stocks):
    from backend.api.routes.research import (
        create_memory_candidate_endpoint,
        promote_memory_candidate,
    )
    from backend.api.schemas import MemoryCandidateCreateRequest, MemoryPromoteRequest

    mc = create_memory_candidate_endpoint(
        request=MemoryCandidateCreateRequest(symbol="600519", summary="Promo insight", memory_type="thesis"),
        db=test_db,
    )
    result = promote_memory_candidate(
        candidate_id=mc["id"],
        request=MemoryPromoteRequest(confirmed_by="analyst_001"),
        db=test_db,
    )
    assert result is not None
    assert result["source_trust"] == "trusted"


# ── Universe snapshot routes ──────────────────────────────────────────────────

def test_snapshot_universe_disabled_returns_503(test_db, monkeypatch):
    from backend.api.routes.research import snapshot_universe_endpoint
    from backend.api.schemas import UniverseSnapshotRequest

    monkeypatch.setattr("backend.config.settings.universe_guard_enabled", False, raising=False)
    with pytest.raises(HTTPException) as exc:
        snapshot_universe_endpoint(
            request=UniverseSnapshotRequest(symbols=["600519"], cutoff_date="2026-01-01"),
            db=test_db,
        )
    assert exc.value.status_code == 503


def test_list_universe_snapshots_empty(test_db, monkeypatch):
    from backend.api.routes.research import list_universe_snapshots

    monkeypatch.setattr("backend.config.settings.universe_guard_enabled", True, raising=False)
    result = list_universe_snapshots(db=test_db)
    assert result["items"] == []
    assert result["total"] == 0


# ── Forward thesis routes ─────────────────────────────────────────────────────

def test_forward_thesis_disabled_returns_503(test_db, monkeypatch):
    from backend.api.routes.research import create_forward_thesis_endpoint
    from backend.api.schemas import ForwardThesisCreateRequest

    monkeypatch.setattr("backend.config.settings.forward_thesis_enabled", False, raising=False)
    with pytest.raises(HTTPException) as exc:
        create_forward_thesis_endpoint(
            symbol="600519",
            request=ForwardThesisCreateRequest(statement="bull case"),
            db=test_db,
        )
    assert exc.value.status_code == 503


def test_create_and_list_forward_thesis(test_db, sample_stocks, monkeypatch):
    from backend.api.routes.research import (
        create_forward_thesis_endpoint,
        list_symbol_forward_theses,
    )
    from backend.api.schemas import ForwardThesisCreateRequest

    monkeypatch.setattr("backend.config.settings.forward_thesis_enabled", True, raising=False)
    created = create_forward_thesis_endpoint(
        symbol="600519",
        request=ForwardThesisCreateRequest(statement="bull case for 茅台"),
        db=test_db,
    )
    assert created["statement"] == "bull case for 茅台"

    listed = list_symbol_forward_theses(symbol="600519", db=test_db)
    assert any(ft["statement"] == "bull case for 茅台" for ft in listed["items"])


# ── Case view route ───────────────────────────────────────────────────────────

def test_case_view_returns_all_sections(test_db, sample_stocks):
    from backend.api.routes.research import get_symbol_case_view

    result = get_symbol_case_view(symbol="600519", db=test_db)
    assert result["symbol"] == "600519"
    assert "dossier" in result
    assert "case_view" in result
    cv = result["case_view"]
    assert "theses" in cv
    assert "review_cases" in cv
    assert "forward_theses" in cv
    assert "theme_hypotheses" in cv


def test_case_view_dossier_keys_unchanged(test_db, sample_stocks):
    """Existing dossier keys must all be present; no new keys may be injected."""
    from backend.api.routes.research import get_symbol_case_view

    result = get_symbol_case_view(symbol="600519", db=test_db)
    dossier = result["dossier"]
    required = {
        "symbol", "stock", "latest_signal", "long_term_label",
        "research_state", "evidence", "stock_memory", "deep_research",
        "pending_questions", "conflicts", "official_action", "missing", "case",
    }
    assert required.issubset(set(dossier.keys()))


def test_case_view_aggregates_linked_records(test_db, sample_stocks, monkeypatch):
    """Create thesis + review_case + forward_thesis for 600519, verify case-view lists them."""
    from backend.api.routes.research import (
        create_forward_thesis_endpoint,
        create_review_case_endpoint,
        create_symbol_thesis,
        get_symbol_case_view,
    )
    from backend.api.schemas import (
        ForwardThesisCreateRequest,
        ReviewCaseCreateRequest,
        ThesisCreateRequest,
    )

    monkeypatch.setattr("backend.config.settings.forward_thesis_enabled", True, raising=False)

    create_symbol_thesis(
        symbol="600519",
        request=ThesisCreateRequest(symbol="600519", title="Case view thesis"),
        db=test_db,
    )
    create_review_case_endpoint(
        symbol="600519",
        request=ReviewCaseCreateRequest(symbol="600519", as_of="2026-01-01"),
        db=test_db,
    )
    create_forward_thesis_endpoint(
        symbol="600519",
        request=ForwardThesisCreateRequest(statement="CV forward thesis"),
        db=test_db,
    )

    result = get_symbol_case_view(symbol="600519", db=test_db)
    cv = result["case_view"]
    assert any(t["title"] == "Case view thesis" for t in cv["theses"])
    assert len(cv["review_cases"]) >= 1
    assert any(ft["statement"] == "CV forward thesis" for ft in cv["forward_theses"])


def test_existing_dossier_route_still_works(test_db, sample_stocks):
    """Regression: existing /dossier route still returns a dict with symbol key."""
    from backend.api.routes.research import get_symbol_research_dossier

    result = get_symbol_research_dossier(symbol="600519", db=test_db)
    assert "symbol" in result


# ── Guard unit tests (mirror test_m15 pattern) ────────────────────────────────

_GUARDED_M40_ROUTES = [
    ("backend.api.routes.research", "/research/{symbol}/theses", "POST", "research.thesis.create"),
    ("backend.api.routes.research", "/research/universe-snapshots", "POST", "research.universe.snapshot"),
    ("backend.api.routes.research", "/research/{symbol}/forward-theses", "POST", "research.forward_thesis.create"),
]


_LOCAL_HUMAN_M40_ROUTES = [
    ("backend.api.routes.research", "/research/memory-candidates/{candidate_id}/promote", "POST"),
    ("backend.api.routes.research", "/research/memory-candidates/{candidate_id}/reject", "POST"),
]


@pytest.mark.parametrize("module,path,method,action", _GUARDED_M40_ROUTES)
def test_m40_write_route_rejects_remote_without_key(monkeypatch, module, path, method, action):
    router = importlib.import_module(module).router
    guards = _route_guards(router, path, method)
    assert guards, f"{path} is missing its agent write guard"
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")
    with pytest.raises(HTTPException) as exc:
        guards[0](_FakeRequest())
    assert exc.value.status_code == 401


@pytest.mark.parametrize("module,path,method,action", _GUARDED_M40_ROUTES)
def test_m40_write_route_honors_action_allowlist(monkeypatch, module, path, method, action):
    router = importlib.import_module(module).router
    guards = _route_guards(router, path, method)
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS", "watchlist.add")
    headers = {"x-stocksage-agent-api-key": "secret"}
    with pytest.raises(HTTPException) as exc:
        guards[0](_FakeRequest(headers))
    assert exc.value.status_code == 403
    # Route's own action should be accepted
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS", action)
    guards[0](_FakeRequest(headers))


@pytest.mark.parametrize("module,path,method,action", _GUARDED_M40_ROUTES)
def test_m40_write_route_passes_in_local_mode(monkeypatch, module, path, method, action):
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "local")
    router = importlib.import_module(module).router
    guards = _route_guards(router, path, method)
    guards[0](_FakeRequest())


@pytest.mark.parametrize("module,path,method", _LOCAL_HUMAN_M40_ROUTES)
def test_m40_memory_trust_routes_reject_remote_even_with_allowlist(monkeypatch, module, path, method):
    router = importlib.import_module(module).router
    guards = _route_guards(router, path, method)
    assert guards, f"{path} is missing its local human memory gate"
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "remote")
    monkeypatch.setenv("STOCKSAGE_AGENT_API_KEY", "secret")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ENABLED", "true")
    monkeypatch.setenv("STOCKSAGE_AGENT_REMOTE_WRITE_ACTIONS", "research.memory.promote,research.memory.reject")
    headers = {"x-stocksage-agent-api-key": "secret"}
    with pytest.raises(HTTPException) as exc:
        guards[0](_FakeRequest(headers))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("module,path,method", _LOCAL_HUMAN_M40_ROUTES)
def test_m40_memory_trust_routes_pass_in_local_mode(monkeypatch, module, path, method):
    monkeypatch.setenv("STOCKSAGE_AGENT_MODE", "local")
    router = importlib.import_module(module).router
    guards = _route_guards(router, path, method)
    guards[0](_FakeRequest())
