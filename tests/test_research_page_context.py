"""Frozen page-binding acceptance scenarios; all providers are synthetic."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import ai, research
from backend.data.database import ChatMessage, FinancialMetric, PendingAIAction, Price, get_db


@pytest.fixture
def page(test_db, monkeypatch):
    monkeypatch.delenv("MINGCANG_AGENT_MODE", raising=False)
    for symbol in ("600001", "600002"):
        test_db.add(
            Price(
                symbol=symbol,
                market="CN",
                date="2026-09-15",
                open=10,
                high=12,
                low=9,
                close=11,
                volume=1000,
                atr14=1,
                source="fixture",
                adjustment="qfq",
            )
        )
        test_db.add(
            FinancialMetric(
                symbol=symbol,
                market="CN",
                report_date="2026-06-30",
                disclosure_date="2026-08-20",
                revenue=100,
                net_profit=10,
                operating_cf=12,
                source="fixture",
            )
        )
    test_db.add(
        Price(
            symbol="600001",
            market="US",
            date="2026-09-15",
            open=999,
            high=999,
            low=999,
            close=999,
            volume=1,
            source="wrong-market",
            adjustment="none",
        )
    )
    test_db.commit()
    app = FastAPI()
    app.include_router(ai.router)
    app.include_router(research.router)
    app.dependency_overrides[get_db] = lambda: test_db
    calls = []

    class Provider:
        def complete_structured(self, **kwargs):
            calls.append(kwargs)
            source = json.loads(kwargs["prompt"])["page_evidence"]["sources"][0]["id"]
            return {
                "claims": [
                    {"text": "收盘价为 11，仍需结合后续现金流核验。", "evidence_ids": [source]}
                ]
            }

    import backend.llm

    monkeypatch.setattr(backend.llm, "has_runtime_llm_provider", lambda *_: True)
    monkeypatch.setattr(backend.llm, "get_provider", lambda: Provider())
    monkeypatch.setattr(
        ai, "_detect_action", lambda *a: pytest.fail("bound research must not parse operations")
    )
    with TestClient(app) as client:
        yield client, test_db, calls


def context(client, **kwargs):
    args = {"start": "2026-09-01", "as_of": "2026-09-15", **kwargs}
    response = client.get("/research/600001/page-context", params=args)
    assert response.status_code == 200, response.text
    return response.json()


def binding(c):
    return {**c["selection"], "context_sha256": c["context_sha256"]}


def ask(c, **kwargs):
    return {"message": "现金流如何？", "research_context": binding(c), **kwargs}


def test_same_page_sources_roundtrip_and_no_implicit_models(page):
    client, db, calls = page
    before = {
        t: db.query(t).count() for t in (Price, FinancialMetric, ChatMessage, PendingAIAction)
    }
    c = context(client)
    assert c["can_ask"] is True
    assert c == context(client)
    assert all(s["source"] != "wrong-market" for s in c["sources"])
    assert not calls
    assert before == {t: db.query(t).count() for t in before}
    result = client.post("/ai/chat", json=ask(c))
    assert result.status_code == 200, result.text
    answer = result.json()
    assert answer["research_context"] == binding(c)
    assert answer["pending_action"] is None
    seen = json.loads(calls[0]["prompt"])["page_evidence"]
    assert seen == c
    messages = client.get(f"/ai/sessions/{answer['session_id']}/messages").json()
    assert messages[0]["context_snapshot"] == c
    assert messages[1]["research_context"] == binding(c)


@pytest.mark.parametrize("change", ["symbol", "date", "range", "price", "adjustment"])
def test_changed_selection_or_data_blocks_before_model_or_record(page, change):
    client, db, calls = page
    c = context(client)
    payload = ask(c)
    if change == "symbol":
        payload["research_context"]["symbol"] = "600002"
    elif change == "date":
        payload["research_context"]["as_of"] = "2026-09-14"
    elif change == "range":
        payload["research_context"]["start"] = "2026-09-02"
    else:
        row = db.query(Price).filter(Price.market == "CN", Price.symbol == "600001").one()
        if change == "price":
            row.close = 10.5
        else:
            row.adjustment = "none"
        db.commit()
    for url in ("/ai/chat", "/ai/chat/stream"):
        assert client.post(url, json=payload).status_code == 409
    assert not calls
    assert db.query(ChatMessage).count() == 0


def test_future_financial_and_unknown_disclosure_never_enter_page(page):
    client, db, _ = page
    db.add(
        FinancialMetric(
            symbol="600001", report_date="2026-09-30", disclosure_date="2026-10-01", revenue=9999
        )
    )
    db.add(
        FinancialMetric(
            symbol="600001", report_date="2026-08-31", disclosure_date=None, revenue=8888
        )
    )
    db.commit()
    c = context(client)
    assert "9999" not in json.dumps(c) and "8888" not in json.dumps(c)
    c2 = context(client, as_of="2026-09-01")
    assert not c2["can_ask"]
    assert client.post("/ai/chat", json=ask(c2)).status_code == 422


@pytest.mark.parametrize("kind", ["missing", "stale", "mixed", "missing_source"])
def test_missing_stale_or_mixed_data_is_not_a_ready_context(page, kind):
    client, db, calls = page
    if kind == "missing":
        db.query(FinancialMetric).delete()
    elif kind == "missing_source":
        db.query(FinancialMetric).filter(FinancialMetric.symbol == "600001").one().source = None
    elif kind == "stale":
        row = db.query(FinancialMetric).filter(FinancialMetric.symbol == "600001").one()
        row.report_date = "2025-12-31"
    else:
        db.add(
            Price(
                symbol="600001",
                date="2026-09-14",
                open=10,
                high=10,
                low=10,
                close=10,
                volume=1000,
                source="other",
                adjustment="none",
            )
        )
    db.commit()
    c = context(client)
    assert c["gaps"] and not c["can_ask"]
    assert client.post("/ai/chat", json=ask(c)).status_code == 422
    assert not calls


def test_out_of_scope_question_and_unbound_model_citations_fail_closed(page, monkeypatch):
    client, db, calls = page
    c = context(client)
    assert client.post("/ai/chat", json=ask(c, message="请比较 600002")).status_code == 422
    assert not calls

    class Bad:
        def complete_structured(self, **kw):
            return {"claims": [{"text": "假的来源", "evidence_ids": ["invented-1"]}]}

    import backend.llm

    monkeypatch.setattr(backend.llm, "get_provider", lambda: Bad())
    assert client.post("/ai/chat", json=ask(c)).status_code == 502
    assert (
        db.query(ChatMessage)
        .filter(ChatMessage.role == "assistant")
        .one()
        .content.startswith("本次回答未完成")
    )


def test_stream_preserves_binding_and_never_creates_action(page):
    client, db, calls = page
    c = context(client)
    response = client.post("/ai/chat/stream", json=ask(c))
    assert response.status_code == 200
    assert "event: done" in response.text and c["context_sha256"] in response.text
    assert len(calls) == 1 and db.query(PendingAIAction).count() == 0


def test_judgment_restores_original_evidence_and_appends_observations(page):
    client, db, calls = page
    c = context(client)
    body = {
        "context": binding(c),
        "judgment": "继续观察",
        "rationale": "现金流仍需核验",
        "watch_for": "下一份公告现金流改善",
    }
    response = client.post("/research/page-reviews", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["source"] == c
    assert client.post("/research/page-reviews", json=body).json() == saved
    assert (
        client.post("/research/page-reviews", json={**body, "judgment": "覆盖旧判断"}).status_code
        == 409
    )
    row = db.query(Price).filter(Price.market == "CN", Price.symbol == "600001").one()
    row.close = 10.2
    db.commit()
    history = client.get("/research/600001/page-reviews").json()["reviews"]
    assert history[0]["source"] == c
    assert not client.get("/research/600002/page-reviews").json()["reviews"]
    outcome = {
        "expected_version": 1,
        "observation_id": "one",
        "status": "inconclusive",
        "note": "仍缺新公告",
    }
    url = f"/research/page-reviews/{saved['review_id']}/outcomes"
    updated = client.post(url, json=outcome)
    assert updated.status_code == 200
    assert updated.json()["result"]["version"] == 2
    assert client.post(url, json=outcome).json() == updated.json()
    assert client.post(url, json={**outcome, "observation_id": "two"}).status_code == 409
    assert client.post(f"/ai/actions/{saved['review_id']}/confirm").json()["status"] == "reviewed"
    assert db.query(PendingAIAction).one().executed_at is None and not calls


def test_market_and_adjustment_switch_are_explicitly_rejected(page):
    client, _, _ = page
    for params in ({"market": "US"}, {"adjustment": "qfq"}):
        assert (
            client.get(
                "/research/600001/page-context",
                params={"start": "2026-09-01", "as_of": "2026-09-15", **params},
            ).status_code
            == 422
        )
