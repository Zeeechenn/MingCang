from __future__ import annotations

from datetime import datetime
from math import tanh
from types import SimpleNamespace
from statistics import median

from backend.data.database import FinancialMetric, FundFlow, HolderSnapshot


def _flow_row(day: int, main_net: float | None) -> SimpleNamespace:
    return SimpleNamespace(
        trade_date=datetime(2026, 7, day),
        main_net=main_net,
        super_large_net=None,
        large_net=None,
        medium_net=None,
        small_net=None,
    )


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


def test_compute_s_flow_data_ignores_missing_main_net_but_keeps_zero():
    from backend.tools.m52_flow_floor import compute_s_flow_data

    valid_values = [0.0] + [float(idx * 100) for idx in range(1, 25)]
    raw = [
        {"trade_date": datetime(2026, 1, 1), "main_net": None},
        *[
            {"trade_date": datetime(2026, 1, idx + 2), "main_net": value}
            for idx, value in enumerate(valid_values)
        ],
        {"trade_date": datetime(2026, 1, 27), "main_net": None},
    ]

    rolling = [sum(valid_values[idx : idx + 5]) for idx in range(0, len(valid_values) - 4)]
    expected = tanh(sum(valid_values[-5:]) / (median(abs(value) for value in rolling) * 3))

    assert compute_s_flow_data(raw) == expected
    assert compute_s_flow_data(raw[:25]) is None


def test_context_fund_flow_recent5_uses_last_five_valid_values(test_db, monkeypatch):
    import backend.data.context_builder as context_builder

    symbol = "601869"
    for day, main_net in ((1, 100.0), (2, None), (3, 0.0), (4, -50.0), (5, 25.0), (6, 75.0)):
        test_db.add(
            FundFlow(
                symbol=symbol,
                trade_date=datetime(2026, 7, day),
                main_net=main_net,
                provider="unit",
            )
        )
    test_db.commit()
    monkeypatch.setattr(context_builder.flow_floor, "compute_s_flow_data", lambda raw: None)

    pack = context_builder.build_stock_context_pack(
        symbol,
        as_of=datetime(2026, 7, 6),
        sections=["fund_flow"],
        db=test_db,
    )

    assert pack["fund_flow"]["recent5_main_net"] == 150.0


def test_context_fund_flow_recent5_is_none_when_valid_values_are_insufficient(test_db):
    import backend.data.context_builder as context_builder

    symbol = "300308"
    for day, main_net in ((1, None), (2, 0.0), (3, 10.0), (4, -5.0), (5, 20.0)):
        test_db.add(
            FundFlow(
                symbol=symbol,
                trade_date=datetime(2026, 7, day),
                main_net=main_net,
                provider="unit",
            )
        )
    test_db.commit()

    pack = context_builder.build_stock_context_pack(
        symbol,
        as_of=datetime(2026, 7, 5),
        sections=["fund_flow"],
        db=test_db,
    )

    assert pack["fund_flow"]["recent5_main_net"] is None


def test_m61_fund_flow_features_use_last_five_valid_values_and_keep_zero():
    from backend.tools.m61_quant_features import _fund_flow_features

    rows = [
        _flow_row(day, main_net)
        for day, main_net in ((1, 100.0), (2, None), (3, 0.0), (4, -50.0), (5, 25.0), (6, 75.0))
    ]

    features = _fund_flow_features(rows, datetime(2026, 7, 6))

    assert features["main_net_5d_sum"] == 150.0


def test_m61_fund_flow_features_require_five_valid_values():
    from math import isnan

    from backend.tools.m61_quant_features import _fund_flow_features

    rows = [
        _flow_row(day, main_net)
        for day, main_net in ((1, None), (2, 0.0), (3, 10.0), (4, -5.0), (5, 20.0))
    ]

    features = _fund_flow_features(rows, datetime(2026, 7, 5))

    assert isnan(features["main_net_5d_sum"])


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


def test_piotroski_analyst_denominator_9_behavior_is_unchanged(monkeypatch):
    import backend.agents.long_term.piotroski_analyst as analyst

    monkeypatch.setattr(analyst.settings, "long_term_piotroski_enabled", True)
    monkeypatch.setattr(analyst.settings, "piotroski_strong_threshold", 7)
    monkeypatch.setattr(analyst.settings, "piotroski_weak_threshold", 4)
    monkeypatch.setattr(analyst, "build_stock_context_pack", lambda *args, **kwargs: {})
    monkeypatch.setattr(analyst, "render_context_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(analyst, "lookup_caveat", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analyst,
        "compute_piotroski_factors",
        lambda symbol, db: {
            "available": True,
            "score": 7,
            "score_denominator": 9,
            "factors": {"roa_positive": True},
            "report_period": "2026-03-31",
            "comparison_period": "2025-03-31",
            "raw": {},
        },
    )

    report = analyst.analyze("300548", db=None)

    assert report.label_vote == "值得持有"
    assert report.score == 55.6
    assert "7/9" in report.key_findings[0]


def test_piotroski_analyst_uses_normalized_denominator_for_vote_score_and_text(monkeypatch):
    import backend.agents.long_term.piotroski_analyst as analyst

    monkeypatch.setattr(analyst.settings, "long_term_piotroski_enabled", True)
    monkeypatch.setattr(analyst.settings, "piotroski_strong_threshold", 7)
    monkeypatch.setattr(analyst.settings, "piotroski_weak_threshold", 5)
    monkeypatch.setattr(analyst, "build_stock_context_pack", lambda *args, **kwargs: {})
    monkeypatch.setattr(analyst, "render_context_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(analyst, "lookup_caveat", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analyst,
        "compute_piotroski_factors",
        lambda symbol, db: {
            "available": True,
            "score": 5,
            "score_denominator": 8,
            "factors": {"roa_positive": True, "no_new_shares": None},
            "report_period": "2026-03-31",
            "comparison_period": "2025-03-31",
            "raw": {},
        },
    )

    report = analyst.analyze("300548", db=None)

    assert report.label_vote == "观望"
    assert report.score == 25.0
    assert "5/8" in report.key_findings[0]
    assert "股本历史缺失" in report.key_findings[0]


def test_piotroski_analyst_zero_denominator_degrades_to_watch(monkeypatch):
    import backend.agents.long_term.piotroski_analyst as analyst

    monkeypatch.setattr(analyst.settings, "long_term_piotroski_enabled", True)
    monkeypatch.setattr(analyst, "build_stock_context_pack", lambda *args, **kwargs: {})
    monkeypatch.setattr(analyst, "render_context_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(analyst, "lookup_caveat", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        analyst,
        "compute_piotroski_factors",
        lambda symbol, db: {
            "available": True,
            "score": 0,
            "score_denominator": 0,
            "factors": {"roa_positive": None},
            "report_period": "2026-03-31",
            "comparison_period": "2025-03-31",
            "raw": {},
        },
    )

    report = analyst.analyze("300548", db=None)

    assert report.label_vote == "观望"
    assert report.score == 0
    assert any("财务数据不足" in finding for finding in report.key_findings)
