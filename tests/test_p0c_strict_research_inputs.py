from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def _add_metric(db, symbol: str, report_date: str, **kwargs):
    from backend.data.database import FinancialMetric

    defaults = {
        "symbol": symbol,
        "report_date": report_date,
        "period_type": "Q",
        "revenue": None,
        "revenue_yoy": None,
        "net_profit": None,
        "net_profit_yoy": None,
        "total_assets": None,
        "total_equity": None,
        "long_term_debt": None,
        "current_ratio": None,
        "operating_cf": None,
        "shares_outstanding": None,
        "gross_margin": None,
        "roe": None,
        "asset_turnover": None,
        "fetched_at": datetime(2026, 1, 1),
    }
    defaults.update(kwargs)
    row = FinancialMetric(**defaults)
    db.add(row)
    db.commit()
    return row


def _add_holder(db, symbol: str, report_date: str, shares: float):
    from backend.data.database import HolderSnapshot

    row = HolderSnapshot(
        symbol=symbol,
        report_date=datetime.fromisoformat(report_date),
        total_shares=shares,
        provider="unit",
    )
    db.add(row)
    db.commit()
    return row


def test_strict_piotroski_marks_all_na_and_tiny_factor_budget_unavailable(test_db):
    from backend.data.fundamentals import (
        compute_piotroski_factors,
        compute_piotroski_factors_strict,
    )

    _add_metric(test_db, "600519", "2025-06-30", disclosure_date="2025-08-01")
    _add_metric(test_db, "600519", "2026-06-30", disclosure_date="2026-08-01")

    default_result = compute_piotroski_factors("600519", test_db)
    assert default_result["available"] is True
    assert default_result["score"] == 0
    assert default_result["score_denominator"] == 8

    strict_result = compute_piotroski_factors_strict(
        "600519",
        test_db,
        as_of=datetime(2026, 8, 1),
    )
    assert strict_result["available"] is False
    assert strict_result["score"] == 0
    assert strict_result["score_denominator"] == 0
    assert all(value is None for value in strict_result["factors"].values())
    assert strict_result["reason"] == "insufficient_usable_factors"

    _add_metric(
        test_db,
        "000001",
        "2025-06-30",
        disclosure_date="2025-08-01",
        net_profit=100.0,
        total_assets=1000.0,
    )
    _add_metric(
        test_db,
        "000001",
        "2026-06-30",
        disclosure_date="2026-08-01",
        net_profit=-10.0,
        total_assets=1000.0,
        operating_cf=-5.0,
    )

    tiny = compute_piotroski_factors_strict("000001", test_db, as_of=datetime(2026, 8, 1))
    assert tiny["available"] is False
    assert tiny["score_denominator"] == 4
    assert tiny["factors"]["roa_positive"] is False
    assert tiny["factors"]["cfo_positive"] is False
    assert tiny["factors"]["roa_improving"] is False
    assert tiny["factors"]["cfo_gt_ni"] is True


def test_strict_piotroski_requires_cutoff_and_does_not_use_recent_quarter_fallback(test_db):
    import pytest

    from backend.data.fundamentals import (
        compute_piotroski_factors,
        compute_piotroski_factors_strict,
    )

    _add_metric(
        test_db,
        "600519",
        "2026-03-31",
        disclosure_date="2026-04-30",
        net_profit=80.0,
        total_assets=1000.0,
        current_ratio=1.2,
        gross_margin=30.0,
        asset_turnover=0.4,
    )
    _add_metric(
        test_db,
        "600519",
        "2026-06-30",
        disclosure_date="2026-07-31",
        net_profit=100.0,
        total_assets=1000.0,
        current_ratio=1.4,
        gross_margin=32.0,
        asset_turnover=0.5,
    )

    with pytest.raises(ValueError, match="strict_piotroski_requires_explicit_as_of"):
        compute_piotroski_factors_strict("600519", test_db)
    with pytest.raises(ValueError):
        compute_piotroski_factors_strict("600519", test_db, as_of="not-a-date")

    default_result = compute_piotroski_factors("600519", test_db)
    assert default_result["comparison_period"] == "2026-03-31"
    assert default_result["factors"]["roa_improving"] is True

    strict_result = compute_piotroski_factors_strict(
        "600519",
        test_db,
        as_of=datetime(2026, 8, 1),
    )
    assert strict_result["comparison_period"] is None
    assert strict_result["factors"]["roa_improving"] is None
    assert strict_result["factors"]["gross_margin_improving"] is None
    assert strict_result["factor_reasons"]["roa_improving"] == "same_period_comparison_missing"
    assert strict_result["factors"]["no_new_shares"] is None
    assert strict_result["factor_reasons"]["no_new_shares"] == "holder_disclosure_as_of_unavailable"


def test_strict_context_uses_one_visible_financial_as_of_for_latest_and_piotroski(test_db):
    from backend.data.context_builder import build_stock_context_pack

    _add_metric(
        test_db,
        "600519",
        "2025-03-31",
        disclosure_date="2025-04-30",
        net_profit=80.0,
        total_assets=1000.0,
        long_term_debt=200.0,
        current_ratio=1.4,
        operating_cf=70.0,
        gross_margin=30.0,
        asset_turnover=0.4,
    )
    _add_metric(
        test_db,
        "600519",
        "2026-03-31",
        disclosure_date="2026-04-30",
        net_profit=120.0,
        total_assets=1000.0,
        long_term_debt=150.0,
        current_ratio=1.8,
        operating_cf=130.0,
        gross_margin=35.0,
        asset_turnover=0.5,
    )
    _add_metric(
        test_db,
        "600519",
        "2026-06-30",
        disclosure_date=None,
        net_profit=999.0,
        total_assets=1000.0,
        long_term_debt=10.0,
        current_ratio=9.0,
        operating_cf=999.0,
        gross_margin=99.0,
        asset_turnover=9.0,
    )
    _add_holder(test_db, "600519", "2025-03-31", 100.0)
    _add_holder(test_db, "600519", "2026-03-31", 100.0)

    as_of = datetime(2026, 7, 4, 15, 0, 0)
    default_pack = build_stock_context_pack("600519", as_of=as_of, sections=["financials"], db=test_db)
    assert default_pack["financials"]["latest"]["report_date"] == "2026-06-30"

    strict_pack = build_stock_context_pack(
        "600519",
        as_of=as_of,
        sections=["financials"],
        db=test_db,
        strict_research_inputs=True,
    )
    assert strict_pack["financials"]["latest"]["report_date"] == "2026-03-31"
    assert strict_pack["financials"]["latest"]["disclosure_date"] == "2026-04-30"
    assert strict_pack["financials"]["piotroski"]["report_period"] == "2026-03-31"
    assert strict_pack["financials"]["piotroski"]["comparison_period"] == "2025-03-31"
    assert strict_pack["financials"]["piotroski"]["factors"]["no_new_shares"] is None
    assert strict_pack["financials"]["visibility"]["cutoff"] == "2026-07-04"
    assert strict_pack["financials"]["visibility"]["granularity"] == "date_level"
    assert strict_pack["financials"]["visibility"]["revision_history"] == "unverified"
    assert strict_pack["financials"]["visibility"]["report_period_age_days"] == 95
    assert strict_pack["financials"]["visibility"]["disclosure_age_days"] == 65


def test_strict_context_blocks_unknown_disclosure_and_future_or_expired_labels(test_db):
    from backend.data.context_builder import build_stock_context_pack
    from backend.data.database import LongTermLabel

    _add_metric(test_db, "600519", "2026-06-30", disclosure_date=None, net_profit=100.0)
    test_db.add(
        LongTermLabel(
            symbol="600519",
            date="2026-07-03",
            label="expired",
            score=1.0,
            expires_at="2026-07-03",
            created_at=datetime(2026, 7, 3, 10, 0, 0),
        )
    )
    test_db.add(
        LongTermLabel(
            symbol="600519",
            date="2026-07-06",
            label="future",
            score=2.0,
            expires_at="2026-07-16",
            created_at=datetime(2026, 7, 6, 10, 0, 0),
        )
    )
    test_db.add(
        LongTermLabel(
            symbol="600519",
            date="2026-07-02",
            label="active",
            score=3.0,
            expires_at="2026-07-12",
            created_at=datetime(2026, 7, 2, 10, 0, 0),
        )
    )
    test_db.commit()

    as_of = datetime(2026, 7, 4, 15, 0, 0)
    strict_pack = build_stock_context_pack(
        "600519",
        as_of=as_of,
        sections=["financials", "long_term_label"],
        db=test_db,
        strict_research_inputs=True,
    )

    assert strict_pack["financials"]["empty"] is True
    assert strict_pack["financials"]["reason"] == "no_disclosed_financials_as_of"
    assert strict_pack["financials"]["visibility"]["granularity"] == "date_level"
    assert strict_pack["financials"]["visibility"]["revision_history"] == "unverified"
    assert strict_pack["long_term_label"]["label"] == "active"


def test_strict_context_requires_explicit_db_and_as_of_without_session_or_ledger_writes(test_db, monkeypatch):
    from backend.data import context_builder
    from backend.data.degradation import DegradationEvent

    def fail_session():
        raise AssertionError("strict mode must not open default SessionLocal")

    monkeypatch.setattr(context_builder, "SessionLocal", fail_session)

    missing_db = context_builder.build_stock_context_pack(
        "600519",
        as_of=datetime(2026, 7, 4),
        sections=["financials"],
        strict_research_inputs=True,
    )
    assert missing_db["financials"]["error"] == "strict_research_inputs_requires_explicit_db_and_as_of"

    missing_as_of = context_builder.build_stock_context_pack(
        "600519",
        sections=["long_term_label"],
        db=test_db,
        strict_research_inputs=True,
    )
    assert missing_as_of["long_term_label"]["error"] == "strict_research_inputs_requires_explicit_db_and_as_of"

    bad_as_of = context_builder.build_stock_context_pack(
        "600519",
        as_of="2026-07-04",
        sections=["financials"],
        db=test_db,
        strict_research_inputs=True,
    )
    assert bad_as_of["financials"]["error"] == "strict_research_inputs_requires_explicit_db_and_as_of"

    def readonly_error(symbol, as_of, db):
        raise RuntimeError("readonly database")

    monkeypatch.setattr(context_builder, "_build_financials_strict", readonly_error)
    packet = context_builder.build_stock_context_pack(
        "600519",
        as_of=datetime(2026, 7, 4),
        sections=["financials"],
        db=test_db,
        strict_research_inputs=True,
    )

    assert packet["financials"]["error"] == "readonly database"
    assert test_db.query(DegradationEvent).count() == 0


def test_strict_context_reads_without_autoflushing_pending_objects(test_db):
    from backend.data.context_builder import build_stock_context_pack
    from backend.data.database import FinancialMetric

    _add_metric(
        test_db,
        "600519",
        "2026-03-31",
        disclosure_date="2026-04-30",
        net_profit=100.0,
        total_assets=1000.0,
    )
    test_db.add(FinancialMetric(report_date="2026-06-30"))

    packet = build_stock_context_pack(
        "600519",
        as_of=datetime(2026, 7, 4),
        sections=["financials"],
        db=test_db,
        strict_research_inputs=True,
    )

    assert packet["financials"]["piotroski"]["available"] is False
    test_db.rollback()


def test_strict_pit_excludes_late_fetched_financial_rows(test_db):
    from backend.data.fundamentals import compute_piotroski_factors_strict

    _add_metric(
        test_db,
        "600519",
        "2025-06-30",
        disclosure_date="2025-08-20",
        net_profit=100.0,
        total_assets=1000.0,
        fetched_at=datetime(2026, 9, 24, 10),
    )
    _add_metric(
        test_db,
        "600519",
        "2026-06-30",
        disclosure_date="2026-08-20",
        net_profit=120.0,
        total_assets=1000.0,
        fetched_at=datetime(2026, 9, 24, 10),
    )

    historical = compute_piotroski_factors_strict(
        "600519", test_db, as_of=datetime(2026, 9, 1)
    )
    current = compute_piotroski_factors_strict(
        "600519", test_db, as_of=datetime(2026, 9, 25)
    )

    assert historical["available"] is False
    assert historical["reason"] == "insufficient_visible_periods"
    assert current["report_period"] == "2026-06-30"


def test_financial_pit_uses_cn_calendar_date_and_utc_fetched_cutoff(test_db):
    from datetime import UTC

    from backend.data.context_builder import build_stock_context_pack

    _add_metric(test_db, "600519", "2024-03-31", disclosure_date="2024-04-30", fetched_at=datetime(2026, 9, 1, 10))
    _add_metric(test_db, "600519", "2025-03-31", disclosure_date="2025-04-30", fetched_at=datetime(2026, 9, 1, 10))
    _add_metric(
        test_db,
        "600519",
        "2026-03-31",
        disclosure_date="2026-04-30",
        fetched_at=datetime(2026, 9, 24, 15, 59, 59, 999999),
    )
    _add_metric(
        test_db,
        "600519",
        "2026-06-30",
        disclosure_date="2026-08-20",
        fetched_at=datetime(2026, 9, 24, 16, 0),
    )
    _add_holder(test_db, "600519", "2025-03-31", 100.0)
    _add_holder(test_db, "600519", "2026-03-31", 100.0)

    cn_eod = datetime(2026, 9, 24, 23, 59, 59, 999999, tzinfo=ZoneInfo("Asia/Shanghai"))
    utc_equivalent = datetime(2026, 9, 24, 15, 59, 59, 999999, tzinfo=UTC)
    naive_utc = datetime(2026, 9, 24, 15, 59, 59, 999999)
    packs = [
        build_stock_context_pack(
            "600519", as_of=cutoff, sections=["financials"], db=test_db, strict_research_inputs=True
        )
        for cutoff in (cn_eod, utc_equivalent, naive_utc)
    ]

    for pack in packs:
        financials = pack["financials"]
        assert financials["latest"]["report_date"] == "2026-03-31"
        assert financials["piotroski"]["report_period"] == "2026-03-31"
        assert financials["piotroski"]["comparison_period"] == "2025-03-31"
        assert financials["visibility"]["cutoff"] == "2026-09-24"


def test_default_context_aware_utc_uses_cn_financial_calendar_date_but_naive_stays_utc(test_db):
    from datetime import UTC

    from backend.data.context_builder import build_stock_context_pack

    _add_metric(
        test_db,
        "600519",
        "2026-09-25",
        disclosure_date="2026-09-25",
        fetched_at=datetime(2026, 9, 24, 16, 0),
    )
    aware_pack = build_stock_context_pack(
        "600519", as_of=datetime(2026, 9, 24, 16, 0, tzinfo=UTC), sections=["financials"], db=test_db
    )
    naive_pack = build_stock_context_pack(
        "600519", as_of=datetime(2026, 9, 24, 16, 0), sections=["financials"], db=test_db
    )

    assert aware_pack["financials"]["latest"]["report_date"] == "2026-09-25"
    assert naive_pack["financials"]["empty"] is True


def test_default_render_context_text_keeps_error_and_empty_text_byte_compatible():
    from backend.data.context_builder import render_context_text

    pack = {
        "symbol": "600519",
        "as_of": "2026-07-04T15:00:00",
        "price": {"error": "boom"},
        "financials": {"empty": True, "reason": "strict-only"},
    }

    assert render_context_text(pack, max_chars=200) == "\n".join(
        [
            "股票: 600519",
            "截至: 2026-07-04T15:00:00",
            "⚠️ 价格: 数据获取失败",
            "(财务: 无数据)",
        ]
    )


def test_render_context_text_strict_preserves_risk_lines_under_small_budget():
    import pytest

    from backend.data.context_builder import StrictContextBudgetError, render_context_text

    pack = {
        "symbol": "600519",
        "as_of": "2026-07-04T15:00:00",
        "price": {"last_close": 100.0, "date": "2026-07-04"},
        "financials": {"empty": True, "reason": "no_disclosed_financials_as_of"},
        "long_term_label": {"empty": True, "reason": "no_active_label_as_of"},
        "news": {"items": [{"title": "headline " * 20, "published_at": "2026-07-03"}]},
        "data_health": {
            "recent_degradations": [
                {"category": "financials", "provider": "unit", "error": "stale disclosure calendar"},
            ],
            "active_fake_feature_flags": {},
        },
    }

    default_text = render_context_text(pack, max_chars=170)
    assert "stale disclosure calendar" not in default_text

    strict_text = render_context_text(pack, max_chars=320, strict_research_inputs=True)
    assert len(strict_text) <= 320
    assert strict_text.startswith("股票: 600519\n截至: 2026-07-04T15:00:00")
    assert "stale disclosure calendar" in strict_text
    assert "unavailable reason=no_disclosed_financials_as_of" in strict_text
    assert "(TRUNCATED ordinary context)" in strict_text

    with pytest.raises(StrictContextBudgetError, match="strict_context_budget_too_small"):
        render_context_text(pack, max_chars=35, strict_research_inputs=True)


def test_strict_render_does_not_treat_long_news_urls_as_required_risk():
    from backend.data.context_builder import render_context_text

    pack = {
        "symbol": "600519",
        "as_of": "2026-07-04T15:00:00",
        "financials": {"empty": True, "reason": "no_disclosed_financials_as_of"},
        "news": {
            "items": [
                {
                    "title": "headline " * 30,
                    "url": "https://example.test/a/very/long/path",
                    "published_at": "2026-07-03",
                }
            ]
        },
    }

    text = render_context_text(pack, max_chars=140, strict_research_inputs=True)
    assert "unavailable reason=no_disclosed_financials_as_of" in text
    assert "(TRUNCATED ordinary context)" in text
    assert "https://example.test" not in text


def test_long_term_piotroski_analyst_uses_strict_as_of_inputs(test_db):
    from backend.agents.long_term.piotroski_analyst import analyze

    _add_metric(
        test_db,
        "600519",
        "2025-06-30",
        disclosure_date="2025-08-20",
        net_profit=100.0,
        total_assets=1000.0,
    )
    _add_metric(
        test_db,
        "600519",
        "2026-06-30",
        disclosure_date="2026-08-20",
        net_profit=-10.0,
        total_assets=1000.0,
        operating_cf=-5.0,
    )

    report = analyze("600519", test_db, as_of=datetime(2026, 9, 1))

    assert report.raw["strict_research_inputs"] is True
    assert report.raw["as_of"] == "2026-09-01T00:00:00"
    assert report.raw["available"] is False
    assert report.raw["factors"]["roa_positive"] is False
    assert report.raw["factors"]["cfo_positive"] is False
    assert report.confidence == 0
    assert any("未知" in finding or "不足" in finding for finding in report.key_findings)


def test_missing_strict_quality_report_degrades_label_eligibility():
    from backend.agents.long_term.base import LongTermReport
    from backend.agents.long_term.team import _assess_label_quality

    reports = {
        "track": LongTermReport("track", 20, 0.8, "观望", ["track evidence"]),
        "quality": LongTermReport(
            "quality",
            0,
            0,
            "观望",
            ["财务数据不足"],
            raw={"strict_research_inputs": True, "available": False, "reason": "insufficient_usable_factors"},
        ),
        "boom": LongTermReport("boom", 15, 0.7, "观望", ["industry evidence"]),
    }

    quality, eligible, notes = _assess_label_quality(reports)

    assert quality == "degraded"
    assert eligible is False
    assert "Piotroski 严格输入不可用" in notes[0]


def test_stock_context_entry_builds_strict_financial_and_active_label_pack(test_db, monkeypatch):
    from backend.agent import context
    from backend.data.database import LongTermLabel

    _add_metric(
        test_db,
        "600519",
        "2025-06-30",
        disclosure_date="2025-08-20",
        net_profit=100.0,
        total_assets=1000.0,
    )
    _add_metric(
        test_db,
        "600519",
        "2026-06-30",
        disclosure_date="2026-08-20",
        net_profit=120.0,
        total_assets=1000.0,
    )
    test_db.add(
        LongTermLabel(
            symbol="600519",
            date="2026-08-20",
            label="观望",
            score=12,
            expires_at="2026-10-30",
            quality="degraded",
            constraint_eligible=False,
            quality_notes_json='["strict inputs unavailable"]',
            created_at=datetime(2026, 8, 20, 10),
        )
    )
    test_db.commit()
    called = {}

    def fake_pack(symbol, **kwargs):
        called.update(kwargs)
        return {"symbol": symbol, "as_of": kwargs["as_of"].isoformat()}

    monkeypatch.setattr(context, "build_stock_context_pack", fake_pack)
    monkeypatch.setattr(context, "render_context_text", lambda _pack, _limit, **kw: str(kw))

    result = context.mingcang_stock_context(test_db, "600519")

    assert called["strict_research_inputs"] is True
    assert called["as_of"] is not None
    assert "long_term_label" in called["sections"]
    assert result["long_term_label"]["quality_basis"] == "stored_generation_metadata"
    assert result["long_term_label"]["revalidation_required"] is True
    assert result["long_term_label"]["current_input_quality_available"] is False
    assert result["long_term_label"]["current_input_quality_reason"] == "strict_financial_quality_unavailable"
    assert result["long_term_label"]["current_constraints_eligible"] is False
    assert result["context_pack"]["as_of"] == called["as_of"].isoformat()


def test_stock_context_does_not_recertify_stored_label_when_strict_inputs_available(test_db, monkeypatch):
    from backend.agent import context
    from backend.data.database import LongTermLabel

    test_db.add(LongTermLabel(
        symbol="600519",
        date="2026-09-20",
        label="跟踪",
        score=15,
        expires_at="2026-10-30",
        quality="ok",
        constraint_eligible=True,
        quality_notes_json="[]",
        created_at=datetime(2026, 9, 20, 10),
    ))
    test_db.commit()

    monkeypatch.setattr(
        context,
        "build_stock_context_pack",
        lambda symbol, **kwargs: {
            "symbol": symbol,
            "as_of": kwargs["as_of"].isoformat(),
            "financials": {"piotroski": {"available": True}},
        },
    )
    monkeypatch.setattr(context, "render_context_text", lambda *_args, **_kwargs: "")

    label = context.mingcang_stock_context(test_db, "600519")["long_term_label"]

    assert label["constraint_eligible"] is True  # historical stored metadata is preserved
    assert label["revalidation_required"] is False
    assert label["current_input_quality_available"] is True
    assert label["current_constraints_eligible"] is None  # current suitability remains unknown
    assert label["current_input_quality_reason"] == "label_not_recomputed_from_current_inputs"
