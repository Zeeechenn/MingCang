from __future__ import annotations

from datetime import datetime


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
    assert strict_pack["financials"]["visibility"] == {
        "cutoff": "2026-07-04",
        "granularity": "date_level",
        "revision_history": "unverified",
        "note": "FinancialMetric disclosure_date is date-level only; historical revision storage is not available.",
    }


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
