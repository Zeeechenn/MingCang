from dataclasses import fields
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from backend.data.news_clustering import EventCluster
from backend.data.news_evidence import NewsEvidence

BASE_TIME = datetime(2026, 6, 28, 9, 30, 0)


def _evidence(
    title: str,
    *,
    url: str,
    content: str | None = None,
    provider: str = "eastmoney",
    minutes: int = 0,
    symbol: str = "603986",
) -> NewsEvidence:
    return NewsEvidence(
        symbol=symbol,
        title=title,
        url=url,
        published_at=BASE_TIME + timedelta(minutes=minutes),
        source_name=provider,
        provider=provider,
        content=content,
    )


def _cluster(
    *,
    title: str = "兆易创新签署存储芯片采购合同",
    event_type: str = "contract",
    entities: list[str] | None = None,
    members: list[NewsEvidence] | None = None,
    source_diversity: int = 1,
    symbol: str = "603986",
) -> EventCluster:
    cluster_members = members or [
        _evidence(title, url="https://example.com/a", symbol=symbol),
    ]
    return EventCluster(
        cluster_id="evt_603986_test",
        symbol=symbol,
        members=cluster_members,
        event_type=event_type,
        representative_title=title,
        source_diversity=source_diversity,
        entities=entities if entities is not None else [symbol, "兆易创新"],
        first_seen=BASE_TIME,
    )


def test_prescreen_cluster_routes_material_contract_to_full_extraction():
    from backend.data.news_extraction import prescreen_cluster

    decision = prescreen_cluster(_cluster())

    assert decision["upgrade"] is True
    assert decision["relevance"] >= 0.7
    assert decision["materiality"] >= 0.7
    assert decision["upgrade_reasons"]


def test_cluster_score_schema_matches_m54_spec():
    from backend.data.news_extraction import ClusterScore

    assert [field.name for field in fields(ClusterScore)] == [
        "relevance",
        "sentiment",
        "materiality",
        "horizon",
        "event_type",
        "catalysts",
        "risks",
        "evidence_refs",
        "confidence",
        "content_depth_used",
    ]


def test_extract_cluster_full_uses_mocked_provider_and_preserves_schema():
    from backend.data.news_extraction import extract_cluster_full

    provider = MagicMock()
    provider.complete_structured.return_value = {
        "relevance": 0.92,
        "sentiment": 0.55,
        "materiality": 0.86,
        "horizon": "medium",
        "event_type": "contract",
        "catalysts": ["存储芯片订单落地"],
        "risks": ["交付节奏不确定"],
        "confidence": 0.78,
    }
    cluster = _cluster(
        members=[
            _evidence(
                "兆易创新签署存储芯片采购合同",
                url="https://example.com/a",
                content="兆易创新公告，公司与客户签署存储芯片采购合同，预计未来十二个月交付。",
            ),
            _evidence(
                "兆易创新获存储芯片订单",
                url="https://example.com/b",
                content="订单金额较大，但存在交付和客户验收风险。",
                provider="anspire",
                minutes=2,
            ),
        ],
        source_diversity=2,
    )

    with patch("backend.data.news_extraction.get_provider", return_value=provider):
        score = extract_cluster_full(cluster, tier="capable")

    assert score.relevance == 0.92
    assert score.sentiment == 0.55
    assert score.materiality == 0.86
    assert score.horizon == "medium"
    assert score.event_type == "contract"
    assert score.catalysts == ["存储芯片订单落地"]
    assert score.risks == ["交付节奏不确定"]
    assert score.evidence_refs == ["https://example.com/a", "https://example.com/b"]
    assert score.confidence == 0.78
    assert score.content_depth_used == "full"
    provider.complete_structured.assert_called_once()
    call = provider.complete_structured.call_args.kwargs
    assert call["model_tier"] == "capable"
    assert "兆易创新公告" in call["prompt"]
    assert call["tool"]["input_schema"]["required"] == [
        "relevance",
        "sentiment",
        "materiality",
        "horizon",
        "event_type",
        "catalysts",
        "risks",
        "confidence",
    ]


def test_score_cluster_title_only_does_not_call_provider_and_discounts_confidence():
    from backend.data.news_extraction import (
        TITLE_ONLY_CONFIDENCE_DISCOUNT,
        score_cluster_title_only,
    )

    score = score_cluster_title_only(
        _cluster(
            title="兆易创新获机构关注",
            event_type="opinion",
            entities=["半导体"],
            source_diversity=1,
        )
    )

    assert score.content_depth_used == "title_only"
    assert score.evidence_refs == ["https://example.com/a"]
    assert score.confidence <= TITLE_ONLY_CONFIDENCE_DISCOUNT
    assert score.materiality < 0.7


def test_extract_clusters_routes_full_and_title_only_without_real_llm():
    from backend.data.news_extraction import extract_clusters

    provider = MagicMock()
    provider.complete_structured.return_value = {
        "relevance": 0.8,
        "sentiment": -0.4,
        "materiality": 0.82,
        "horizon": "short",
        "event_type": "regulatory",
        "catalysts": ["回购稳定预期"],
        "risks": ["监管事项扰动"],
        "confidence": 0.7,
    }
    full_cluster = _cluster(
        title="兆易创新发布回购公告",
        event_type="regulatory",
        members=[
            _evidence(
                "兆易创新发布回购公告",
                url="https://example.com/full",
                content="公司公告拟回购股份，金额区间明确。",
            )
        ],
    )
    title_cluster = _cluster(
        title="半导体板块震荡走弱",
        event_type="unknown",
        entities=["半导体"],
        members=[_evidence("半导体板块震荡走弱", url="https://example.com/title")],
    )

    with patch("backend.data.news_extraction.get_provider", return_value=provider):
        scores = extract_clusters([full_cluster, title_cluster], tier="capable")

    assert [score.content_depth_used for score in scores] == ["full", "title_only"]
    assert [score.evidence_refs for score in scores] == [
        ["https://example.com/full"],
        ["https://example.com/title"],
    ]
    provider.complete_structured.assert_called_once()
