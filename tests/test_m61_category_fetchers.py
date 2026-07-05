from __future__ import annotations

import json
import sys
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd


def test_ifind_notice_maps_payload(monkeypatch):
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

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
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

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
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

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


def test_ifind_events_maps_payload_and_classifies(monkeypatch):
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

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
                                    "事件名称": "兆易创新限售股解禁",
                                    "事件日期": "20260616",
                                    "事件内容": "限售股份上市流通",
                                },
                                {
                                    "事件名称": "股份回购进展",
                                    "日期": "2026-05-20",
                                    "详情": "公司回购股份",
                                },
                                {
                                    "事件名称": "监管警示函",
                                    "日期": "2026-04-10",
                                    "详情": "交易所监管警示",
                                },
                                {
                                    "事件名称": "定向增发预案",
                                    "日期": "2026-03-01",
                                    "详情": "拟增发股份",
                                },
                                {
                                    "事件名称": "年度分红派息",
                                    "日期": "2026-02-01",
                                    "详情": "现金分红",
                                },
                                {
                                    "事件名称": "并购重组事项",
                                    "日期": "2026-01-15",
                                    "详情": "重大资产重组",
                                },
                                {
                                    "事件名称": "管理层变动",
                                    "日期": "2026-01-02",
                                    "详情": "董事辞任",
                                },
                                {
                                    "事件名称": "未来解禁",
                                    "日期": "2026-09-30",
                                    "详情": "不在请求窗口",
                                },
                            ],
                            ensure_ascii=False,
                        )
                    }
                },
                ensure_ascii=False,
            )
            return SimpleNamespace(text=text)

    monkeypatch.setattr(fetchers, "IfindMcpClient", FakeClient)

    rows = fetchers.fetch_corporate_events_ifind(
        FetchRequest(
            symbol="603986",
            start=date(2026, 1, 1),
            end=date(2026, 7, 4),
            extra={"name": "兆易创新"},
        )
    )

    assert calls[0][1] == "get_stock_events"
    assert calls[0][2] == {
        "query": "兆易创新(603986) 2026-01-01至2026-07-04 解禁 定增 回购 监管处罚 分红 并购重组 事件"
    }
    assert [row["event_type"] for row in rows] == ["解禁", "回购", "监管", "定增", "分红", "并购", "其他"]
    assert rows[0]["event_date"] == datetime(2026, 6, 16)
    assert rows[0]["title"] == "兆易创新限售股解禁"
    assert rows[0]["detail"] == "限售股份上市流通"
    assert rows[0]["provider"] == "ifind_events"


def _ifind_shareholder_markdown(rows):
    headers = ["证券代码", "证券简称", "日期", "前十大股东持股数量合计", "总股本", "前十大持股比例合计"]
    for rank in range(1, 11):
        headers.extend(
            [
                f"第{rank}名股东名称",
                f"第{rank}名股东持股数量",
                f"第{rank}名股东持股比例",
                f"第{rank}名股东持股股份性质",
                f"第{rank}名股东性质",
            ]
        )
    lines = [
        "|" + "|".join(headers) + "|",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        cells = list(row[: len(headers)])
        cells.extend(["\t"] * (len(headers) - len(cells)))
        lines.append("|" + "|".join(cells) + "|")
    return "\n".join(lines)


def test_ifind_shareholders_maps_real_table_periods_and_converts_units(monkeypatch):
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

    calls = []
    answer = _ifind_shareholder_markdown(
        [
            [
                "300548",
                "博创科技",
                "20260930",
                "1.23亿",
                "2.9157亿",
                "42.1",
                "未来一号",
                "3000万",
                "10.29",
                "流通A股",
                "境内非国有法人",
                "未来二号",
                "2000万",
                "6.86",
                "流通A股",
                "境内自然人",
            ],
            [
                "300548",
                "博创科技",
                "20260630",
                "1.20亿",
                "2.9157亿",
                "41.2",
                "半年一号",
                "3000万",
                "10.29",
                "流通A股",
                "境内非国有法人",
                "半年二号",
                "2000万",
                "6.86",
                "流通A股",
                "境内自然人",
            ],
            [
                "300548",
                "博创科技",
                "20260331",
                "1.10亿",
                "2.9157亿",
                "37.72",
                "第一大股东",
                "5538.4099万",
                "18.99",
                "限售流通A股",
                "境内非国有法人",
                "第二大股东",
                "2000万",
                "6.86",
                "流通A股",
                "境内自然人",
                "第三大股东",
                "1000万",
                "3.43",
                "流通A股",
                "基金",
                "第四大股东",
                "900万",
                "3.09",
                "流通A股",
                "其他",
                "第五大股东",
                "800万",
                "2.74",
                "流通A股",
                "其他",
                "第六大股东",
                "700万",
                "2.40",
                "流通A股",
                "其他",
                "第七大股东",
                "600万",
                "2.06",
                "流通A股",
                "其他",
                "第八大股东",
                "500万",
                "1.71",
                "流通A股",
                "其他",
                "第九大股东",
                "400万",
                "1.37",
                "流通A股",
                "其他",
                "第十大股东",
                "300万",
                "1.03",
                "流通A股",
                "其他",
            ],
            [
                "300548",
                "博创科技",
                "20251231",
                "1.00亿",
                "2.8000亿",
                "35.71",
                "年报一号",
                "5000万",
                "17.86",
                "流通A股",
                "境内非国有法人",
                "年报二号",
                "1000万",
                "3.57",
                "流通A股",
                "境内自然人",
                "年报三号",
                "900万",
                "3.21",
                "流通A股",
                "其他",
                "年报四号",
                "800万",
                "2.86",
                "流通A股",
                "其他",
                "年报五号",
                "700万",
                "2.50",
                "流通A股",
                "其他",
                "年报六号",
                "600万",
                "2.14",
                "流通A股",
                "其他",
                "年报七号",
                "500万",
                "1.79",
                "流通A股",
                "其他",
                "年报八号",
                "400万",
                "1.43",
                "流通A股",
                "其他",
                "年报九号",
                "300万",
                "1.07",
                "流通A股",
                "其他",
                "年报十号",
                "200万",
                "0.71",
                "流通A股",
                "其他",
            ],
        ]
    )

    class FakeClient:
        def call_tool(self, mcp_id, name, arguments):
            calls.append((mcp_id, name, arguments))
            text = json.dumps(
                {"data": {"answer": answer}},
                ensure_ascii=False,
            )
            return SimpleNamespace(text=text)

    monkeypatch.setattr(fetchers, "IfindMcpClient", FakeClient)
    monkeypatch.setattr(fetchers, "_utcnow", lambda: datetime(2026, 5, 15, 12, 0))

    rows = fetchers.fetch_holders_ifind_shareholders(
        FetchRequest(
            symbol="300548",
            start=date(2026, 1, 1),
            end=date(2026, 7, 4),
            extra={"name": "博创科技"},
        )
    )

    assert calls[0][1] == "get_stock_shareholders"
    assert calls[0][2] == {"query": "博创科技(300548) 最新股本结构与前十大股东"}
    assert [row["report_date"] for row in rows] == [datetime(2026, 3, 31), datetime(2025, 12, 31)]
    assert rows[0]["symbol"] == "300548"
    assert rows[0]["total_shares"] == 291_570_000.0
    assert rows[0]["float_shares"] is None
    assert rows[0]["holder_count"] is None
    assert rows[0]["provider"] == "ifind_shareholders"
    assert json.loads(rows[0]["top10_json"])[0] == {
        "name": "第一大股东",
        "shares": 55_384_099.0,
        "pct": 18.99,
        "nature": "限售流通A股",
    }
    assert json.loads(rows[1]["top10_json"])[0] == {
        "name": "年报一号",
        "shares": 50_000_000.0,
        "pct": 17.86,
        "nature": "流通A股",
    }


def test_ifind_shareholders_undated_uses_fetch_date_provider_suffix(monkeypatch):
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

    class FakeClient:
        def call_tool(self, mcp_id, name, arguments):
            text = json.dumps(
                {"data": {"data": json.dumps([{"总股本": "10000股"}], ensure_ascii=False)}},
                ensure_ascii=False,
            )
            return SimpleNamespace(text=text)

    monkeypatch.setattr(fetchers, "IfindMcpClient", FakeClient)
    monkeypatch.setattr(fetchers, "_utcnow", lambda: datetime(2026, 7, 4, 12, 30))

    rows = fetchers.fetch_holders_ifind_shareholders(
        FetchRequest(symbol="300548", start=None, end=None, extra={"name": "博创科技"})
    )

    assert rows[0]["report_date"] == datetime(2026, 7, 4)
    assert rows[0]["provider"] == "ifind_shareholders_undated"
    assert rows[0]["total_shares"] == 10000.0


def test_eastmoney_fflow_history_maps_fixture_and_filters(monkeypatch):
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2026-06-30,100,10,20,30,40,1,2,3,4,5,6,7,8,9",
                        "2026-07-01,200,11,21,31,41,1,2,3,4,5,6,7,8,9",
                    ]
                }
            }

    def fake_get(url, params, headers, timeout):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(fetchers.requests, "get", fake_get)
    monkeypatch.setattr(fetchers, "_utcnow", lambda: datetime(2026, 7, 5, 9, 0))
    monkeypatch.setattr(fetchers._EASTMONEY_THROTTLE, "wait", lambda: None)

    rows = fetchers.fetch_fund_flow_eastmoney_fflow_history(
        FetchRequest(symbol="603986", start=date(2026, 7, 1), end=date(2026, 7, 4), limit=120)
    )

    assert captured["url"] == fetchers.EASTMONEY_FFLOW_HISTORY_URL
    assert captured["params"]["secid"] == "1.603986"
    assert captured["params"]["lmt"] == "120"
    assert captured["params"]["fields2"] == fetchers.EASTMONEY_FFLOW_HISTORY_FIELDS2
    assert captured["headers"]["Referer"] == "https://quote.eastmoney.com"
    assert captured["headers"]["Origin"] == "https://quote.eastmoney.com"
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_date"] == datetime(2026, 7, 1)
    assert row["main_net"] == 200.0
    assert row["small_net"] == 11.0
    assert row["medium_net"] == 21.0
    assert row["large_net"] == 31.0
    assert row["super_large_net"] == 41.0
    assert row["provider"] == "eastmoney_fflow_history"


def test_sina_moneyflow_history_maps_fixture_and_filters(monkeypatch):
    import backend.data.category_fetchers as fetchers
    from backend.data.category_registry import FetchRequest

    captured = {}

    class FakeResponse:
        text = (
            '[{"opendate":"2026-07-01","r0_net":"100.5","r1_net":"-40.5",'
            '"r2_net":"7.0","r3_net":"-3.0"},'
            '{"opendate":"2026-06-30","r0_net":"11.0","r1_net":"22.0",'
            '"r2_net":"1.0","r3_net":"2.0"}]'
        )

        def raise_for_status(self):
            return None

    def fake_get(url, params, headers, timeout):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(fetchers.requests, "get", fake_get)
    monkeypatch.setattr(fetchers, "_utcnow", lambda: datetime(2026, 7, 6, 9, 0))
    monkeypatch.setattr(fetchers._SINA_THROTTLE, "wait", lambda: None)

    rows = fetchers.fetch_fund_flow_sina_history(
        FetchRequest(symbol="300759", start=date(2026, 7, 1), end=date(2026, 7, 4), limit=120)
    )

    assert captured["url"] == fetchers.SINA_MONEYFLOW_HISTORY_URL
    assert captured["params"]["daima"] == "sz300759"
    assert captured["params"]["num"] == "120"
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_date"] == datetime(2026, 7, 1)
    assert row["super_large_net"] == 100.5
    assert row["large_net"] == -40.5
    assert row["main_net"] == 60.0
    assert row["medium_net"] == 7.0
    assert row["small_net"] == -3.0
    assert row["provider"] == "sina_moneyflow_history"


def test_sina_daima_prefixes():
    import backend.data.category_fetchers as fetchers

    assert fetchers._sina_daima("601869") == "sh601869"
    assert fetchers._sina_daima("300759") == "sz300759"
    assert fetchers._sina_daima("002821") == "sz002821"
    assert fetchers._sina_daima("830799") == "bj830799"


def test_save_helpers_are_idempotent(test_db):
    from backend.data.category_fetchers import (
        save_announcements,
        save_corporate_events,
        save_fund_flows,
        save_holder_snapshots,
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
    event_rows = [
        {
            "symbol": "300308",
            "event_type": "回购",
            "title": "回购A",
            "event_date": datetime(2026, 6, 1),
            "detail": "详情",
            "provider": "ifind_events",
        }
    ]
    holder_rows = [
        {
            "symbol": "300308",
            "report_date": datetime(2026, 3, 31),
            "total_shares": 10000.0,
            "float_shares": 8000.0,
            "top10_json": None,
            "holder_count": 123,
            "provider": "ifind_shareholders",
        }
    ]
    flow_rows = [
        {
            "symbol": "300308",
            "trade_date": datetime(2026, 6, 1),
            "main_net": 1.0,
            "super_large_net": 2.0,
            "large_net": 3.0,
            "medium_net": 4.0,
            "small_net": 5.0,
            "provider": "eastmoney_fflow",
        }
    ]
    history_flow_rows = [{**flow_rows[0], "provider": "eastmoney_fflow_history", "main_net": 99.0}]

    assert save_announcements(announcement_rows, test_db) == 1
    assert save_announcements(announcement_rows, test_db) == 0
    assert save_research_reports(report_rows, test_db) == 1
    assert save_research_reports(report_rows, test_db) == 0
    assert save_lhb(lhb_rows, test_db) == 1
    assert save_lhb(lhb_rows, test_db) == 0
    assert save_corporate_events(event_rows, test_db) == 1
    assert save_corporate_events(event_rows, test_db) == 0
    assert save_holder_snapshots(holder_rows, test_db) == 1
    assert save_holder_snapshots(holder_rows, test_db) == 0
    assert save_fund_flows(flow_rows, test_db) == 1
    assert save_fund_flows(flow_rows, test_db) == 0
    assert save_fund_flows(history_flow_rows, test_db) == 0


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


def test_backfill_does_not_turn_coverage_gap_into_fetch_failed(monkeypatch, test_db):
    from backend.data.category_registry import FetchResult
    from backend.tools import m61_backfill

    def fake_fetch_by_category(category, request, db=None):
        return FetchResult(
            ok=False,
            rows=[],
            provider=None,
            degradations=[
                {
                    "category": category,
                    "provider": "unit",
                    "error": "coverage_gap:empty",
                    "symbol": request.symbol,
                }
            ],
        )

    recorded: list[dict] = []
    monkeypatch.setattr(m61_backfill, "fetch_by_category", fake_fetch_by_category)
    monkeypatch.setattr(m61_backfill, "_record_degradation", lambda *args, **kwargs: recorded.append(args) or {})

    inserted, degradations = m61_backfill._backfill_stock_category(
        "research_reports",
        [{"symbol": "000001", "name": "平安银行"}],
        date(2026, 6, 1),
        date(2026, 6, 30),
        test_db,
    )

    assert inserted == 0
    assert recorded == []
    assert [row["error"] for row in degradations] == ["coverage_gap:empty"]
