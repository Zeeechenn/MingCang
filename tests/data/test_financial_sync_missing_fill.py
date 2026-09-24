"""Safe opt-in enrichment of existing financial metric rows."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from backend.data.database import FinancialMetric, Stock
from backend.data.fundamentals import compute_piotroski_factors_strict


def test_financial_sync_prefers_direct_cash_flow_and_fills_only_null_fields(test_db, monkeypatch):
    import backend.data.fundamentals as fundamentals

    abstract = pd.DataFrame(
        [
            {"指标": "营业总收入", "20260331": 10000.0},
            {"指标": "归母净利润", "20260331": 1200.0},
            {"指标": "毛利率", "20260331": 42.0},
            {"指标": "经营现金流量净额", "20260331": -1000.25},
            {"指标": "股东权益合计(净资产)", "20260331": 8000.0},
            {"指标": "净资产收益率(ROE)", "20260331": 15.0},
            {"指标": "总资产周转率", "20260331": 0.6},
            {"指标": "流动比率", "20260331": 1.8},
        ]
    )
    indicator = pd.DataFrame(
        [
            {
                "日期": "2026-03-31",
                "净资产收益率(%)": 14.0,
                "总资产周转率(次)": 0.55,
                "总资产(元)": 12000.0,
                "长期负债比率(%)": 10.0,
                "股东权益比率(%)": 60.0,
                "流动比率": 1.7,
                "经营现金净流量对销售收入比率(%)": -0.1,
            }
        ]
    )
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace())
    monkeypatch.setattr(fundamentals, "_fetch_abstract", lambda _ak, _symbol: abstract)
    monkeypatch.setattr(fundamentals, "_fetch_indicator", lambda _ak, _symbol, years: indicator)

    existing = FinancialMetric(
        symbol="600519",
        report_date="2026-03-31",
        period_type="Q1",
        total_assets=9999.0,
        source="legacy-provider",
        disclosure_date="2026-04-30",
        fetched_at=datetime(2026, 5, 1),
        raw_json='{"total_assets":9999.0}',
    )
    test_db.add(existing)
    test_db.add(
        FinancialMetric(
            symbol="600519",
            report_date="2025-03-31",
            period_type="Q1",
            net_profit=100.0,
            total_assets=1000.0,
            disclosure_date="2025-04-30",
            fetched_at=datetime(2025, 5, 1),
        )
    )
    test_db.commit()

    assert fundamentals.sync_financial_metrics("600519", test_db) == 0
    test_db.refresh(existing)
    assert existing.net_profit is None
    assert existing.fetched_at == datetime(2026, 5, 1)

    before_enrichment = compute_piotroski_factors_strict(
        "600519", test_db, as_of=datetime(2026, 7, 1)
    )
    assert before_enrichment["report_period"] == "2026-03-31"

    result = fundamentals.sync_financial_metrics(
        "600519", test_db, fill_missing=True, return_counts=True
    )
    assert result == {"inserted": 0, "updated": 1}
    test_db.refresh(existing)

    assert existing.net_profit == 1200.0
    assert existing.revenue == 10000.0
    assert existing.operating_cf == -1000.25
    assert existing.roe == 15.0  # direct abstract value, not the distinct indicator estimate
    assert existing.current_ratio == 1.8
    assert existing.asset_turnover == 0.6
    assert existing.total_equity == 8000.0
    assert existing.total_assets == 9999.0  # known values are never replaced
    assert existing.source == "legacy-provider"
    assert existing.disclosure_date == "2026-04-30"  # sync never invents/replaces disclosure time
    assert existing.fetched_at > datetime(2026, 5, 1)
    payload = json.loads(existing.raw_json)
    assert payload["field_sources"]["operating_cf"] == "akshare_financial_abstract"
    assert "operating_cf" in payload["field_observed_at"]
    assert payload["total_assets"] == 9999.0
    after_enrichment = compute_piotroski_factors_strict(
        "600519", test_db, as_of=datetime(2026, 7, 1)
    )
    assert after_enrichment["report_period"] is None
    assert after_enrichment["reason"] == "insufficient_visible_periods"


def test_targeted_financial_fill_requires_symbols_and_returns_update_receipt(test_db, monkeypatch):
    from backend.tools import backfill_coverage

    test_db.add(Stock(symbol="000858", asset_key="CN:000858", name="五粮液", market="CN", active=True))
    test_db.commit()
    monkeypatch.setattr(backfill_coverage, "SessionLocal", lambda: test_db)
    calls = []

    def fake_sync(symbol, _db, *, years, fill_missing, return_counts):
        calls.append((symbol, years, fill_missing, return_counts))
        return {"inserted": 2, "updated": 1}

    monkeypatch.setattr(backfill_coverage, "sync_financial_metrics", fake_sync)
    monkeypatch.setattr(
        backfill_coverage,
        "sync_disclosure_dates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("full-market disclosure sync")),
    )

    result = backfill_coverage.run_backfill(
        fill_missing_financial=True,
        financial_symbols=["000858"],
        skip_financial=False,
        sleep_seconds=0,
    )

    assert calls == [("000858", 5, True, True)]
    assert result["stats"]["financial_rows_inserted"] == 2
    assert result["stats"]["financial_rows_updated"] == 1
    assert result["stats"]["financial_rows_missing_disclosure"] == 0


def test_targeted_financial_fill_rejects_missing_or_inactive_symbols(test_db, monkeypatch):
    import pytest

    from backend.tools import backfill_coverage

    monkeypatch.setattr(backfill_coverage, "SessionLocal", lambda: test_db)
    with pytest.raises(ValueError, match="fill_missing_financial_requires_explicit_symbols"):
        backfill_coverage.run_backfill(fill_missing_financial=True)
    with pytest.raises(ValueError, match="financial_symbols_not_active_cn_watchlist"):
        backfill_coverage.run_backfill(
            fill_missing_financial=True,
            financial_symbols=["600519"],
        )
