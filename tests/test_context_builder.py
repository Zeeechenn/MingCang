from __future__ import annotations

from datetime import datetime, timedelta

import pytest


def _seed_context_rows(db, symbol: str = "603986") -> datetime:
    from backend.data.database import (
        Announcement,
        CorporateEvent,
        FinancialMetric,
        FundFlow,
        HolderSnapshot,
        LhbRecord,
        LongTermLabel,
        NewsItem,
        Price,
        ResearchReport,
    )

    as_of = datetime(2026, 7, 4, 15, 0, 0)
    start = as_of - timedelta(days=70)
    for idx in range(70):
        day = start + timedelta(days=idx)
        close = 100 + idx
        db.add(
            Price(
                symbol=symbol,
                date=day.strftime("%Y-%m-%d"),
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=1000 + idx,
                atr14=2.5,
            )
        )

    for report_date, revenue_yoy, profit_yoy, total_shares in (
        ("2025-03-31", 8.0, 10.0, 100.0),
        ("2026-03-31", 12.0, 15.0, 101.0),
    ):
        db.add(
            FinancialMetric(
                symbol=symbol,
                report_date=report_date,
                disclosure_date="2026-04-30" if report_date.startswith("2026") else "2025-04-30",
                period_type="Q1",
                revenue=1000.0,
                revenue_yoy=revenue_yoy,
                net_profit=120.0,
                net_profit_yoy=profit_yoy,
                total_assets=2000.0,
                total_equity=1000.0,
                long_term_debt=100.0,
                current_ratio=1.8,
                operating_cf=150.0,
                gross_margin=35.0,
                roe=12.0,
                asset_turnover=0.5,
            )
        )
        db.add(
            HolderSnapshot(
                symbol=symbol,
                report_date=datetime.fromisoformat(report_date),
                total_shares=total_shares,
                float_shares=80.0,
                holder_count=50000,
                provider="unit",
            )
        )

    db.add(
        NewsItem(
            symbol=symbol,
            title="新闻标题",
            url=f"https://example.test/{symbol}/news",
            published_at=as_of - timedelta(days=1),
            source="unit",
            provider="unit",
            content="正文" * 100,
        )
    )
    db.add(
        Announcement(
            symbol=symbol,
            title="公告标题",
            ann_type="定期报告",
            published_at=as_of - timedelta(days=2),
            provider="unit",
        )
    )
    for days_ago, eps in ((20, 1.4), (40, 1.2), (120, 1.0)):
        db.add(
            ResearchReport(
                symbol=symbol,
                title=f"研报{days_ago}",
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
            event_type="限售解禁",
            title="未来解禁",
            event_date=as_of + timedelta(days=30),
            detail="测试事件",
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
    for idx in range(30):
        db.add(
            FundFlow(
                symbol=symbol,
                trade_date=as_of - timedelta(days=29 - idx),
                main_net=float((idx + 1) * 100),
                provider="unit",
            )
        )
    db.add(
        LongTermLabel(
            symbol=symbol,
            date="2026-07-03",
            label="观望",
            score=12.0,
            expires_at="2026-07-13",
        )
    )
    db.commit()
    return as_of


def test_build_stock_context_pack_full_pack_has_all_sections(test_db, monkeypatch):
    import backend.data.context_builder as context_builder

    as_of = _seed_context_rows(test_db)
    monkeypatch.setattr(context_builder.flow_floor, "compute_s_flow_data", lambda raw: 0.25)

    pack = context_builder.build_stock_context_pack("603986", as_of=as_of, db=test_db)

    assert set(context_builder.SECTION_ORDER).issubset(pack.keys())
    assert pack["price"]["last_close"] == 169
    assert pack["financials"]["latest"]["roe"] == 12.0
    assert pack["financials"]["piotroski"]["score_denominator"] == 9
    assert pack["news"]["items"][0]["content_preview"] == "正文" * 60
    assert pack["research_reports"]["eps_forecast_trend"] == "up"
    assert pack["corporate_events"]["items"][0]["title"] == "未来解禁"
    assert pack["holders"]["share_trend"]["pct_change"] == pytest.approx(1.0)
    assert pack["fund_flow"] == {"s_flow": 0.25, "recent5_main_net": 14000.0}
    assert pack["long_term_label"]["label"] == "观望"


def test_section_exception_isolated_and_degradation_emitted(test_db, monkeypatch):
    from backend.data.degradation import DegradationEvent
    import backend.data.context_builder as context_builder

    as_of = _seed_context_rows(test_db)

    def boom(symbol, as_of, db):
        raise RuntimeError("price failed")

    monkeypatch.setitem(context_builder._SECTION_BUILDERS, "price", boom)

    pack = context_builder.build_stock_context_pack("603986", as_of=as_of, db=test_db)

    assert "price failed" in pack["price"]["error"]
    assert "latest" in pack["financials"]
    event = test_db.query(DegradationEvent).filter_by(component="context_builder").one()
    assert event.category == "price"
    assert event.provider == "context_builder"
    assert "603986" in (event.context_json or "")


def test_render_context_text_markers_max_chars_and_deterministic():
    from backend.data.context_builder import render_context_text

    pack = {
        "symbol": "603986",
        "as_of": "2026-07-04T15:00:00",
        "price": {"error": "boom"},
        "financials": {"empty": True},
        "news": {"items": [{"title": "很长新闻标题" * 20, "published_at": "2026-07-03"}]},
    }

    one = render_context_text(pack, max_chars=120)
    two = render_context_text(pack, max_chars=120)

    assert one == two
    assert len(one) <= 120
    assert "⚠️ 价格: 数据获取失败" in one
    assert "(财务: 无数据)" in one
    assert not one.endswith("…")


def test_sections_filter_and_unknown_section(test_db):
    from backend.data.context_builder import build_stock_context_pack

    as_of = _seed_context_rows(test_db)

    pack = build_stock_context_pack("603986", as_of=as_of, sections=["price", "news"], db=test_db)

    assert "price" in pack
    assert "news" in pack
    assert "financials" not in pack
    with pytest.raises(ValueError, match="unknown section"):
        build_stock_context_pack("603986", as_of=as_of, sections=["price", "bogus"], db=test_db)
