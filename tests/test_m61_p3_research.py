from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock


def _seed_research_context(db, symbol: str = "603986") -> datetime:
    from backend.data.database import (
        Announcement,
        CorporateEvent,
        FundFlow,
        Price,
        ResearchReport,
        Signal,
        Stock,
    )

    as_of = datetime(2026, 7, 4, 15, 0, 0)
    db.add(Stock(symbol=symbol, name="兆易创新", market="CN", industry="半导体", active=True))
    db.add(Price(symbol=symbol, date="2026-07-04", open=100, high=105, low=99, close=104, volume=1000))
    db.add(
        Signal(
            symbol=symbol,
            date="2026-07-04",
            quant_score=10,
            technical_score=15,
            sentiment_score=20,
            composite_score=45,
            recommendation="观望",
            confidence="中",
            stop_loss=90,
            take_profit=120,
            limit_status="normal",
            rule_version="aggregate_v1:new_framework",
        )
    )
    db.add(
        Announcement(
            symbol=symbol,
            title="公告：存储芯片订单更新",
            ann_type="经营合同",
            published_at=as_of - timedelta(days=1),
            provider="unit",
        )
    )
    db.add(
        ResearchReport(
            symbol=symbol,
            title="研报：存储周期上行",
            org_name="测试券商",
            rating="买入",
            eps_forecast_y1=1.6,
            eps_forecast_y2=1.9,
            publish_date=as_of - timedelta(days=2),
            provider="unit",
        )
    )
    db.add(
        CorporateEvent(
            symbol=symbol,
            event_type="产能",
            title="事件：先进产线投产",
            # PIT 语义:非排期类事件只有 event_date <= as_of 才可见(见 context_builder)
            event_date=as_of - timedelta(days=10),
            detail="新增产线进入试产。",
            provider="unit",
        )
    )
    for idx in range(5):
        db.add(
            FundFlow(
                symbol=symbol,
                trade_date=as_of - timedelta(days=4 - idx),
                main_net=float((idx + 1) * 100),
                provider="unit",
            )
        )
    db.commit()
    return as_of


def _llm_card() -> dict:
    return {
        "stance": "中性",
        "event_read": "公告与研报均显示景气改善，但仍需确认兑现。",
        "technical_read": "技术分中性。",
        "risks": ["兑现不及预期"],
        "validation_questions": ["订单能否延续？"],
        "summary_opinion": "维持影子观察，不改变官方信号。",
        "shadow_position_pct": 0.02,
        "position_note": "仅作研究观察。",
    }


def test_deep_research_m61_context_text_has_new_sections_and_no_data_markers(test_db):
    from backend.research.deep_research import _build_m61_research_context_text

    as_of = _seed_research_context(test_db)

    text = _build_m61_research_context_text(
        symbols=["603986"],
        db=test_db,
        as_of_dt=as_of,
        topic="兆易创新单股研究",
        max_chars=2000,
    )

    assert "【公告】" in text
    assert "公告：存储芯片订单更新" in text
    assert "【研报】" in text
    assert "EPS预测趋势" in text
    assert "研报：存储周期上行" in text
    assert "【公司事件】" in text
    assert "事件：先进产线投产" in text
    assert "(股东: 无数据)" in text
    assert "(龙虎榜: 无数据)" in text
    assert "【数据健康】" in text
    assert "新闻" not in text

    empty_text = _build_m61_research_context_text(
        symbols=["000001"],
        db=test_db,
        as_of_dt=as_of,
        topic="空数据单股研究",
        max_chars=1000,
    )
    assert "(公告: 无数据)" in empty_text
    assert "(研报: 无数据)" in empty_text
    assert "(公司事件: 无数据)" in empty_text


def test_copilot_prompt_adds_m61_context_but_card_schema_is_unchanged(test_db, monkeypatch):
    from backend.research import copilot

    _seed_research_context(test_db)
    monkeypatch.setattr("backend.data.context_builder.flow_floor.compute_s_flow_data", lambda raw: 0.42)
    monkeypatch.setattr(copilot, "has_runtime_llm_provider", lambda settings: True)
    captured: dict[str, str] = {}
    provider = MagicMock()

    def complete_structured(**kwargs):
        captured["prompt"] = kwargs["prompt"]
        return _llm_card()

    provider.complete_structured.side_effect = complete_structured
    monkeypatch.setattr(copilot, "get_provider", lambda: provider)

    card = copilot.generate_symbol_copilot("603986", test_db)

    prompt = captured["prompt"]
    assert prompt.startswith("ctx=m61_p3\n")
    assert "【公告】" in prompt
    assert "公告：存储芯片订单更新" in prompt
    assert "【研报】" in prompt
    assert "研报：存储周期上行" in prompt
    assert "【公司事件】" in prompt
    assert "事件：先进产线投产" in prompt
    assert "【资金流】" in prompt
    payload = json.loads(prompt.split("\n", 2)[-1])
    assert "recent_news" in payload
    assert "signals" not in payload
    assert set(_llm_card()).issubset(card.keys())
    assert card["stance"] == "中性"
    assert card["summary_opinion"] == "维持影子观察，不改变官方信号。"


def test_research_context_pack_failure_falls_back_and_emits_degradation(test_db, monkeypatch):
    from backend.research import copilot, deep_research

    _seed_research_context(test_db)
    emitted: list[dict] = []

    def boom(*args, **kwargs):
        raise RuntimeError("pack failed")

    def capture_emit(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(deep_research, "build_stock_context_pack", boom)
    monkeypatch.setattr(deep_research, "emit_degradation", capture_emit)

    deep_text = deep_research._build_m61_research_context_text(
        symbols=["603986"],
        db=test_db,
        as_of_dt=datetime(2026, 7, 4, 15, 0, 0),
        topic="半导体行业",
    )

    monkeypatch.setattr(copilot, "build_stock_context_pack", boom)
    monkeypatch.setattr(copilot, "emit_degradation", capture_emit)

    copilot_text = copilot._build_m61_copilot_context_text("603986", test_db)

    assert deep_text == ""
    assert copilot_text == ""
    assert [event["component"] for event in emitted] == ["research_layer", "research_layer"]
    assert {event["category"] for event in emitted} == {
        "deep_research_context_pack",
        "copilot_context_pack",
    }
