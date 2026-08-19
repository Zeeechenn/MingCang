from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.data.database import Base
from backend.main import app


@pytest.fixture
def http_db():
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


def _run_selection() -> dict:
    envelope = {
        "schema_version": "run_envelope.v1",
        "run_id": "run-1",
        "batch_id": "m63_postmarket:2026-08-18",
        "as_of": "2026-08-18",
        "status": "complete",
        "entrypoint": "m63_postmarket",
    }
    return {
        "status": "selected",
        "as_of": "2026-08-18",
        "candidates": 1,
        "run_envelope": envelope,
    }


def _postmarket_panel() -> dict:
    return {
        "schema_version": "postmarket_panel.v1",
        "summary": {"text": "候选 1 / 持仓 1 / 风险 1"},
        "header": {"as_of": "2026-08-18"},
        "buy_candidates": {"items": [{"symbol": "300308", "reason": "score"}], "vetoed_items": []},
        "position_health": {"items": [{"symbol": "300308", "distance_to_stop_loss_pct": 8.2}]},
        "risk_warnings": {
            "concentration": {"items": []},
            "stop_loss_buffer_ranking": {"items": []},
        },
        "watchtower_followups": {"items": [{"symbol": "300308", "reason": "trigger"}]},
        "watchtower_confirm": {"items": []},
        "review_attribution": {"items": [{"symbol": "300308"}], "note": "closed positions from positions table"},
        "daily_delta": {
            "current_as_of": "2026-08-18",
            "previous_as_of": "2026-08-17",
            "summary": "候选 +1，风险不变",
            "changes": [{"field": "candidate_count", "delta": 1}],
        },
    }


def _news_event_risk() -> dict:
    return {
        "schema_version": "news_event_risk_facade.v1",
        "as_of": "2026-08-18",
        "status": "ready",
        "event_risk_cards": [{"symbol": "300308", "event_risk_level": "high"}],
        "panel_payload": {
            "total": 1,
            "attention_count": 1,
            "attention": [{"symbol": "300308", "event_risk_level": "high"}],
        },
        "direction_experiment": {
            "lifecycle": "shadow",
            "status": "blocked",
            "direction_weights_allowed": False,
        },
        "degradation_flags": [],
    }


def test_daily_panel_payload_has_all_roadmap_cards_and_run_refs() -> None:
    from backend.evidence.daily_panel import CARD_TYPES, build_daily_panel_payload

    payload = build_daily_panel_payload(
        mode="postmarket",
        as_of="2026-08-18",
        run_selection=_run_selection(),
        postmarket_panel=_postmarket_panel(),
        news_event_risk=_news_event_risk(),
        m63_report={"mode": "postmarket", "as_of": "2026-08-18", "text": "report"},
        m63_queue={"pending": [{"id": "q1", "target": "300308"}], "done": []},
        discretion_cards=[{"symbol": "300308", "slot": "candidate"}],
    )

    assert payload["schema_version"] == "daily_panel.v1"
    assert [card["card_type"] for card in payload["cards"]] == list(CARD_TYPES)
    assert payload["source_contract"]["no_synthetic_batch"] is True
    assert "event_risk" in payload["lifecycle_visibility"]["shadow"]
    assert payload["lifecycle_visibility"]["rejected"] == []
    for card in payload["cards"]:
        assert card["run_ref"]["run_id"] == "run-1"
        assert card["evidence_refs"], card["card_type"]
        assert {"lifecycle", "status", "summary", "payload", "drilldown"} <= card.keys()
    event_card = next(card for card in payload["cards"] if card["card_type"] == "event_risk")
    assert event_card["payload"]["direction_weights"]["status"] == "blocked"
    assert event_card["payload"]["direction_weights"]["lifecycle"] == "shadow"
    watchtower_card = next(card for card in payload["cards"] if card["card_type"] == "watchtower")
    assert watchtower_card["payload"]["suppression_history_status"] == "missing"


def test_daily_panel_payload_does_not_synthesize_missing_batch() -> None:
    from backend.evidence.daily_panel import build_daily_panel_payload

    payload = build_daily_panel_payload(
        mode="postmarket",
        as_of="2026-08-18",
        run_selection={"status": "missing", "job_run": None, "candidates": 0},
        postmarket_panel=None,
        news_event_risk=_news_event_risk(),
    )

    batch = payload["cards"][0]
    assert payload["status"] == "degraded"
    assert batch["card_type"] == "batch_integrity"
    assert batch["status"] == "missing"
    assert batch["run_ref"] is None
    assert batch["payload"]["no_synthetic_batch"] is True


def test_daily_panel_missing_run_with_raw_postmarket_is_unverified_not_ready() -> None:
    from backend.evidence.daily_panel import build_daily_panel_payload

    payload = build_daily_panel_payload(
        mode="postmarket",
        as_of="2026-08-18T22:00:00+08:00",
        run_selection={"status": "missing", "job_run": None, "candidates": 0},
        postmarket_panel=_postmarket_panel(),
        news_event_risk=_news_event_risk(),
    )

    assert payload["as_of"] == "2026-08-18"
    for card_type in ("candidate", "position_health", "review_attribution"):
        card = next(card for card in payload["cards"] if card["card_type"] == card_type)
        assert card["status"] == "degraded"
        assert card["run_ref"] is None
        assert card["evidence_refs"][0]["status"] == "unverified"
        assert card["evidence_refs"][0]["as_of"] == "2026-08-18"
    event = next(card for card in payload["cards"] if card["card_type"] == "event_risk")
    assert event["status"] == "degraded"
    assert event["evidence_refs"][0]["status"] == "unverified"


def test_daily_panel_delta_requires_structured_current_vs_previous() -> None:
    from backend.evidence.daily_panel import build_daily_panel_payload

    panel = _postmarket_panel()
    panel.pop("daily_delta")
    payload = build_daily_panel_payload(
        mode="postmarket",
        as_of="2026-08-18",
        run_selection=_run_selection(),
        postmarket_panel=panel,
        news_event_risk=_news_event_risk(),
        m63_report={"mode": "postmarket", "as_of": "2026-08-17", "text": "stale"},
        discretion_cards=[{"symbol": "300308", "as_of": "2026-08-17"}],
    )

    daily_delta = next(card for card in payload["cards"] if card["card_type"] == "daily_delta")
    candidate = next(card for card in payload["cards"] if card["card_type"] == "candidate")
    assert daily_delta["status"] == "missing"
    assert daily_delta["payload"]["missing_reason"] == "missing_structured_current_vs_previous_delta"
    assert daily_delta["payload"]["m63_report"]["stale"] is True
    assert candidate["payload"]["shadow_discretion_cards"][0]["stale"] is True


def test_daily_panel_queue_staleness_is_explicit() -> None:
    from backend.evidence.daily_panel import build_daily_panel_payload

    payload = build_daily_panel_payload(
        mode="postmarket",
        as_of="2026-08-18",
        run_selection=_run_selection(),
        postmarket_panel=_postmarket_panel(),
        news_event_risk=_news_event_risk(),
        m63_queue={"pending": [{"id": "old", "target": "300308", "created_at": "2026-07-05T12:00:00+08:00"}]},
    )

    card = next(card for card in payload["cards"] if card["card_type"] == "human_confirmation")
    assert card["status"] == "degraded"
    assert card["payload"]["queue_stale_count"] == 1
    assert card["payload"]["queue_status"] == "stale"
    assert card["evidence_refs"][0]["status"] == "stale"


def test_latest_daily_panel_custom_session_does_not_fall_back_to_default_db(monkeypatch, http_db) -> None:
    from backend.evidence import daily_panel

    monkeypatch.setattr(
        daily_panel,
        "build_postmarket_panel",
        lambda *args, **kwargs: pytest.fail("must not read default production DB for injected memory session"),
    )
    payload = daily_panel.build_latest_daily_panel(
        http_db,
        mode="postmarket",
        as_of="2026-08-18",
    )

    batch = payload["cards"][0]
    assert payload["status"] == "degraded"
    assert "postmarket_panel_unavailable:no_file_sqlite_path" in batch["payload"]["source_flags"]


def test_daily_panel_api_latest_is_single_readonly_entrypoint(monkeypatch) -> None:
    from backend.api.routes import daily

    expected = {
        "schema_version": "daily_panel.v1",
        "mode": "postmarket",
        "as_of": "2026-08-18",
        "generated_at": "2026-08-18T16:00:00Z",
        "status": "ready",
        "cards": [
            {
                "card_type": card_type,
                "lifecycle": "stable",
                "status": "ready",
                "summary": card_type,
                "payload": {},
                "evidence_refs": [{"source_type": "test", "source_ref": card_type}],
                "run_ref": {"run_id": "run-1"},
                "drilldown": {"kind": "route", "href": "/daily", "label": "daily"},
            }
            for card_type in (
                "batch_integrity",
                "candidate",
                "position_health",
                "event_risk",
                "watchtower",
                "daily_delta",
                "human_confirmation",
                "review_attribution",
            )
        ],
        "lifecycle_visibility": {"stable": [], "shadow": [], "dormant": [], "rejected": []},
        "source_contract": {"read_only": True, "no_synthetic_batch": True},
    }

    monkeypatch.setattr(daily, "build_latest_daily_panel", lambda *args, **kwargs: expected)
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/api/daily/panel/latest?mode=postmarket")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "daily_panel.v1"
    assert len(body["cards"]) == 8


@pytest.mark.parametrize("mode", ["premarket", "intraday", "weekly"])
def test_daily_panel_api_rejects_noncanonical_modes(mode: str) -> None:
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get(f"/api/daily/panel/latest?mode={mode}")
    assert response.status_code == 422


def test_close_confirmed_reads_prices_for_the_panel_trade_date(test_db) -> None:
    """A panel built before the day's prices land must say so, not stay silent."""
    from backend.data.database import Price
    from backend.evidence.daily_panel import _close_confirmed_for

    assert _close_confirmed_for(test_db, "2026-08-19") is False

    test_db.add(Price(
        symbol="600519", market="CN", date="2026-08-19",
        open=10.0, high=10.5, low=9.8, close=10.0, volume=1000,
    ))
    test_db.commit()

    assert _close_confirmed_for(test_db, "2026-08-19") is True
    assert _close_confirmed_for(test_db, "2026-08-20") is False
