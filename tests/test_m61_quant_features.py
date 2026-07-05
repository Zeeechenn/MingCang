from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from backend.data.database import (
    CorporateEvent,
    Price,
    ResearchReport,
    Stock,
)


def _add_prices(db, symbol: str, start: str = "2026-01-01", days: int = 130) -> None:
    dates = pd.bdate_range(start=start, periods=days)
    for idx, date in enumerate(dates):
        close = 10.0 + idx * 0.1
        db.add(
            Price(
                symbol=symbol,
                date=date.strftime("%Y-%m-%d"),
                open=close - 0.1,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=1000.0 + idx,
            )
        )
    db.commit()


def test_research_report_after_date_does_not_affect_features_at_d(test_db):
    from backend.tools.m61_quant_features import build_feature_matrix_v2

    symbol = "603986"
    test_db.add(Stock(symbol=symbol, name="兆易创新", market="CN", industry="半导体", active=True))
    _add_prices(test_db, symbol)
    test_db.add(
        ResearchReport(
            symbol=symbol,
            title="future report",
            org_name="unit",
            eps_forecast_y1=2.0,
            publish_date=datetime(2026, 4, 15),
            provider="unit",
        )
    )
    test_db.commit()

    matrix = build_feature_matrix_v2([symbol], "2026-04-14", "2026-04-15", test_db)

    assert matrix.loc[(symbol, "2026-04-14"), "report_count_90d"] == 0
    assert matrix.loc[(symbol, "2026-04-15"), "report_count_90d"] == 1


def test_missing_fund_flow_preserves_nan_not_zero(test_db):
    from backend.tools.m61_quant_features import build_feature_matrix_v2

    symbol = "300308"
    test_db.add(Stock(symbol=symbol, name="中际旭创", market="CN", industry="通信", active=True))
    _add_prices(test_db, symbol)

    matrix = build_feature_matrix_v2([symbol], "2026-03-02", "2026-03-02", test_db)

    row = matrix.loc[(symbol, "2026-03-02")]
    assert math.isnan(row["s_flow"])
    assert math.isnan(row["main_net_5d_sum"])
    assert row["s_flow"] != 0
    assert row["main_net_5d_sum"] != 0


def test_eps_forecast_revision_uses_recent_vs_prior_90d_mean(test_db):
    from backend.tools.m61_quant_features import build_feature_matrix_v2

    symbol = "601869"
    test_db.add(Stock(symbol=symbol, name="长飞光纤", market="CN", industry="通信", active=True))
    _add_prices(test_db, symbol, start="2025-08-01", days=190)
    for publish_date, eps in (
        ("2025-10-20", 1.0),
        ("2025-11-15", 1.2),
        ("2026-02-15", 1.5),
        ("2026-03-15", 1.8),
    ):
        test_db.add(
            ResearchReport(
                symbol=symbol,
                title=f"report {publish_date}",
                org_name="unit",
                eps_forecast_y1=eps,
                publish_date=datetime.fromisoformat(publish_date),
                provider="unit",
            )
        )
    test_db.commit()

    matrix = build_feature_matrix_v2([symbol], "2026-04-15", "2026-04-15", test_db)

    recent_mean = (1.5 + 1.8) / 2
    prior_mean = (1.0 + 1.2) / 2
    expected = recent_mean / prior_mean - 1
    assert matrix.loc[(symbol, "2026-04-15"), "eps_forecast_revision"] == expected


def test_unlock_days_are_capped_at_90(test_db):
    from backend.tools.m61_quant_features import build_feature_matrix_v2

    symbol = "688008"
    test_db.add(Stock(symbol=symbol, name="澜起科技", market="CN", industry="半导体", active=True))
    _add_prices(test_db, symbol)
    test_db.add(
        CorporateEvent(
            symbol=symbol,
            event_type="解禁",
            title="限售股解禁",
            event_date=datetime(2026, 7, 30),
            provider="unit",
            fetched_at=datetime(2026, 1, 1),
        )
    )
    test_db.commit()

    matrix = build_feature_matrix_v2([symbol], "2026-03-02", "2026-03-02", test_db)

    assert matrix.loc[(symbol, "2026-03-02"), "days_to_next_unlock"] == 90
