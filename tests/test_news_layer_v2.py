from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.data.database import NewsItem

BASE_TIME = datetime(2026, 6, 28, 9, 30, 0)


def _news_item(
    *,
    symbol: str = "603986",
    title: str = "兆易创新签署存储芯片采购合同",
    url: str = "https://example.com/news",
    published_at: datetime = BASE_TIME,
    source: str = "东方财富",
    content: str | None = "兆易创新公告，公司与客户签署存储芯片采购合同。",
    provider: str | None = "eastmoney",
) -> NewsItem:
    return NewsItem(
        symbol=symbol,
        title=title,
        url=url,
        published_at=published_at,
        source=source,
        content=content,
        provider=provider,
    )


def test_news_v2_score_from_db_runs_end_to_end_with_mocked_llm(test_db):
    from backend.data.news_layer_v2 import news_v2_score_from_db

    provider = MagicMock()
    provider.complete_structured.return_value = {
        "relevance": 0.9,
        "sentiment": 0.6,
        "materiality": 0.85,
        "horizon": "medium",
        "event_type": "contract",
        "catalysts": ["存储芯片订单落地"],
        "risks": ["交付节奏不确定"],
        "confidence": 0.8,
    }
    test_db.add(
        _news_item(
            url="https://example.com/full",
            content="兆易创新公告，公司与客户签署存储芯片采购合同，预计未来十二个月交付。",
            published_at=BASE_TIME - timedelta(hours=1),
        )
    )
    test_db.commit()

    with patch("backend.data.news_extraction.get_provider", return_value=provider):
        signal = news_v2_score_from_db(
            "603986",
            BASE_TIME,
            3,
            test_db,
            tier="capable",
            flow_value=0.2,
        )

    assert signal.news_score == pytest.approx(0.6)
    assert signal.flow_score == 0.2
    assert signal.composite > 0.0
    assert signal.contributing_clusters
    assert signal.degradation_flags == []
    provider.complete_structured.assert_called_once()


def test_score_news_v2_empty_evidence_uses_fusion_degraded_path():
    from backend.data.news_fusion import DEGRADED, FLOW_MISSING, NEWS_THIN
    from backend.data.news_layer_v2 import score_news_v2

    signal = score_news_v2([], BASE_TIME)

    assert signal.composite == 0.0
    assert signal.news_score is None
    assert signal.flow_score is None
    assert signal.degradation_flags == [NEWS_THIN, FLOW_MISSING, DEGRADED]


def test_evidence_from_db_is_strictly_point_in_time_and_maps_content_provider(test_db):
    from backend.data.news_layer_v2 import evidence_from_db

    test_db.add_all(
        [
            _news_item(
                title="兆易创新发布回购公告",
                url="https://example.com/in-window-full",
                published_at=BASE_TIME,
                source="证券时报",
                content="  公司公告拟回购股份。  ",
                provider="anspire",
            ),
            _news_item(
                title="兆易创新未来新闻",
                url="https://example.com/future",
                published_at=BASE_TIME + timedelta(seconds=1),
                content="未来正文",
                provider="eastmoney",
            ),
            _news_item(
                title="兆易创新旧新闻",
                url="https://example.com/old",
                published_at=BASE_TIME - timedelta(days=4),
                content="旧正文",
                provider="eastmoney",
            ),
            _news_item(
                title="其他股票新闻",
                url="https://example.com/other-symbol",
                published_at=BASE_TIME,
                symbol="600519",
                content="其他正文",
                provider="eastmoney",
            ),
        ]
    )
    test_db.commit()

    evidence = evidence_from_db("603986", BASE_TIME, 3, test_db)

    assert len(evidence) == 1
    item = evidence[0]
    assert item.symbol == "603986"
    assert item.title == "兆易创新发布回购公告"
    assert item.url == "https://example.com/in-window-full"
    assert item.published_at == BASE_TIME
    assert item.source_name == "证券时报"
    assert item.provider == "anspire"
    assert item.content == "公司公告拟回购股份。"
    assert item.content_status == "full"
