from datetime import datetime


def test_run_deep_research_creates_report_and_decision_run(test_db, tmp_path, sample_stocks):
    from backend.data.database import NewsItem
    from backend.research.deep_research import run_deep_research

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创披露高速光模块订单增长",
        url="https://finance.eastmoney.com/a/202605171111.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        fetched_at=datetime(2026, 5, 17, 10, 5, 0),
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
        allow_external_retrieval=False,
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
    assert sections[0].catalysts == ()
    assert sections[0].stance == "证据不足"
    assert "不能据此判断行业周期" in sections[0].content
    assert sections[1].evidence_snippets
    assert sections[2].risks == ("weak_source",)
    assert sections[-1].catalysts == ()
    assert sections[-1].stance == "中性"


def test_long_term_theme_framework_marks_unsupported_dimensions_unknown():
    from backend.research.agents import build_long_term_theme_framework

    result = build_long_term_theme_framework(
        topic="白酒",
        symbols=["600519", "000858"],
        names={"600519": "贵州茅台", "000858": "五粮液"},
        financials=[{"symbol": "600519", "available": True, "report_date": "2026-06-30", "roe": 18.0}],
        source_count=2,
        weak_source_count=59,
        risk_flags=["stale_source"],
    )

    dimensions = {item["dimension"]: item for item in result["framework"]}
    assert result["coverage"]["financial_metric_coverage"] == "1/8"
    assert dimensions["产业周期"]["status"] == "unknown"
    assert dimensions["供需与竞争"]["status"] == "unknown"
    assert dimensions["成分公司财务"]["status"] == "partial"
    assert dimensions["估值"]["status"] == "unknown"
    assert "不能据此给出行业长期看多/看空判断" in result["limitations"][1]


def test_source_relevance_does_not_trust_symbol_association_alone():
    from datetime import datetime

    from backend.data.news_audit import audit_news_items
    from backend.data.news_models import RawNews
    from backend.research import deep_research

    audit = audit_news_items(
        [RawNews(
            title="白酒板块资金净流出",
            url="https://example.com/sector",
            published_at=datetime(2026, 5, 17, 10),
            source="证券时报",
            symbol="000858",
        )],
        now=datetime(2026, 5, 17, 12),
    )
    relevance = deep_research._source_relevance(
        audit, topic="五粮液", symbols=["000858"], names={"000858": "五粮液"},
    )
    evaluation = deep_research._evaluate_evidence(
        topic="五粮液",
        symbols=["000858"],
        names={"000858": "五粮液"},
        audits=audit,
        financials=[{"symbol": "000858", "available": True}],
        window_days=14,
        min_usable=1,
        theme_research=False,
    )

    assert relevance["direct_company_count"] == 0
    assert relevance["associated_without_text_match_count"] == 1
    assert evaluation.quality == "insufficient"
    assert evaluation.next_plan["action"] == "expand_news_window"


def test_company_name_in_article_body_counts_as_direct_company_evidence():
    from datetime import datetime

    from backend.data.news_audit import audit_news_items
    from backend.data.news_models import RawNews
    from backend.research import deep_research

    audit = audit_news_items(
        [RawNews(
            title="白酒行业专题",
            url="https://example.com/company",
            published_at=datetime(2026, 5, 17, 10),
            source="证券时报",
            symbol="000858",
            content="五粮液公司经营情况与渠道库存分析",
        )],
        now=datetime(2026, 5, 17, 12),
    )
    result = deep_research._source_relevance(
        audit, topic="五粮液", symbols=["000858"], names={"000858": "五粮液"},
    )

    assert result["direct_company_count"] == 1


def test_financial_snapshot_excludes_future_disclosure_and_late_fetch(test_db):
    from datetime import datetime

    from backend.data.database import FinancialMetric
    from backend.research.deep_research import _latest_financial_context

    test_db.add_all([
        FinancialMetric(
            symbol="000858", report_date="2026-06-30", disclosure_date="2026-09-25",
            fetched_at=datetime(2026, 9, 25, 10), revenue_yoy=18.0,
        ),
        FinancialMetric(
            symbol="000858", report_date="2025-12-31", disclosure_date="2026-03-15",
            fetched_at=datetime(2026, 3, 16, 10), revenue_yoy=9.0,
        ),
        FinancialMetric(
            symbol="000858", report_date="2025-09-30", disclosure_date="2026-03-01",
            fetched_at=datetime(2026, 9, 25, 10), revenue_yoy=99.0,
        ),
    ])
    test_db.commit()

    result = _latest_financial_context(test_db, "000858", as_of="2026-09-24")

    assert result["report_date"] == "2025-12-31"
    assert result["revenue_yoy"] == 9.0
    assert result["quality"] == "partial"
    assert "roe" in result["missing_fields"]


def test_price_snapshot_respects_as_of_cutoff(test_db):
    from backend.data.database import Price
    from backend.research.deep_research import _latest_price_context

    test_db.add_all([
        Price(symbol="000858", date="2026-09-23", open=10, high=11, low=9, close=10.5, volume=100),
        Price(symbol="000858", date="2026-09-25", open=12, high=13, low=11, close=12.5, volume=100),
    ])
    test_db.commit()

    result = _latest_price_context(test_db, "000858", as_of="2026-09-24")

    assert result["latest_date"] == "2026-09-23"
    assert result["latest_close"] == 10.5


def test_run_deep_research_can_force_theme_framework_for_single_member(test_db, tmp_path, sample_stocks):
    from backend.research.deep_research import run_deep_research

    report = run_deep_research(
        topic="白酒",
        symbols=["600519"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=False,
        long_term_theme=True,
    )

    text = report.path.read_text(encoding="utf-8")
    assert report.long_term_framework is not None
    assert "板块长期研究框架（证据状态）" in text
    assert "供需与竞争（unknown）" in text
    assert "不表示本次分别调用了五个独立模型" in text
    assert "Deep Research 入口不调用多轮辩论" in text


def test_run_deep_research_renders_structured_sections(test_db, tmp_path, sample_stocks):
    from backend.data.database import NewsItem
    from backend.research.deep_research import run_deep_research

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创公告订单继续增长",
        url="https://www.cninfo.com.cn/test",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="巨潮资讯",
        fetched_at=datetime(2026, 5, 17, 10, 5, 0),
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
    assert report.sections[0]["catalysts"] == []


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
    today = datetime.now().strftime("%Y-%m-%d")

    def fake_search(queries):
        assert queries == ["光模块订单兑现"]
        return [{
            "title": "中际旭创订单兑现跟踪",
            "url": "https://example.com/order",
            "snippet": "订单兑现继续推进",
            "published_date": today,
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    report = deep_research.run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of=today,
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
    today = datetime.now().strftime("%Y-%m-%d")

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
            "published_date": today,
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    report = deep_research.run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of=today,
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
    today = datetime.now().strftime("%Y-%m-%d")

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
            "published_date": today,
            "source": "tavily_web",
        }]

    monkeypatch.setattr(deep_research, "_tavily_web_search", fake_search)

    report = deep_research.run_deep_research(
        topic="AI算力产业链",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of=today,
        persist=False,
        seed_queries=["不会命中的 seed query"],
    )

    text = report.path.read_text(encoding="utf-8")
    assert len(tavily_calls) >= 2
    assert tavily_calls[0] == ["不会命中的 seed query"]
    assert tavily_calls[1] != tavily_calls[0]
    assert report.source_count == 1
    assert "[通用 Tavily 查询补到光模块证据](https://example.com/tavily-retry)" in text


# ---------------------------------------------------------------------------
# M50 Phase 1: ResearchReportGate write-before hook tests
# ---------------------------------------------------------------------------

def test_gate_blocked_does_not_write_markdown(test_db, tmp_path, sample_stocks, monkeypatch):
    """When gate blocks, the Markdown file must NOT be written."""
    from backend.config import settings
    from backend.research import deep_research

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)

    # Inject a blocking gate verdict by patching run_research_report_gate
    from backend.research.research_report_gate import GateVerdict

    def fake_gate(report, audits, text, **kwargs):
        return GateVerdict(
            status="blocked",
            reasons=["test: forced block"],
            warnings=[],
        )

    monkeypatch.setattr(
        "backend.research.research_report_gate.run_research_report_gate",
        fake_gate,
    )
    # Also patch the import inside deep_research module
    import backend.research.research_report_gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_research_report_gate", fake_gate)

    from backend.data.database import NewsItem

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创高速光模块订单",
        url="https://finance.eastmoney.com/a/gate_block_test.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="东方财富",
    ))
    test_db.commit()

    report = deep_research.run_deep_research(
        topic="Gate拦截测试",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=True,
    )

    # File must NOT exist when blocked
    assert report.path is not None
    assert not report.path.exists(), (
        f"Gate-blocked report must not be written to disk, but found: {report.path}"
    )


def test_gate_blocked_does_not_persist(test_db, tmp_path, sample_stocks, monkeypatch):
    """When gate blocks, _persist_report must NOT be called."""
    from backend.config import settings
    from backend.research import deep_research

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)

    from backend.research.research_report_gate import GateVerdict

    def fake_gate(report, audits, text, **kwargs):
        return GateVerdict(
            status="blocked",
            reasons=["test: forced block for persist check"],
            warnings=[],
        )

    import backend.research.research_report_gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_research_report_gate", fake_gate)

    persist_calls = []
    original_persist = deep_research._persist_report

    def spy_persist(db, report, audits, *, gate=None):
        persist_calls.append("called")
        return original_persist(db, report, audits, gate=gate)

    monkeypatch.setattr(deep_research, "_persist_report", spy_persist)

    from backend.data.database import NewsItem

    test_db.add(NewsItem(
        symbol="300308",
        title="Gate拦截持久化测试",
        url="https://finance.eastmoney.com/a/persist_block_test.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="东方财富",
    ))
    test_db.commit()

    deep_research.run_deep_research(
        topic="Gate持久化测试",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=True,
    )

    assert not persist_calls, "_persist_report must not be called when gate blocks"


def test_gate_warning_writes_markdown_with_annotations(
    test_db, tmp_path, sample_stocks, monkeypatch
):
    """When gate warns, the Markdown file IS written with warning annotations."""
    from backend.config import settings
    from backend.research import deep_research

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)

    from backend.research.research_report_gate import GateVerdict

    def fake_gate(report, audits, text, **kwargs):
        return GateVerdict(
            status="warning",
            reasons=[],
            warnings=["test: 来源质量偏低"],
        )

    import backend.research.research_report_gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_research_report_gate", fake_gate)

    from backend.data.database import NewsItem

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创警告测试",
        url="https://finance.eastmoney.com/a/warning_test.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="东方财富",
    ))
    test_db.commit()

    report = deep_research.run_deep_research(
        topic="Gate警告测试",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=False,
    )

    assert report.path.exists(), "Warning path: file should still be written"
    text = report.path.read_text(encoding="utf-8")
    assert "来源质量偏低" in text, "Warning annotations should appear in written file"


def test_gate_pass_preserves_original_behavior(test_db, tmp_path, sample_stocks, monkeypatch):
    """When gate passes, original behavior (write + persist) is unchanged."""
    from backend.config import settings
    from backend.data.database import NewsItem
    from backend.research import deep_research

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)

    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创高速光模块正常测试",
        url="https://finance.eastmoney.com/a/normal_test.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="东方财富",
    ))
    test_db.commit()

    report = deep_research.run_deep_research(
        topic="Gate通过测试",
        symbols=["300308"],
        db=test_db,
        output_dir=tmp_path,
        as_of="2026-05-17",
        persist=True,
    )

    # File written
    assert report.path.exists()
    text = report.path.read_text(encoding="utf-8")
    assert "Gate通过测试" in text

    # DB persisted
    from backend.decision.harness import get_decision_evidence
    evidence = get_decision_evidence(test_db, "300308")
    assert any(e["run_type"] == "deep_research" for e in evidence)


def test_gate_blocked_report_is_distinguishable_via_status(
    test_db, tmp_path, sample_stocks, monkeypatch
):
    """M50 Phase 1 收尾: blocked report carries gate_status='blocked' so callers
    can distinguish it from a normal report (path points to unwritten file)."""
    from datetime import datetime

    from backend.config import settings
    from backend.data.database import NewsItem
    from backend.research import deep_research
    from backend.research.research_report_gate import GateVerdict

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)

    def fake_gate(report, audits, text, **kwargs):
        return GateVerdict(status="blocked", reasons=["forced"], warnings=[])

    import backend.research.research_report_gate as gate_mod
    monkeypatch.setattr(gate_mod, "run_research_report_gate", fake_gate)

    test_db.add(NewsItem(
        symbol="300308", title="可区分性测试",
        url="https://finance.eastmoney.com/a/distinguish.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0), source="东方财富",
    ))
    test_db.commit()

    report = deep_research.run_deep_research(
        topic="可区分性测试", symbols=["300308"], db=test_db,
        output_dir=tmp_path, as_of="2026-05-17", persist=True,
    )
    assert report.gate_status == "blocked"
    assert report.gate_reasons == ("forced",)
    assert not report.path.exists()


# ---------------------------------------------------------------------------
# F3 / F4: timezone and upper-bound filter regression tests
# ---------------------------------------------------------------------------

def test_collect_news_upper_bound_excludes_future_items(test_db, tmp_path, sample_stocks):
    """F4: _collect_news with a past as_of must NOT include items published after as_of."""
    from backend.data.database import NewsItem
    from backend.research.deep_research import _collect_news

    as_of_str = "2026-05-10"
    as_of_dt = datetime.strptime(as_of_str, "%Y-%m-%d")

    # Add one old item (within window) and one future item (after as_of)
    test_db.add(NewsItem(
        symbol="300308",
        title="在窗口内的旧新闻",
        url="https://finance.eastmoney.com/a/old.html",
        published_at=datetime(2026, 5, 9, 10, 0, 0),
        source="东方财富",
        fetched_at=datetime(2026, 5, 9, 10, 1, 0),
    ))
    test_db.add(NewsItem(
        symbol="300308",
        title="在as_of之后的未来新闻",
        url="https://finance.eastmoney.com/a/future.html",
        published_at=datetime(2026, 5, 15, 10, 0, 0),   # > as_of 2026-05-10
        source="东方财富",
        fetched_at=datetime(2026, 5, 9, 10, 1, 0),
    ))
    test_db.commit()

    items, audits = _collect_news(
        test_db, ["300308"], as_of_dt, window_days=14
    )
    titles = [item.title for item in items]
    assert "在窗口内的旧新闻" in titles, "Old item should be included"
    assert "在as_of之后的未来新闻" not in titles, (
        "F4: item published after as_of must be excluded by upper bound filter"
    )


def test_collect_news_excludes_late_fetched_backdated_row(test_db, sample_stocks):
    from backend.data.database import NewsItem
    from backend.research.deep_research import _collect_news

    test_db.add(NewsItem(
        symbol="300308", title="回填发布日期但晚于cutoff抓取", url="https://example.com/late-fetch",
        published_at=datetime(2026, 5, 9, 10), fetched_at=datetime(2026, 5, 11, 0), source="测试",
    ))
    test_db.commit()
    items, _ = _collect_news(test_db, ["300308"], datetime(2026, 5, 10), window_days=14)
    assert all(item.title != "回填发布日期但晚于cutoff抓取" for item in items)


def test_collect_news_memory_items_also_upper_bounded(test_db, tmp_path, sample_stocks):
    """F4: memory_items passed to _collect_news are also filtered by the upper bound."""
    from backend.data.news import RawNews
    from backend.research.deep_research import _collect_news

    as_of_str = "2026-05-10"
    as_of_dt = datetime.strptime(as_of_str, "%Y-%m-%d")

    within_window = RawNews(
        title="内存旧新闻",
        url="https://example.com/old",
        published_at=datetime(2026, 5, 8, 10, 0, 0),
        source="tavily_web",
        symbol=None,
        fetched_at=datetime(2026, 5, 9, 10, 1, 0),
    )
    after_as_of = RawNews(
        title="内存未来新闻",
        url="https://example.com/future",
        published_at=datetime(2026, 5, 17, 10, 0, 0),
        source="tavily_web",
        symbol=None,
        fetched_at=datetime(2026, 5, 17, 10, 1, 0),
    )

    items, _ = _collect_news(
        test_db, [], as_of_dt, window_days=14,
        memory_items=[within_window, after_as_of],
    )
    titles = [item.title for item in items]
    assert "内存旧新闻" in titles
    assert "内存未来新闻" not in titles, (
        "F4: memory_item published after as_of must be excluded by upper bound"
    )


def test_gate_pass_sets_status_pass(test_db, tmp_path, sample_stocks, monkeypatch):
    """A passing report carries gate_status='pass'."""
    from datetime import datetime

    from backend.config import settings
    from backend.data.database import NewsItem
    from backend.research import deep_research

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)
    test_db.add(NewsItem(
        symbol="300308", title="中际旭创高速光模块正常测试",
        url="https://finance.eastmoney.com/a/status_pass.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0), source="东方财富",
    ))
    test_db.commit()

    report = deep_research.run_deep_research(
        topic="状态pass测试", symbols=["300308"], db=test_db,
        output_dir=tmp_path, as_of="2026-05-17", persist=False,
    )
    assert report.gate_status in ("pass", "warning")
    assert report.path.exists()


def test_api_endpoint_blocked_report_returns_null_path_with_gate_fields(
    test_db, tmp_path, sample_stocks, monkeypatch
):
    """F2: when gate blocks a report, the API endpoint must return report_path=None
    and expose gate_status='blocked' + gate_reasons so callers are not misled."""
    from datetime import datetime

    from backend.api.routes import run_deep_research_endpoint
    from backend.api.schemas import DeepResearchRequest
    from backend.config import settings
    from backend.data.database import NewsItem
    from backend.research.research_report_gate import GateVerdict

    monkeypatch.setattr(settings, "research_report_gate_enabled", True)
    monkeypatch.setattr("backend.research.deep_research.default_output_dir", lambda: tmp_path)

    import backend.research.research_report_gate as gate_mod

    def fake_gate(report, audits, text, **kwargs):
        return GateVerdict(status="blocked", reasons=["test-block-reason"], warnings=[])

    monkeypatch.setattr(gate_mod, "run_research_report_gate", fake_gate)

    test_db.add(NewsItem(
        symbol="603986", title="兆易创新F2测试新闻",
        url="https://finance.eastmoney.com/a/f2_test.html",
        published_at=datetime(2026, 5, 17, 10, 0, 0), source="东方财富",
    ))
    test_db.commit()

    response = run_deep_research_endpoint(
        DeepResearchRequest(topic="F2端点拦截测试", symbols=["603986"]),
        db=test_db,
    )

    assert response.gate_status == "blocked", (
        "F2: endpoint must surface gate_status='blocked' when report was blocked"
    )
    assert "test-block-reason" in response.gate_reasons, (
        "F2: gate_reasons must be forwarded to API response"
    )
    assert response.report_path is None, (
        "F2: blocked report must return report_path=None, not the unwritten file path"
    )
