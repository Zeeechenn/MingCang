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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A safe symbol that won't collide with literal route segments
_SYM = "600519"


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
