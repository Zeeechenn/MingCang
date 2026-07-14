"""Canonical lookahead audit and legacy-path compatibility tests."""

from datetime import datetime


def test_m46_5_audit_passes_clean_point_in_time_rows(test_db):
    from backend.data.database import FinancialMetric, NewsItem, Price, Signal, Stock
    from backend.tools.m46_5_lookahead_one_time_audit import build_audit

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", active=True))
    test_db.add(Price(
        symbol="600519",
        date="2026-06-01",
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=1000,
        source="fixture",
        fetched_at=datetime(2026, 6, 1, 16, 0),
        adjustment="qfq",
    ))
    test_db.add(NewsItem(
        symbol="600519",
        title="历史新闻",
        url="https://example.test/1",
        published_at=datetime(2026, 6, 1, 9, 0),
        source="fixture",
    ))
    test_db.add(FinancialMetric(
        symbol="600519",
        report_date="2026-03-31",
        disclosure_date="2026-04-28",
        revenue=100,
    ))
    test_db.add(Signal(
        symbol="600519",
        date="2026-06-01",
        data_timestamp="2026-06-01",
        sentiment_score=10,
        composite_score=20,
        recommendation="可关注",
        confidence="中",
    ))
    test_db.commit()

    report = build_audit(test_db)

    assert report["status"] == "pass"
    assert report["writes_db"] is False
    assert report["calls_llm_or_api"] is False
    assert report["blockers"] == []
    assert report["warnings"] == []


def test_m46_5_audit_blocks_future_signal_inputs(test_db):
    from backend.data.database import FinancialMetric, Price, ReviewCase, Signal
    from backend.tools.m46_5_lookahead_one_time_audit import build_audit

    test_db.add(Price(symbol="600519", date="2026-06-01", open=10, high=11, low=9, close=10, volume=1000))
    leaked_signal = Signal(
        symbol="600519",
        date="2026-06-01",
        data_timestamp="2026-06-02",
        composite_score=25,
        recommendation="可关注",
        confidence="中",
    )
    test_db.add(leaked_signal)
    test_db.add(FinancialMetric(
        symbol="600519",
        report_date="2026-06-30",
        disclosure_date="2026-06-01",
    ))
    test_db.commit()
    test_db.add(ReviewCase(
        symbol="600519",
        as_of="2026-05-31",
        signal_id=leaked_signal.id,
    ))
    test_db.commit()

    report = build_audit(test_db)

    assert report["status"] == "blocked"
    assert "signal_data_timestamp_after_signal_day" in report["blockers"]
    assert "financial_disclosure_before_report_date" in report["blockers"]
    assert "review_case_references_future_signal" in report["blockers"]


def test_m46_5_audit_warns_on_unproven_lineage_and_display_risks(test_db):
    from backend.data.database import NewsItem, Price, Signal
    from backend.tools.m46_5_lookahead_one_time_audit import build_audit

    test_db.add(Price(symbol="600519", date="2026-06-01", open=10, high=11, low=9, close=10, volume=1000))
    test_db.add(Signal(
        symbol="600519",
        date="2026-06-01T22:11+08:00",
        data_timestamp="2026-06-01",
        sentiment_score=20,
        composite_score=25,
        recommendation="可关注",
        confidence="中",
    ))
    test_db.add(NewsItem(
        symbol="600519",
        title="次日新闻",
        url="https://example.test/2",
        published_at=datetime(2026, 6, 2, 8, 0),
        source="fixture",
    ))
    test_db.commit()

    report = build_audit(test_db)

    assert report["status"] == "warning"
    assert "signal_date_not_plain_yyyy_mm_dd" in report["warnings"]
    assert "same_symbol_news_after_signal_day_requires_lineage_review" in report["warnings"]
    assert "price_rows_missing_provenance" in report["warnings"]


def test_m46_5_cli_uses_read_only_sqlite_uri_for_local_files():
    from backend.tools.m46_5_lookahead_one_time_audit import _readonly_sqlite_url

    url = _readonly_sqlite_url("sqlite:////tmp/mingcang.db")

    assert url == "sqlite:///file:/tmp/mingcang.db?mode=ro&immutable=1&uri=true"
