from datetime import datetime


def test_run_deep_research_creates_report_and_decision_run(test_db, tmp_path, sample_stocks):
    from backend.data.database import NewsItem
    from backend.research.deep_research import run_deep_research

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创披露高速光模块订单增长",
        url="https://finance.eastmoney.com/a/202605171111.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="东方财富",
    ))
    test_db.commit()

    report = run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=True,
    )

    assert report.topic == "AI算力产业链"
    assert report.path is not None
    assert report.path.exists()
    text = report.path.read_text(encoding="utf-8")
    assert "AI算力产业链" in text
    assert "来源审计" in text
    assert "不构成投资建议" in text

    from backend.decision.harness import get_decision_evidence

    evidence = get_decision_evidence(test_db, "300308")
    assert evidence[0]["run_type"] == "deep_research"
    assert evidence[0]["input_snapshot"]["topic"] == "AI算力产业链"


def test_run_deep_research_does_not_create_daily_signal(test_db, tmp_path, sample_stocks):
    from backend.data.database import Signal
    from backend.research.deep_research import run_deep_research

    run_deep_research(
        topic="黄金行业专题",
        symbols=["600519"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=True,
    )

    assert test_db.query(Signal).count() == 0


def test_remember_deep_research_stores_structured_research_memory(test_db):
    from backend.memory.ai_memory import recall
    from backend.memory.research_memory import remember_deep_research

    remember_deep_research(
        test_db,
        topic="AI算力产业链",
        summary="光模块景气度高，但估值和拥挤度是主要风险。",
        symbols=["300308", "300394"],
        report_path="docs/research/2026-05-17-ai.md",
    )

    raw = recall(test_db, "deep_research:AI算力产业链", scope="research")

    assert raw is not None
    assert "300308" in raw
    assert "光模块景气度高" in raw


def test_deep_research_api_runs_synchronously(test_db, tmp_path, monkeypatch, sample_stocks):
    from backend.api.routes import run_deep_research_endpoint
    from backend.api.schemas import DeepResearchRequest

    monkeypatch.setattr("backend.research.deep_research.default_output_dir", lambda: tmp_path)

    response = run_deep_research_endpoint(
        DeepResearchRequest(topic="半导体国产替代", symbols=["603986"]),
        db=test_db,
    )

    assert response.topic == "半导体国产替代"
    assert response.symbols == ["603986"]
    assert response.report_path


def test_deep_research_agent_templates_return_named_sections():
    from backend.research.agents import build_research_sections

    sections = build_research_sections(
        topic="AI算力产业链",
        symbols=["300308"],
        names={"300308": "中际旭创"},
        prices=[{"symbol": "300308", "available": True, "change_20d": 12.5}],
        financials=[{"symbol": "300308", "available": False}],
        source_count=2,
        weak_source_count=1,
        risk_flags=["weak_source"],
    )

    assert [s.role for s in sections] == [
        "sector_researcher",
        "company_researcher",
        "risk_reviewer",
        "source_auditor",
        "research_writer",
    ]
    assert "AI算力产业链" in sections[0].content
    assert "weak_source" in sections[2].content
    assert sections[0].catalysts
    assert sections[1].evidence_snippets
    assert sections[2].risks == ("weak_source",)


def test_run_deep_research_renders_structured_sections(test_db, tmp_path, sample_stocks):
    from backend.data.database import NewsItem
    from backend.research.deep_research import run_deep_research

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创公告订单继续增长",
        url="https://www.cninfo.com.cn/test",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="巨潮资讯",
    ))
    test_db.commit()

    report = run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=True,
    )

    text = report.path.read_text(encoding="utf-8")
    assert "结构化 IC Memo" in text
    assert "催化剂" in text
    assert report.sections
    assert report.sections[0]["catalysts"]


def test_execute_plan_web_search_uses_tavily_memory_only(monkeypatch):
    from backend.research import deep_research

    captured = {}

    def fake_search(queries):
        captured["queries"] = queries
        return [{
            "title": "光模块订单更新",
            "url": "https://example.com/news",
            "snippet": "订单兑现继续推进",
            "published_date": "2026-05-17",
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    result = deep_research._execute_plan(
        {"action": "web_search", "search_queries": ["光模块 订单"]},
        db=None,
        symbols=["300308"],
        topic="AI算力",
    )

    assert captured["queries"] == ["光模块 订单"]
    assert result["provider"] == "tavily_web"
    assert result["fetched"] == 1
    assert result["results"][0]["url"] == "https://example.com/news"


def test_run_deep_research_seed_queries_inject_tavily_evidence(
    test_db,
    tmp_path,
    sample_stocks,
    monkeypatch,
):
    from backend.research import deep_research

    def fake_search(queries):
        assert queries == ["光模块订单兑现"]
        return [{
            "title": "中际旭创订单兑现跟踪",
            "url": "https://example.com/order",
            "snippet": "订单兑现继续推进",
            "published_date": "2026-05-17",
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    report = deep_research.run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=False,
        seed_queries=["光模块订单兑现"],
        min_usable_sources=1,
    )

    text = report.path.read_text(encoding="utf-8")
    assert report.source_count == 1
    assert "tavily_web" in text
    assert "[中际旭创订单兑现跟踪](https://example.com/order)" in text


def test_run_deep_research_counts_tavily_found_on_final_default_iteration(
    test_db,
    tmp_path,
    sample_stocks,
    monkeypatch,
):
    from backend.config import settings
    from backend.research import deep_research

    monkeypatch.setattr(settings, "anspire_api_key", "unit-anspire")
    monkeypatch.setattr(settings, "tavily_api_key", "unit-tavily")
    monkeypatch.setattr(
        "backend.data.news.fetch_stock_news_anspire",
        lambda *args, **kwargs: [],
    )

    tavily_calls = []

    def fake_search(queries):
        tavily_calls.append(queries)
        return [{
            "title": "中际旭创发布高速光模块订单进展",
            "url": "https://example.com/tavily-final",
            "snippet": "高速光模块订单仍在兑现。",
            "published_date": "2026-05-17",
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    report = deep_research.run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=False,
    )

    text = report.path.read_text(encoding="utf-8")
    assert tavily_calls
    assert report.source_count == 1
    assert "tavily_web" in text
    assert "[中际旭创发布高速光模块订单进展](https://example.com/tavily-final)" in text


def test_run_deep_research_retries_tavily_after_empty_seed_queries(
    test_db,
    tmp_path,
    sample_stocks,
    monkeypatch,
):
    from backend.config import settings
    from backend.research import deep_research

    monkeypatch.setattr(settings, "anspire_api_key", "")
    monkeypatch.setattr(settings, "tavily_api_key", "unit-tavily")

    def fake_backfill(*args, **kwargs):
        return {"action": "backfill_financials", "synced": 0, "errors": []}

    monkeypatch.setattr(
        deep_research,
        "_backfill_financials",
        fake_backfill,
    )

    tavily_calls = []

    def fake_search(queries):
        tavily_calls.append(queries)
        if len(tavily_calls) == 1:
            return []
        return [{
            "title": "通用 Tavily 查询补到光模块证据",
            "url": "https://example.com/tavily-retry",
            "snippet": "通用查询补到可追溯来源。",
            "published_date": "2026-05-17",
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    report = deep_research.run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=False,
        seed_queries=["不会命中的 seed query"],
    )

    text = report.path.read_text(encoding="utf-8")
    assert len(tavily_calls) >= 2
    assert tavily_calls[0] == ["不会命中的 seed query"]
    assert tavily_calls[1] != tavily_calls[0]
    assert report.source_count == 1
    assert "[通用 Tavily 查询补到光模块证据](https://example.com/tavily-retry)" in text
