from __future__ import annotations

from datetime import datetime, timedelta


def _seed_m61_context(db, symbol: str = "603986", *, fund_flow: bool = True) -> datetime:
    from backend.data.database import (
        Announcement,
        CorporateEvent,
        FinancialMetric,
        FundFlow,
        HolderSnapshot,
        LhbRecord,
        NewsItem,
        Price,
        ResearchReport,
        Stock,
    )

    as_of = datetime.now().replace(microsecond=0)
    db.add(Stock(symbol=symbol, name="兆易创新", market="CN", industry="半导体", active=True))
    start = as_of - timedelta(days=80)
    for idx in range(70):
        day = start + timedelta(days=idx)
        close = 50 + idx
        db.add(
            Price(
                symbol=symbol,
                date=day.strftime("%Y-%m-%d"),
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=1000 + idx,
                atr14=2.0,
            )
        )

    for report_date, disclosure_date, revenue_yoy, profit_yoy, roe, shares in (
        ("2025-03-31", "2025-04-30", 8.0, 10.0, 10.0, 100.0),
        ("2026-03-31", "2026-04-30", 14.0, 18.0, 13.0, 100.5),
    ):
        db.add(
            FinancialMetric(
                symbol=symbol,
                report_date=report_date,
                disclosure_date=disclosure_date,
                period_type="Q1",
                revenue=1000.0,
                revenue_yoy=revenue_yoy,
                net_profit=120.0,
                net_profit_yoy=profit_yoy,
                total_assets=2000.0,
                total_equity=1000.0,
                long_term_debt=100.0 if report_date.startswith("2026") else 140.0,
                current_ratio=1.9 if report_date.startswith("2026") else 1.6,
                operating_cf=160.0,
                gross_margin=38.0 if report_date.startswith("2026") else 34.0,
                roe=roe,
                asset_turnover=0.55 if report_date.startswith("2026") else 0.50,
            )
        )
        db.add(
            HolderSnapshot(
                symbol=symbol,
                report_date=datetime.fromisoformat(report_date),
                total_shares=shares,
                float_shares=80.0,
                holder_count=50000,
                provider="unit",
            )
        )

    db.add(
        NewsItem(
            symbol=symbol,
            title="锁单周期延长",
            url="https://example.test/news",
            published_at=as_of - timedelta(days=1),
            source="unit",
            provider="unit",
            content="供应链锁单周期延长到六个月，交期变化明显。",
        )
    )
    db.add(
        Announcement(
            symbol=symbol,
            title="年度订单公告",
            ann_type="经营合同",
            published_at=as_of - timedelta(days=2),
            provider="unit",
        )
    )
    for days_ago, eps in ((20, 1.6), (40, 1.5), (130, 1.1)):
        db.add(
            ResearchReport(
                symbol=symbol,
                title=f"半导体研报{days_ago}",
                org_name="券商",
                rating="买入",
                eps_forecast_y1=eps,
                eps_forecast_y2=eps + 0.2,
                publish_date=as_of - timedelta(days=days_ago),
                provider="unit",
            )
        )
    db.add(
        CorporateEvent(
            symbol=symbol,
            event_type="扩产",
            title="先进封装扩产",
            # PIT 语义:非排期类事件只有 event_date <= as_of 才可见(见 context_builder)
            event_date=as_of - timedelta(days=20),
            detail="新增产线进入试产。",
            provider="unit",
        )
    )
    db.add(
        LhbRecord(
            symbol=symbol,
            trade_date=as_of - timedelta(days=3),
            reason="日涨幅偏离值达7%",
            net_buy_amount=123.0,
            provider="unit",
        )
    )
    if fund_flow:
        for idx in range(10):
            db.add(
                FundFlow(
                    symbol=symbol,
                    trade_date=as_of - timedelta(days=9 - idx),
                    main_net=float((idx + 1) * 100),
                    provider="unit",
                )
            )
    db.commit()
    return as_of


def test_track_prompt_uses_context_pack_and_fixed_semantic_search(test_db, monkeypatch):
    from backend.agents.long_term import track_analyst

    _seed_m61_context(test_db)
    captured: dict[str, object] = {}

    class Provider:
        def complete_structured(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return {
                "layer3_cycle_or_structural": "结构性",
                "layer5_entry_timing": "观望",
                "score": 15,
                "label_vote": "观望",
                "key_findings": ["上下文证据已纳入"],
            }

    def fake_search(query, *, days, max_results):
        captured.setdefault("queries", []).append(query)
        return ["供应链交期拉长到 26 周"]

    monkeypatch.setattr(track_analyst.settings, "tavily_api_key", "unit-key")
    monkeypatch.setattr(track_analyst, "runtime_readiness", lambda settings: {"usable": True, "reason": "ok"})
    monkeypatch.setattr(track_analyst, "get_provider", lambda: Provider())
    monkeypatch.setattr("backend.data.news.search_titles_tavily", fake_search)

    report = track_analyst.analyze("603986", "兆易创新", test_db)

    prompt = str(captured["prompt"])
    assert report.label_vote == "观望"
    assert "【新闻】" in prompt
    assert "【公告】" in prompt
    assert "【研报】" in prompt
    assert "【公司事件】" in prompt
    assert len(report.raw["context_text"]) <= 1800
    assert any("锁单 排产 交期 涨价 供应链 具体数据" in q for q in captured["queries"])
    assert all("股票 最新消息" not in q for q in captured["queries"])


def test_quality_boom_and_flow_context_markers(test_db, monkeypatch):
    from backend.agents.long_term import jingqi_analyst, piotroski_analyst, qfii_flow_analyst
    import backend.data.context_builder as context_builder

    _seed_m61_context(test_db)
    monkeypatch.setattr(context_builder.flow_floor, "compute_s_flow_data", lambda raw: 0.31)
    monkeypatch.setattr(qfii_flow_analyst, "get_qfii_history", lambda *a, **kw: {"20260331": []})

    quality = piotroski_analyst.analyze("603986", test_db)
    boom = jingqi_analyst.analyze("603986", test_db)
    flow = qfii_flow_analyst.analyze("603986", test_db)

    assert "【财务】" in quality.raw["context_text"]
    assert "【股东】" in quality.raw["context_text"]
    assert "Piotroski" in quality.raw["context_text"]
    assert "N/A因子" in quality.raw["context_text"]
    assert "【研报】" in boom.raw["context_text"]
    assert "EPS预测趋势" in boom.raw["context_text"]
    assert "【龙虎榜】" in boom.raw["context_text"]
    assert "【价格】" in boom.raw["context_text"]
    assert "【资金流】" in flow.raw["context_text"]
    assert "S-flow 0.31" in flow.raw["context_text"]
    assert "【龙虎榜】" in flow.raw["context_text"]


def test_flow_fund_flow_absent_returns_neutral_with_no_data_marker(test_db, monkeypatch):
    from backend.agents.long_term import qfii_flow_analyst

    _seed_m61_context(test_db, fund_flow=False)
    calls = []
    monkeypatch.setattr(qfii_flow_analyst, "get_qfii_history", lambda *a, **kw: calls.append(True) or {})

    report = qfii_flow_analyst.analyze("603986", test_db)

    assert report.label_vote == "观望"
    assert report.confidence == 0.0
    assert report.raw["reason"] == "fund_flow_absent"
    assert "(资金流: 无数据)" in report.raw["context_text"]
    assert calls == []


def test_track_llm_failure_retries_then_emits_degradation(test_db, monkeypatch):
    from backend.agents.long_term import track_analyst
    from backend.data.degradation import DegradationEvent

    _seed_m61_context(test_db)

    class EmptyProvider:
        def __init__(self):
            self.calls = 0

        def complete_structured(self, **kwargs):
            self.calls += 1
            return {}

    provider = EmptyProvider()
    monkeypatch.setattr(track_analyst, "runtime_readiness", lambda settings: {"usable": True, "reason": "ok"})
    monkeypatch.setattr(track_analyst, "get_provider", lambda: provider)

    report = track_analyst.analyze("603986", "兆易创新", test_db)

    assert provider.calls == 2
    assert report.label_vote == "观望"
    assert report.confidence == 0
    event = test_db.query(DegradationEvent).filter_by(component="long_term_team").one()
    assert event.provider == "track"
    assert event.error == "llm_failed"


def test_team_result_carries_m61_prompt_version(monkeypatch, test_db):
    from backend.agents.long_term import team as team_mod
    from backend.agents.long_term.base import LongTermReport

    monkeypatch.setattr(
        team_mod.track_analyst,
        "analyze",
        lambda s, n, db: LongTermReport(role="track", score=20, confidence=0.8, label_vote="观望", key_findings=[]),
    )
    monkeypatch.setattr(
        team_mod.piotroski_analyst,
        "analyze",
        lambda s, db: LongTermReport(role="quality", score=30, confidence=0.8, label_vote="观望", key_findings=[]),
    )
    monkeypatch.setattr(
        team_mod.jingqi_analyst,
        "analyze",
        lambda s, db: LongTermReport(role="boom", score=40, confidence=0.8, label_vote="观望", key_findings=[]),
    )
    monkeypatch.setattr(
        team_mod.qfii_flow_analyst,
        "analyze",
        lambda s, db: LongTermReport(role="flow", score=0, confidence=0, label_vote="观望", key_findings=[]),
    )

    label = team_mod.LongTermTeam().run("603986", "兆易创新", test_db)

    assert label.prompt_version == "m61_p3"
    assert "prompt_version=m61_p3" in label.quality_notes
