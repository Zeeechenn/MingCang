import json
from datetime import datetime

import pytest

from backend.data.news_models import RawNews


def _raw_news(
    *,
    title: str,
    url: str,
    symbol: str = "603986",
    content: str | None,
    provider: str,
    published_at: datetime = datetime(2026, 6, 20, 9, 30, 0),
) -> RawNews:
    return RawNews(
        title=title,
        url=url,
        published_at=published_at,
        source=provider,
        symbol=symbol,
        content=content,
        provider=provider,
    )


def test_m54_content_backfill_ingests_mocked_fetches_and_reports_coverage(
    monkeypatch,
    tmp_path,
    test_db,
):
    from backend.tools import m54_content_backfill as tool

    universe = tmp_path / "universe.json"
    universe.write_text(
        json.dumps(
            {
                "stocks": [
                    {"symbol": "603986", "name": "兆易创新"},
                    {"symbol": "600519", "name": "贵州茅台"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_cn(symbol: str, limit: int) -> list[RawNews]:
        assert limit == 7
        if symbol == "600519":
            raise RuntimeError("network skipped")
        return [
            _raw_news(
                title="兆易创新发布回购公告",
                url="https://eastmoney.example/full",
                content="公司公告拟回购股份。",
                provider="eastmoney",
            ),
            _raw_news(
                title="兆易创新新闻标题摘要",
                url="https://eastmoney.example/empty",
                content=None,
                provider="eastmoney",
            ),
        ]

    def fake_anspire(symbol: str, name: str) -> list[RawNews]:
        assert (symbol, name) == ("603986", "兆易创新")
        return [
            _raw_news(
                title="兆易创新签署订单",
                url="https://anspire.example/full",
                content="订单正文。",
                provider="anspire",
            )
        ]

    monkeypatch.setattr(tool, "fetch_stock_news_cn", fake_cn)
    monkeypatch.setattr(tool, "fetch_stock_news_anspire", fake_anspire)

    result = tool.run_backfill(
        db=test_db,
        universe_path=universe,
        stock_limit=None,
        cn_limit=7,
    )

    assert result.stocks_total == 2
    assert result.stocks_processed == 1
    assert result.stocks_failed == 1
    assert result.inserted == 3

    report = tool.coverage_report(
        test_db,
        start=datetime(2026, 6, 1),
        end=datetime(2026, 6, 30, 23, 59, 59),
    )

    assert report["total"] == {"rows": 3, "with_content": 2, "coverage_pct": pytest.approx(66.67)}
    assert report["by_provider"] == {
        "anspire": {"rows": 1, "with_content": 1, "coverage_pct": pytest.approx(100.0)},
        "eastmoney": {"rows": 2, "with_content": 1, "coverage_pct": pytest.approx(50.0)},
    }
