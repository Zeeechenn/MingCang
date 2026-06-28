from datetime import datetime, timedelta

import pytest

from backend.data.news_clustering import EventCluster
from backend.data.news_evidence import NewsEvidence
from backend.data.news_extraction import ClusterScore

BASE_TIME = datetime(2026, 6, 28, 9, 30, 0)


def _evidence(
    title: str = "兆易创新签署存储芯片采购合同",
    *,
    url: str = "https://example.com/a",
    provider: str = "eastmoney",
    content: str | None = "正文",
) -> NewsEvidence:
    return NewsEvidence(
        symbol="603986",
        title=title,
        url=url,
        published_at=BASE_TIME,
        source_name=provider,
        provider=provider,
        content=content,
    )


def _cluster(
    cluster_id: str,
    *,
    first_seen: datetime = BASE_TIME,
    source_diversity: int = 1,
    title_only: bool = False,
) -> EventCluster:
    return EventCluster(
        cluster_id=cluster_id,
        symbol="603986",
        members=[_evidence(content=None if title_only else "正文")],
        event_type="contract",
        representative_title="兆易创新签署存储芯片采购合同",
        source_diversity=source_diversity,
        entities=["603986", "兆易创新"],
        first_seen=first_seen,
    )


def _score(
    *,
    sentiment: float,
    materiality: float = 1.0,
    relevance: float = 1.0,
    confidence: float = 0.8,
    content_depth_used: str = "full",
) -> ClusterScore:
    return ClusterScore(
        relevance=relevance,
        sentiment=sentiment,
        materiality=materiality,
        horizon="short",
        event_type="contract",
        catalysts=[],
        risks=[],
        evidence_refs=[],
        confidence=confidence,
        content_depth_used=content_depth_used,  # type: ignore[arg-type]
    )


def test_fuse_signal_weighted_news_score_uses_freshness_and_diversity():
    from backend.data.news_fusion import fuse_signal

    signal = fuse_signal(
        [
            _score(sentiment=0.6),
            _score(sentiment=-0.2),
        ],
        [
            _cluster("fresh_one_source", first_seen=BASE_TIME, source_diversity=1),
            _cluster("old_three_sources", first_seen=BASE_TIME - timedelta(days=3), source_diversity=3),
        ],
        BASE_TIME,
        flow_value=None,
        flow_provider=lambda _symbol, _as_of: None,
    )

    assert signal.news_score == pytest.approx(0.12)
    assert signal.flow_score is None
    assert signal.contributing_clusters == ["fresh_one_source", "old_three_sources"]
    assert "FLOW_MISSING" in signal.degradation_flags


def test_fuse_signal_same_sign_raises_confidence():
    from backend.data.news_fusion import (
        ALIGNMENT_CONFIDENCE_BONUS,
        FLOW_CONFIDENCE,
        fuse_signal,
    )

    signal = fuse_signal(
        [_score(sentiment=0.6, confidence=0.8)],
        [_cluster("positive", source_diversity=3)],
        BASE_TIME,
        flow_value=0.4,
    )

    expected = ((0.8 * 0.6) + (FLOW_CONFIDENCE * 0.4)) / (0.8 + FLOW_CONFIDENCE)
    assert signal.composite == pytest.approx(expected)
    assert signal.confidence == pytest.approx(((0.8 + FLOW_CONFIDENCE) / 2) + ALIGNMENT_CONFIDENCE_BONUS)
    assert signal.degradation_flags == []


def test_fuse_signal_opposite_sign_lowers_confidence_and_shrinks_composite():
    from backend.data.news_fusion import (
        DIVERGENCE_COMPOSITE_SHRINK,
        DIVERGENCE_CONFIDENCE_MULTIPLIER,
        FLOW_CONFIDENCE,
        fuse_signal,
    )

    signal = fuse_signal(
        [_score(sentiment=0.6, confidence=0.8)],
        [_cluster("conflict", source_diversity=3)],
        BASE_TIME,
        flow_value=-0.4,
    )

    weighted = ((0.8 * 0.6) + (FLOW_CONFIDENCE * -0.4)) / (0.8 + FLOW_CONFIDENCE)
    assert signal.composite == pytest.approx(weighted * DIVERGENCE_COMPOSITE_SHRINK)
    assert signal.confidence == pytest.approx(((0.8 + FLOW_CONFIDENCE) / 2) * DIVERGENCE_CONFIDENCE_MULTIPLIER)
    assert "SIGNAL_DIVERGENCE" in signal.degradation_flags


def test_fuse_signal_single_news_channel_flags_missing_flow_and_discounts_confidence():
    from backend.data.news_fusion import (
        FLOW_MISSING_CONFIDENCE_MULTIPLIER,
        SINGLE_CHANNEL_CONFIDENCE_MULTIPLIER,
        fuse_signal,
    )

    signal = fuse_signal(
        [_score(sentiment=0.5, confidence=0.8)],
        [_cluster("news_only", source_diversity=3)],
        BASE_TIME,
        flow_provider=lambda _symbol, _as_of: None,
    )

    assert signal.composite == pytest.approx(0.5)
    assert signal.news_score == pytest.approx(0.5)
    assert signal.flow_score is None
    assert signal.confidence == pytest.approx(
        0.8 * SINGLE_CHANNEL_CONFIDENCE_MULTIPLIER * FLOW_MISSING_CONFIDENCE_MULTIPLIER
    )
    assert signal.degradation_flags == ["FLOW_MISSING"]


def test_fuse_signal_all_title_only_flags_news_thin_without_zero_pollution():
    from backend.data.news_fusion import (
        ALIGNMENT_CONFIDENCE_BONUS,
        FLOW_CONFIDENCE,
        NEWS_THIN_CONFIDENCE_MULTIPLIER,
        TITLE_ONLY_CLUSTER_CONFIDENCE_MULTIPLIER,
        fuse_signal,
    )

    signal = fuse_signal(
        [_score(sentiment=-0.3, confidence=0.4, content_depth_used="title_only")],
        [_cluster("title_only", title_only=True, source_diversity=1)],
        BASE_TIME,
        flow_value=-0.2,
    )

    assert signal.news_score == pytest.approx(-0.3)
    assert signal.composite < 0.0
    news_confidence = (
        0.4 * TITLE_ONLY_CLUSTER_CONFIDENCE_MULTIPLIER * NEWS_THIN_CONFIDENCE_MULTIPLIER
    )
    assert signal.confidence == pytest.approx(
        ((news_confidence + FLOW_CONFIDENCE) / 2) + ALIGNMENT_CONFIDENCE_BONUS
    )
    assert signal.degradation_flags == ["NEWS_THIN"]


def test_fuse_signal_uses_injected_flow_provider_without_default_network_call():
    from backend.data.news_fusion import fuse_signal

    calls: list[tuple[str, datetime]] = []

    def flow_provider(symbol: str, as_of: datetime) -> float:
        calls.append((symbol, as_of))
        return -0.25

    signal = fuse_signal([], [], BASE_TIME, symbol="603986", flow_provider=flow_provider)

    assert calls == [("603986", BASE_TIME)]
    assert signal.news_score is None
    assert signal.flow_score == -0.25
    assert signal.composite == -0.25
    assert "NEWS_THIN" in signal.degradation_flags


def test_fuse_signal_both_missing_is_degraded_low_confidence_and_neutral_only_for_exclusion():
    from backend.data.news_fusion import DEGRADED_CONFIDENCE_FLOOR, fuse_signal

    signal = fuse_signal(
        [],
        [],
        BASE_TIME,
        flow_provider=lambda _symbol, _as_of: None,
    )

    assert signal.composite == 0.0
    assert signal.news_score is None
    assert signal.flow_score is None
    assert signal.confidence == DEGRADED_CONFIDENCE_FLOOR
    assert signal.degradation_flags == ["NEWS_THIN", "FLOW_MISSING", "DEGRADED"]
