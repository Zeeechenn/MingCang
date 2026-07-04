from __future__ import annotations

from datetime import datetime
from math import tanh
from statistics import median

from backend.data.database import FinancialMetric, FundFlow, HolderSnapshot


def _add_metric(db, symbol: str, report_date: str) -> None:
    db.add(
        FinancialMetric(
            symbol=symbol,
            report_date=report_date,
            period_type="Q1",
            revenue=100,
            net_profit=10,
            total_assets=100,
            long_term_debt=10,
            current_ratio=2,
            operating_cf=20,
            gross_margin=30,
            asset_turnover=1,
        )
    )
    db.commit()


def _add_holder(db, symbol: str, report_date: str, total_shares: float) -> None:
    db.add(
        HolderSnapshot(
            symbol=symbol,
            report_date=datetime.fromisoformat(report_date),
            total_shares=total_shares,
            provider="test",
        )
    )
    db.commit()


def test_fflow_kline_parse_mapping(monkeypatch):
    from backend.data.category_fetchers import fetch_fund_flow_eastmoney_fflow
    from backend.data.category_registry import FetchRequest

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": {
                    "klines": [
                        "2026-07-01,100,10,20,30,40,1,2,3,4,5",
                    ]
                }
            }

    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr("backend.data.category_fetchers.requests.get", fake_get)

    rows = fetch_fund_flow_eastmoney_fflow(
        FetchRequest(symbol="601869", start=None, end=None)
    )

    assert captured["params"]["secid"] == "1.601869"
    assert captured["params"]["klt"] == 101
    assert captured["params"]["lmt"] == 250
    assert captured["headers"]["User-Agent"] == "Mozilla/5.0"
    assert rows[0]["trade_date"] == datetime(2026, 7, 1)
    assert rows[0]["main_net"] == 100.0
    assert rows[0]["small_net"] == 10.0
    assert rows[0]["medium_net"] == 20.0
    assert rows[0]["large_net"] == 30.0
    assert rows[0]["super_large_net"] == 40.0
    assert rows[0]["metric"] == "main_net"
    assert rows[0]["value"] == 100.0
    assert rows[0]["currency"] == "CNY"


def test_compute_s_flow_data_known_series_and_empty_cases():
    from backend.tools.m52_flow_floor import compute_s_flow_data

    values = [float(idx * 100) for idx in range(1, 26)]
    raw = [{"trade_date": datetime(2026, 1, idx), "main_net": value} for idx, value in enumerate(values, 1)]

    rolling = [sum(values[idx : idx + 5]) for idx in range(0, len(values) - 4)]
    expected = tanh(sum(values[-5:]) / (median(abs(value) for value in rolling) * 3))

    assert compute_s_flow_data(raw) == expected
    assert compute_s_flow_data(raw[:24]) is None
    assert compute_s_flow_data([]) is None
    assert compute_s_flow_data(None) is None


def test_fetch_flow_data_pit_excludes_rows_after_as_of(test_db, monkeypatch):
    import backend.tools.m52_flow_floor as flow_floor

    for day, main_net in ((1, 100.0), (2, 200.0), (3, 300.0)):
        test_db.add(
            FundFlow(
                symbol="601869",
                trade_date=datetime(2026, 7, day),
                main_net=main_net,
                super_large_net=main_net + 1,
                large_net=main_net + 2,
                medium_net=main_net + 3,
                small_net=main_net + 4,
                provider="eastmoney_fflow",
            )
        )
    test_db.commit()
    monkeypatch.setattr(flow_floor, "SessionLocal", lambda: test_db)

    rows = flow_floor.fetch_flow_data_pit("601869", datetime(2026, 7, 2, 15))

    assert [row["trade_date"] for row in rows] == [datetime(2026, 7, 1), datetime(2026, 7, 2)]
    assert [row["main_net"] for row in rows] == [100.0, 200.0]


def test_piotroski_no_new_shares_increase_gt_2_false(test_db):
    from backend.data.fundamentals import compute_piotroski_factors

    _add_metric(test_db, "300548", "2025-03-31")
    _add_metric(test_db, "300548", "2026-03-31")
    _add_holder(test_db, "300548", "2025-03-31", 100.0)
    _add_holder(test_db, "300548", "2026-03-31", 103.0)

    result = compute_piotroski_factors("300548", test_db)

    assert result["factors"]["no_new_shares"] is False
    assert result["score_denominator"] == 9


def test_piotroski_no_new_shares_lte_2_true(test_db):
    from backend.data.fundamentals import compute_piotroski_factors

    _add_metric(test_db, "300548", "2025-03-31")
    _add_metric(test_db, "300548", "2026-03-31")
    _add_holder(test_db, "300548", "2025-03-31", 100.0)
    _add_holder(test_db, "300548", "2026-03-31", 102.0)

    result = compute_piotroski_factors("300548", test_db)

    assert result["factors"]["no_new_shares"] is True
    assert result["score_denominator"] == 9


def test_piotroski_no_new_shares_missing_history_is_na_and_excluded(test_db):
    from backend.data.fundamentals import compute_piotroski_factors

    _add_metric(test_db, "300548", "2025-03-31")
    _add_metric(test_db, "300548", "2026-03-31")
    _add_holder(test_db, "300548", "2026-03-31", 100.0)

    result = compute_piotroski_factors("300548", test_db)

    assert result["factors"]["no_new_shares"] is None
    assert result["score_denominator"] == 8
