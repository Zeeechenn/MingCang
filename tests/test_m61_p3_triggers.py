from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def _sqlite_db_from_session(test_db, tmp_path: Path) -> Path:
    path = tmp_path / "mingcang-test.sqlite3"
    raw = test_db.get_bind().raw_connection()
    dest = sqlite3.connect(path)
    try:
        raw.driver_connection.backup(dest)
    finally:
        dest.close()
        raw.close()
    return path


def _watchlist_dir(tmp_path: Path, symbol: str = "603986") -> Path:
    path = tmp_path / "watchlists"
    path.mkdir(exist_ok=True)
    (path / "semis.json").write_text(
        json.dumps(
            {
                "theme_key": "semis",
                "title": "半导体",
                "thesis": "unit",
                "symbols": [symbol],
                "validation_conditions": ["unit"],
                "invalidation_conditions": ["unit"],
                "created_at": "2026-07-03",
                "source_ref": "unit",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _seed_prices(test_db, symbol: str, as_of: str = "2026-07-03") -> None:
    from backend.data.database import Price, Stock

    test_db.add(Stock(symbol=symbol, name="兆易创新", market="CN", industry="半导体", active=True))
    start = datetime.fromisoformat(as_of) - timedelta(days=80)
    for idx in range(70):
        day = start + timedelta(days=idx)
        close = 50.0 + idx * 0.1
        test_db.add(
            Price(
                symbol=symbol,
                date=day.strftime("%Y-%m-%d"),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1000,
            )
        )
    test_db.commit()


def test_lhb_trigger_fires_on_seeded_row(test_db, tmp_path):
    from backend.data.database import LhbRecord
    from backend.tools.m60_watchtower import TRIGGER_LHB_APPEARANCE, build_watchtower_report

    _seed_prices(test_db, "603986")
    test_db.add(
        LhbRecord(
            symbol="603986",
            trade_date=datetime(2026, 7, 3),
            reason="日涨幅偏离值达7%",
            net_buy_amount=12345678.0,
            provider="unit",
        )
    )
    test_db.commit()

    report = build_watchtower_report(
        db_path=_sqlite_db_from_session(test_db, tmp_path),
        as_of="2026-07-03",
        watchlist_dir=_watchlist_dir(tmp_path),
    )

    triggers = [t for t in report["triggers"] if t["trigger_type"] == TRIGGER_LHB_APPEARANCE]
    assert len(triggers) == 1
    assert triggers[0]["symbol"] == "603986"
    assert triggers[0]["card"] == "龙虎榜上榜: 日涨幅偏离值达7%, 净买 12345678.0"


def test_lhb_trigger_silent_when_none(test_db, tmp_path):
    from backend.tools.m60_watchtower import TRIGGER_LHB_APPEARANCE, build_watchtower_report

    _seed_prices(test_db, "603986")

    report = build_watchtower_report(
        db_path=_sqlite_db_from_session(test_db, tmp_path),
        as_of="2026-07-03",
        watchlist_dir=_watchlist_dir(tmp_path),
    )

    assert all(t["trigger_type"] != TRIGGER_LHB_APPEARANCE for t in report["triggers"])


def test_fund_flow_zscore_trigger_and_silent_when_short(test_db, tmp_path):
    from backend.data.database import FundFlow
    from backend.tools.m60_watchtower import TRIGGER_FUND_FLOW_SURGE, build_watchtower_report

    _seed_prices(test_db, "603986")
    base = datetime(2026, 4, 1)
    for idx in range(60):
        baseline = 100.0 + (idx % 7) * 10.0
        test_db.add(
            FundFlow(
                symbol="603986",
                trade_date=base + timedelta(days=idx),
                main_net=baseline if idx < 55 else 1000.0,
                provider="unit",
            )
        )
    test_db.commit()

    report = build_watchtower_report(
        db_path=_sqlite_db_from_session(test_db, tmp_path),
        as_of=(base + timedelta(days=59)).strftime("%Y-%m-%d"),
        watchlist_dir=_watchlist_dir(tmp_path),
    )

    triggers = [t for t in report["triggers"] if t["trigger_type"] == TRIGGER_FUND_FLOW_SURGE]
    assert len(triggers) == 1
    assert triggers[0]["detail"]["rows_used"] == 60
    assert triggers[0]["value"] >= 2.0

    short_symbol = "300308"
    _seed_prices(test_db, short_symbol)
    for idx in range(24):
        test_db.add(
            FundFlow(
                symbol=short_symbol,
                trade_date=base + timedelta(days=idx),
                main_net=1000.0,
                provider="unit",
            )
        )
    test_db.commit()

    short_report = build_watchtower_report(
        db_path=_sqlite_db_from_session(test_db, tmp_path),
        as_of=(base + timedelta(days=23)).strftime("%Y-%m-%d"),
        watchlist_dir=_watchlist_dir(tmp_path, short_symbol),
    )
    assert all(t["trigger_type"] != TRIGGER_FUND_FLOW_SURGE for t in short_report["triggers"])


def test_overseas_fetcher_mapping(monkeypatch):
    from backend.data import category_fetchers as cf
    from backend.data.category_registry import FetchRequest

    calls: list[tuple[str, str, dict]] = []

    class Client:
        def call_tool(self, mcp_id, name, arguments):
            calls.append((mcp_id, name, arguments))

            class Result:
                text = """
| 日期 | 收盘价 | 涨跌幅 | 20日涨跌幅 | 换手率 |
|---|---:|---:|---:|---:|
| 2026-07-02 | 88.50 | 1.25 | 12.00 | 2.3 |
"""

            return Result()

    monkeypatch.setattr(cf, "_stock_ifind_client", lambda: Client())

    rows = cf.fetch_overseas_ifind_global(FetchRequest(symbol=None, start=None, end=None))

    assert len(rows) == 4
    first = rows[0]
    assert first["symbol"] == "MRVL"
    assert first["name"] == "Marvell"
    assert first["snap_date"] == datetime(2026, 7, 2)
    assert first["close"] == 88.5
    assert first["chg_pct_1d"] == 1.25
    assert first["chg_pct_20d"] == 12.0
    assert "换手率" in first["note"]
    assert calls[0][1] == "global_stock_quotes"


def test_panel_renders_overseas_line(test_db, tmp_path):
    from backend.data.database import OverseasSnapshot
    from backend.tools.m59_panel import build_panel, render_markdown

    test_db.add(
        OverseasSnapshot(
            symbol="MRVL",
            name="Marvell",
            snap_date=datetime(2026, 7, 2),
            close=88.5,
            chg_pct_1d=1.25,
            chg_pct_20d=12.0,
            provider="unit",
        )
    )
    test_db.commit()

    panel = build_panel(db_path=_sqlite_db_from_session(test_db, tmp_path), as_of="2026-07-03")
    markdown = render_markdown(panel)

    assert panel["overseas_reference"]["items"][0]["symbol"] == "MRVL"
    assert "MRVL(Marvell) 收 88.5 (1日 +1.25% / 20日 +12.0%)" in markdown


def test_m54_announcements_flag_controls_corpus(test_db, monkeypatch):
    from backend.data.database import Announcement, NewsItem
    from backend.data.news_layer_v2 import evidence_from_db

    as_of = datetime(2026, 7, 3, 23, 59, 59)
    test_db.add(
        NewsItem(
            symbol="603986",
            title="新闻标题",
            url="https://example.test/news",
            published_at=as_of - timedelta(days=1),
            source="unit",
            provider="unit",
            content="新闻正文",
        )
    )
    test_db.add(
        Announcement(
            symbol="603986",
            title="公告标题",
            content="公告正文",
            published_at=as_of - timedelta(days=1),
            source_url="https://example.test/ann",
            provider="unit",
        )
    )
    test_db.commit()

    default_evidence = evidence_from_db("603986", as_of, 3, test_db)
    augmented_evidence = evidence_from_db(
        "603986",
        as_of,
        3,
        test_db,
        include_announcements=True,
    )

    assert [item.title for item in default_evidence] == ["新闻标题"]
    assert [item.title for item in augmented_evidence] == ["新闻标题", "【公告】公告标题"]
    assert augmented_evidence[1].content == "【公告】公告正文"
