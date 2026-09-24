"""Frozen page-binding acceptance scenarios; all providers are synthetic."""

import json
from argparse import Namespace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import ai, research
from backend.data.database import ChatMessage, FinancialMetric, PendingAIAction, Price, get_db
from backend.research.page_context import ResearchTaskSpec, _prior_judgments


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
                fetched_at=datetime(2026, 9, 15, 10),
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


def test_page_financial_sources_share_the_strict_utc_fetch_cutoff_and_filter_before_limit(page):
    from datetime import UTC

    from backend.data.context_builder import build_stock_context_pack

    client, db, _ = page
    db.add_all([
        FinancialMetric(
            symbol="600001", market="CN", report_date="2025-06-30", disclosure_date="2025-08-20",
            revenue=80, net_profit=8, operating_cf=10, source="fixture",
            fetched_at=datetime(2026, 9, 15, 10),
        ),
        FinancialMetric(
            symbol="600001", market="CN", report_date="2026-08-31", disclosure_date="2026-09-01",
            revenue=9999, net_profit=999, operating_cf=999, source="late-fixture",
            fetched_at=datetime(2026, 9, 15, 16),
        ),
    ])
    db.commit()

    page_context = context(client)
    cutoff_cn = datetime.combine(date(2026, 9, 15), time.max, tzinfo=ZoneInfo("Asia/Shanghai"))
    direct = build_stock_context_pack(
        "600001", as_of=cutoff_cn, sections=["financials"], db=db, strict_research_inputs=True
    )["financials"]
    utc_equivalent = build_stock_context_pack(
        "600001",
        as_of=datetime(2026, 9, 15, 15, 59, 59, 999999, tzinfo=UTC),
        sections=["financials"], db=db, strict_research_inputs=True,
    )["financials"]

    financial_sources = [source for source in page_context["sources"] if source["kind"] == "financial"]
    assert {source["date"] for source in financial_sources} == {"2025-06-30", "2026-06-30"}
    assert all(source["source"] != "late-fixture" for source in financial_sources)
    assert page_context["financial_context"]["latest"] == direct["latest"]
    assert direct["latest"] == utc_equivalent["latest"]
    assert direct["piotroski"]["report_period"] == direct["latest"]["report_date"]


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
    assert len(calls) == 1
    run = db.query(PendingAIAction).one()
    assert run.action == "research.page_question" and run.status == "executed"
    assert json.loads(run.result_json)["execution"]["state"] == "completed"
    assert "event: running" in response.text and "event: evidence" in response.text


def test_prepare_is_read_only_shared_contract_and_enforces_budget(page):
    client, db, calls = page
    before = {t: db.query(t).count() for t in (ChatMessage, PendingAIAction)}
    task = {
        "symbol": "600001", "market": "CN", "start": "2026-09-01", "as_of": "2026-09-15",
        "adjustment": "stored", "question": "现金流如何？", "horizon": "medium",
        "budget_tokens": 500, "max_calls": 1,
    }
    response = client.post("/research/task/prepare", json=task)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "research_task.v1"
    assert body["task"]["budget_tokens"] == 500 and body["task"]["max_calls"] == 1
    assert body["execution"] == {"mode": "prepare_only", "model_calls": 0, "max_calls": 1, "budget_tokens": 500}
    assert not calls
    assert before == {t: db.query(t).count() for t in before}
    assert client.post("/research/task/prepare", json={**task, "budget_tokens": 901}).status_code == 422
    assert client.post("/research/task/prepare", json={**task, "max_calls": 2}).status_code == 422
    assert ResearchTaskSpec.model_validate(task).budget_tokens == 500


def test_cli_and_mcp_prepare_share_read_only_helper_and_read_guard(page, monkeypatch):
    _, db, calls = page
    task = {
        "symbol": "600001", "market": "CN", "start": "2026-09-01", "as_of": "2026-09-15",
        "adjustment": "stored", "question": "现金流如何？", "budget_tokens": 400,
    }
    from backend.agent import cli
    cli_guards = []
    monkeypatch.setattr(cli, "_read_guard", lambda args: cli_guards.append(args.command))
    monkeypatch.setattr(cli, "_with_db", lambda fn, **kwargs: fn(db))
    cli_result = cli._command_research_prepare(Namespace(command="research-prepare", api_key=None, payload_json=json.dumps(task)))
    assert cli_guards == ["research-prepare"] and cli_result["execution"]["model_calls"] == 0

    from backend.agent import mcp_server
    mcp_guards = []
    monkeypatch.setattr(mcp_server, "require_agent_access", lambda operation, api_key=None: mcp_guards.append(operation))
    monkeypatch.setattr(mcp_server, "_with_db", lambda fn: fn(db))
    mcp_result = mcp_server._research_prepare(task)
    assert mcp_guards == ["read"] and mcp_result["task"] == cli_result["task"]
    assert not calls


def test_new_prepare_and_status_routes_require_remote_read_key(page, monkeypatch):
    client, _, _ = page
    monkeypatch.setenv("MINGCANG_AGENT_MODE", "remote")
    monkeypatch.setenv("MINGCANG_AGENT_API_KEY", "read-secret")
    task = {
        "symbol": "600001", "market": "CN", "start": "2026-09-01", "as_of": "2026-09-15",
        "adjustment": "stored", "question": "现金流如何？",
    }
    assert client.post("/research/task/prepare", json=task).status_code == 401
    headers = {"x-mingcang-agent-api-key": "read-secret"}
    prepared = client.post("/research/task/prepare", json=task, headers=headers)
    assert prepared.status_code == 200
    assert client.get("/research/tasks/missing", headers=headers).status_code == 404
    assert client.get("/research/tasks/missing").status_code == 401


def test_request_id_replay_is_idempotent_and_conflicting_payload_is_rejected(page):
    client, db, calls = page
    c = context(client)
    payload = ask(c, request_id="stable_request_1")
    first = client.post("/ai/chat", json=payload)
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]
    count_after_first = db.query(ChatMessage).count()
    replay = client.post("/ai/chat", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["task_execution"]["replayed"] is True
    assert replay.json()["session_id"] == session_id
    assert len(calls) == 1 and db.query(ChatMessage).count() == count_after_first
    conflict = client.post("/ai/chat", json={**payload, "message": "现金流风险？"})
    assert conflict.status_code == 409
    assert len(calls) == 1
    status = client.get("/research/tasks/stable_request_1")
    assert status.status_code == 200
    assert status.json()["status"] == "executed" and status.json()["response"]["answer"] == first.json()["answer"]


def test_reservation_exception_is_unknown_and_never_retried(page, monkeypatch):
    client, db, calls = page
    c = context(client)

    class AmbiguousFailure:
        def complete_structured(self, **kwargs):
            calls.append(kwargs)
            raise TimeoutError("connection dropped after dispatch")

    import backend.llm
    monkeypatch.setattr(backend.llm, "get_provider", lambda: AmbiguousFailure())
    payload = ask(c, request_id="unknown_result_1")
    response = client.post("/ai/chat", json=payload)
    assert response.status_code == 503
    row = db.query(PendingAIAction).one()
    saved = json.loads(row.result_json)["execution"]
    assert row.status == "failed" and saved["remote_outcome"] == "unknown"
    assert saved["retry_allowed"] is False
    assert "provider_wire_attempts" in saved and saved["max_output_tokens"] == 900
    assert client.post("/ai/chat", json=payload).status_code == 409
    assert len(calls) == 1


def test_prior_judgments_use_source_hash_and_filter_future_outcomes(monkeypatch):
    from backend.research import page_context as module
    judgment = {
        "review_id": "r1",
        "source": {"context_sha256": "a" * 64, "selection": {"as_of": "2026-09-14"}},
        "result": {
            "recorded_at": "2026-09-14T10:00:00+08:00", "decision": {"judgment": "old view"},
            "outcomes": [
                {"recorded_at": "2026-09-14T11:00:00+08:00", "note": "known"},
                {"recorded_at": "2026-09-15T16:30:00+00:00", "note": "future in China timezone"},
                {"recorded_at": "2026-09-16T11:00:00+08:00", "note": "future"},
            ],
        },
    }
    monkeypatch.setattr(module, "page_review_history", lambda *_: {"reviews": [judgment]})
    result = _prior_judgments(None, "600001", date.fromisoformat("2026-09-15"), "b" * 64)
    assert result[0]["evidence_context_sha256"] == "a" * 64
    assert result[0]["validity"] == "historical_context_changed"
    assert [item["note"] for item in result[0]["outcomes"]] == ["known"]
    assert result[0]["not_a_fact"] is True
    assert result[0]["decision_is_excerpt"] is False


def test_judgment_restores_original_evidence_and_appends_observations(page):
    client, db, calls = page
    c = context(client)
    body = {
        "context": binding(c),
        "judgment": "继续观察",
        "rationale": "现金流仍需核验",
        "watch_for": "下一份公告现金流改善",
    }
    other = context(client, symbol="600002")
    invalid = {**body, "context": binding(other), "supporting_evidence_ids": ["invented"]}
    assert client.post("/research/page-reviews", json=invalid).status_code == 422
    response = client.post("/research/page-reviews", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["result"]["human_choice"]["choice"] == "modified"
    evidence_id = c["sources"][0]["id"]
    chosen = {**body, "choice": "accepted", "supporting_evidence_ids": [evidence_id], "uncertainties": ["需要后续财报"]}
    assert client.post("/research/page-reviews", json=chosen).status_code == 409
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
