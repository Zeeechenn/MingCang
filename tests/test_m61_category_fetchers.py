from __future__ import annotations

import json
import sys
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd


def test_ifind_notice_maps_payload(monkeypatch):
    from backend.data.category_registry import FetchRequest
    import backend.data.category_fetchers as fetchers

    calls = []

    class FakeClient:
        def call_tool(self, mcp_id, name, arguments):
            calls.append((mcp_id, name, arguments))
            text = json.dumps(
                {
                    "data": {
                        "data": json.dumps(
                            [
                                {
                                    "公告标题": "长飞光纤：一季度报告",
                                    "公告内容": "营收增长",
                                    "公告类型": "定期报告",
                                    "日期": "2026-06-15",
                                    "URL": "https://example.test/a.pdf",
                                }
                            ],
                            ensure_ascii=False,
                        )
                    }
                },
                ensure_ascii=False,
            )
            return SimpleNamespace(text=text)

    monkeypatch.setattr(fetchers, "IfindMcpClient", FakeClient)

    rows = fetchers.fetch_announcements_ifind_notice(
        FetchRequest(
            symbol="601869",
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            limit=20,
            extra={"name": "长飞光纤"},
        )
    )

    assert calls[0][1] == "search_notice"
    assert calls[0][2] == {
        "query": "长飞光纤(601869) 公告 2026-06-01至2026-06-30",
        "time_start": "2026-06-01",
        "time_end": "2026-06-30",
        "size": 20,
    }
    assert rows[0]["symbol"] == "601869"
    assert rows[0]["title"] == "长飞光纤：一季度报告"
    assert rows[0]["content"] == "营收增长"
    assert rows[0]["ann_type"] == "定期报告"
    assert rows[0]["published_at"] == datetime(2026, 6, 15)
    assert rows[0]["source_url"] == "https://example.test/a.pdf"
    assert rows[0]["provider"] == "ifind_notice"


def test_eastmoney_reportapi_maps_payload(monkeypatch):
    from backend.data.category_registry import FetchRequest
    import backend.data.category_fetchers as fetchers

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "title": "中际旭创点评",
                        "orgSName": "测试证券",
                        "emRatingName": "买入",
                        "predictThisYearEps": "5.12",
                        "predictNextYearEps": "6.34",
                        "publishDate": "2026-06-20 08:00:00",
                        "infoCode": "AP202606200000001",
                    }
                ]
            }

    def fake_get(url, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(fetchers.requests, "get", fake_get)

    rows = fetchers.fetch_research_reports_eastmoney(
        FetchRequest(symbol="300308", start=date(2026, 6, 1), end=date(2026, 7, 4), limit=200)
    )

    assert captured["url"] == "https://reportapi.eastmoney.com/report/list"
    assert captured["params"]["code"] == "300308"
    assert captured["params"]["beginTime"] == "2026-06-01"
    assert captured["params"]["endTime"] == "2026-07-04"
    assert captured["params"]["pageSize"] == 100
    assert captured["timeout"] == 10
    assert rows == [
        {
            "symbol": "300308",
            "title": "中际旭创点评",
            "org_name": "测试证券",
            "rating": "买入",
            "eps_forecast_y1": 5.12,
            "eps_forecast_y2": 6.34,
            "publish_date": datetime(2026, 6, 20, 8, 0),
            "info_code": "AP202606200000001",
            "provider": "eastmoney_reportapi",
        }
    ]


def test_akshare_lhb_maps_and_filters_payload(monkeypatch):
    from backend.data.category_registry import FetchRequest
    import backend.data.category_fetchers as fetchers

    fake_ak = SimpleNamespace(
        stock_lhb_detail_em=lambda start_date, end_date: pd.DataFrame(
            [
                {
                    "代码": "300308",
                    "上榜日": "2026-06-18",
                    "上榜原因": "日涨幅偏离值达7%",
                    "龙虎榜净买额": "1234.5",
                    "龙虎榜买入额": "5000",
                    "龙虎榜卖出额": "3765.5",
                },
                {
                    "代码": "600519",
                    "上榜日": "2026-06-18",
                    "上榜原因": "测试",
                    "龙虎榜净买额": "1",
                },
            ]
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)

    rows = fetchers.fetch_lhb_akshare(
        FetchRequest(symbol="300308", start=date(2026, 6, 1), end=date(2026, 7, 4))
    )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "300308"
    assert rows[0]["trade_date"] == datetime(2026, 6, 18)
    assert rows[0]["reason"] == "日涨幅偏离值达7%"
    assert rows[0]["net_buy_amount"] == 1234.5
    assert json.loads(rows[0]["buy_seats_json"]) == {"龙虎榜买入额": "5000"}
    assert json.loads(rows[0]["sell_seats_json"]) == {"龙虎榜卖出额": "3765.5"}
    assert rows[0]["provider"] == "akshare_lhb"


def test_save_helpers_are_idempotent(test_db):
    from backend.data.category_fetchers import (
        save_announcements,
        save_lhb,
        save_research_reports,
    )

    announcement_rows = [
        {
            "symbol": "300308",
            "title": "公告A",
            "content": "正文",
            "ann_type": "临时公告",
            "published_at": datetime(2026, 6, 1),
            "source_url": None,
            "provider": "ifind_notice",
        }
    ]
    report_rows = [
        {
            "symbol": "300308",
            "title": "研报A",
            "org_name": "测试证券",
            "rating": None,
            "eps_forecast_y1": None,
            "eps_forecast_y2": None,
            "publish_date": datetime(2026, 6, 1),
            "info_code": None,
            "provider": "eastmoney_reportapi",
        }
    ]
    lhb_rows = [
        {
            "symbol": "300308",
            "trade_date": datetime(2026, 6, 1),
            "reason": "测试原因",
            "net_buy_amount": 1.0,
            "buy_seats_json": None,
            "sell_seats_json": None,
            "provider": "akshare_lhb",
        }
    ]

    assert save_announcements(announcement_rows, test_db) == 1
    assert save_announcements(announcement_rows, test_db) == 0
    assert save_research_reports(report_rows, test_db) == 1
    assert save_research_reports(report_rows, test_db) == 0
    assert save_lhb(lhb_rows, test_db) == 1
    assert save_lhb(lhb_rows, test_db) == 0


def test_backfill_continues_past_failing_stock(tmp_path, monkeypatch, test_db, capsys):
    from backend.tools import m61_backfill

    universe = tmp_path / "universe.json"
    universe.write_text(
        json.dumps(
            {
                "stocks": [
                    {"symbol": "000001", "name": "平安银行"},
                    {"symbol": "000002", "name": "万科A"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_fetch_by_category(category, request, db=None):
        calls.append(request.symbol)
        if request.symbol == "000001":
            raise RuntimeError("boom")
        return SimpleNamespace(
            ok=True,
            rows=[
                {
                    "symbol": request.symbol,
                    "title": "研报A",
                    "org_name": "测试证券",
                    "publish_date": datetime(2026, 6, 2),
                    "provider": "eastmoney_reportapi",
                }
            ],
            provider="eastmoney_reportapi",
            degradations=[],
        )

    monkeypatch.setattr(m61_backfill, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(m61_backfill, "fetch_by_category", fake_fetch_by_category)

    code = m61_backfill.main(
        [
            "--category",
            "research_reports",
            "--universe",
            str(universe),
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-30",
        ]
    )

    assert code == 0
    assert calls == ["000001", "000002"]
    summary = json.loads(capsys.readouterr().out)
    assert summary["category"] == "research_reports"
    assert summary["stocks"] == 2
    assert summary["inserted"] == 1
    assert len(summary["degradations"]) == 1
    assert summary["degradations"][0]["symbol"] == "000001"
