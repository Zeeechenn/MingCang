"""Observe-only deterministic M54 fusion from news clusters and real flow.

`DEGRADED` means both independent channels are missing. The returned neutral
`composite=0.0` is only a placeholder for callers to route or exclude the
window; `DEGRADED` rows should not enter the primary IC sample.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from operator import attrgetter
from typing import Any

from backend.data.news_clustering import EventCluster
from backend.data.news_extraction import ClusterScore

FRESHNESS_HALFLIFE_DAYS = 3.0
DIVERSITY_SATURATION = 3

NEWS_CHANNEL_WEIGHT = 1.0
FLOW_CHANNEL_WEIGHT = 1.0
FLOW_CONFIDENCE = 0.65

ALIGNMENT_CONFIDENCE_BONUS = 0.12
DIVERGENCE_CONFIDENCE_MULTIPLIER = 0.65
DIVERGENCE_COMPOSITE_SHRINK = 0.75

SINGLE_CHANNEL_CONFIDENCE_MULTIPLIER = 0.70
NEWS_THIN_CONFIDENCE_MULTIPLIER = 0.55
FLOW_MISSING_CONFIDENCE_MULTIPLIER = 0.75
TITLE_ONLY_CLUSTER_CONFIDENCE_MULTIPLIER = 0.65
DEGRADED_CONFIDENCE_FLOOR = 0.05

NEWS_THIN = "NEWS_THIN"
FLOW_MISSING = "FLOW_MISSING"
DEGRADED = "DEGRADED"
SIGNAL_DIVERGENCE = "SIGNAL_DIVERGENCE"

FlowProvider = Callable[[str, datetime], float | int | dict[str, Any] | object | None]


@dataclass
class NewsSignalV2:
    composite: float
    news_score: float | None
    flow_score: float | None
    confidence: float
    degradation_flags: list[str]
    contributing_clusters: list[str]
    # M54 阶段7 additive field. Only ever populated by the event-pyramid
    # orchestrator (backend.data.news_layer_v2) when news_v2_pyramid_enabled
    # is on and the symbol was L1-triggered that day. Left as the deterministic
    # AttributionCard from backend.data.news_trigger to avoid a fusion->trigger
    # import edge here; typed loosely (Any) so this module stays independent.
    attribution_card: Any | None = None


@dataclass(frozen=True)
class _NewsAggregate:
    score: float | None
    confidence: float
    contributing_clusters: list[str]
    all_title_only: bool


def fuse_signal(
    cluster_scores: Sequence[ClusterScore],
    clusters: Sequence[EventCluster],
    as_of: datetime,
    *,
    flow_value: float | int | dict[str, Any] | object | None = None,
    flow_provider: FlowProvider | None = None,
    symbol: str | None = None,
) -> NewsSignalV2:
    """Fuse cluster-level news scores with the independent M52 flow channel.

    Flow is injectable for tests and offline audits. When neither `flow_value`
    nor `flow_provider` is passed, this function attempts a lazy default read
    from `backend.tools.m52_flow_floor`; any failure degrades to `flow_score=None`
    instead of manufacturing a neutral flow signal.
    """
    if len(cluster_scores) != len(clusters):
        raise ValueError("cluster_scores and clusters must have the same length")

    flags: list[str] = []
    news = _aggregate_news(cluster_scores, clusters, as_of)
    if news.score is None or news.all_title_only:
        _append_flag(flags, NEWS_THIN)

    resolved_symbol = symbol or _infer_symbol(clusters)
    flow_score = _resolve_flow_score(
        flow_value=flow_value,
        flow_provider=flow_provider,
        symbol=resolved_symbol,
        as_of=as_of,
    )
    if flow_score is None:
        _append_flag(flags, FLOW_MISSING)

    if news.score is None and flow_score is None:
        _append_flag(flags, DEGRADED)
        return NewsSignalV2(
            composite=0.0,
            news_score=None,
            flow_score=None,
            confidence=DEGRADED_CONFIDENCE_FLOOR,
            degradation_flags=flags,
            contributing_clusters=[],
        )

    if news.score is None:
        confidence = FLOW_CONFIDENCE * SINGLE_CHANNEL_CONFIDENCE_MULTIPLIER
        confidence *= NEWS_THIN_CONFIDENCE_MULTIPLIER
        return NewsSignalV2(
            composite=flow_score if flow_score is not None else 0.0,
            news_score=None,
            flow_score=flow_score,
            confidence=_clamp(confidence, DEGRADED_CONFIDENCE_FLOOR, 1.0),
            degradation_flags=flags,
            contributing_clusters=[],
        )

    news_confidence = news.confidence
    if news.all_title_only:
        news_confidence *= NEWS_THIN_CONFIDENCE_MULTIPLIER

    if flow_score is None:
        confidence = news_confidence * SINGLE_CHANNEL_CONFIDENCE_MULTIPLIER
        confidence *= FLOW_MISSING_CONFIDENCE_MULTIPLIER
        return NewsSignalV2(
            composite=news.score,
            news_score=news.score,
            flow_score=None,
            confidence=_clamp(confidence, DEGRADED_CONFIDENCE_FLOOR, 1.0),
            degradation_flags=flags,
            contributing_clusters=news.contributing_clusters,
        )

    news_weight = NEWS_CHANNEL_WEIGHT * news_confidence
    flow_weight = FLOW_CHANNEL_WEIGHT * FLOW_CONFIDENCE
    composite = ((news_weight * news.score) + (flow_weight * flow_score)) / (
        news_weight + flow_weight
    )
    confidence = (news_confidence + FLOW_CONFIDENCE) / 2

    if _same_nonzero_sign(news.score, flow_score):
        confidence += ALIGNMENT_CONFIDENCE_BONUS
    elif _opposite_sign(news.score, flow_score):
        _append_flag(flags, SIGNAL_DIVERGENCE)
        confidence *= DIVERGENCE_CONFIDENCE_MULTIPLIER
        composite *= DIVERGENCE_COMPOSITE_SHRINK

    return NewsSignalV2(
        composite=_clamp(composite, -1.0, 1.0),
        news_score=news.score,
        flow_score=flow_score,
        confidence=_clamp(confidence, DEGRADED_CONFIDENCE_FLOOR, 1.0),
        degradation_flags=flags,
        contributing_clusters=news.contributing_clusters,
    )


def _aggregate_news(
    cluster_scores: Sequence[ClusterScore],
    clusters: Sequence[EventCluster],
    as_of: datetime,
) -> _NewsAggregate:
    weighted_sentiment = 0.0
    total_weight = 0.0
    weighted_confidence = 0.0
    contributing_clusters: list[str] = []

    for score, cluster in zip(cluster_scores, clusters, strict=True):
        weight = _cluster_weight(score, cluster, as_of)
        if weight <= 0.0:
            continue
        weighted_sentiment += score.sentiment * weight
        score_confidence = score.confidence
        if score.content_depth_used == "title_only":
            score_confidence *= TITLE_ONLY_CLUSTER_CONFIDENCE_MULTIPLIER
        weighted_confidence += score_confidence * weight
        total_weight += weight
        contributing_clusters.append(cluster.cluster_id)

    if total_weight <= 0.0:
        return _NewsAggregate(
            score=None,
            confidence=0.0,
            contributing_clusters=[],
            all_title_only=False,
        )

    return _NewsAggregate(
        score=_clamp(weighted_sentiment / total_weight, -1.0, 1.0),
        confidence=_clamp(weighted_confidence / total_weight, 0.0, 1.0),
        contributing_clusters=contributing_clusters,
        all_title_only=all(score.content_depth_used == "title_only" for score in cluster_scores),
    )


def _cluster_weight(score: ClusterScore, cluster: EventCluster, as_of: datetime) -> float:
    return (
        _clamp(score.materiality, 0.0, 1.0)
        * _clamp(score.relevance, 0.0, 1.0)
        * _freshness_decay(cluster.first_seen, as_of)
        * _diversity_weight(cluster.source_diversity)
    )


def _freshness_decay(first_seen: datetime, as_of: datetime) -> float:
    age_days = max((as_of - first_seen).total_seconds() / 86_400, 0.0)
    return 0.5 ** (age_days / FRESHNESS_HALFLIFE_DAYS)


def _diversity_weight(source_diversity: int) -> float:
    return _clamp(source_diversity / DIVERSITY_SATURATION, 0.0, 1.0)


def _resolve_flow_score(
    *,
    flow_value: float | int | dict[str, Any] | object | None,
    flow_provider: FlowProvider | None,
    symbol: str | None,
    as_of: datetime,
) -> float | None:
    if flow_value is not None:
        return _coerce_flow_value(flow_value)
    if flow_provider is not None:
        if symbol is None:
            return None
        return _coerce_flow_value(flow_provider(symbol, as_of))
    if symbol is None:
        return None
    return _coerce_flow_value(_default_flow_provider(symbol, as_of))


def _default_flow_provider(symbol: str, as_of: datetime) -> object | None:
    try:
        module = import_module("backend.tools.m52_flow_floor")
    except Exception:
        return None

    fetch_flow_data_pit = getattr(module, "fetch_flow_data_pit", None)
    compute_s_flow_data = getattr(module, "compute_s_flow_data", None)
    if not callable(fetch_flow_data_pit) or not callable(compute_s_flow_data):
        return None

    for fetch_kwargs in (
        {"symbol": symbol, "as_of": as_of},
        {"symbol": symbol},
    ):
        try:
            raw_flow = fetch_flow_data_pit(**fetch_kwargs)
            return compute_s_flow_data(raw_flow)
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _coerce_flow_value(value: float | int | dict[str, Any] | object | None) -> float | None:
    raw = value
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("s_flow_data")
    elif not isinstance(raw, int | float) and hasattr(raw, "s_flow_data"):
        raw = attrgetter("s_flow_data")(raw)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return _clamp(float(raw), -1.0, 1.0)


def _infer_symbol(clusters: Sequence[EventCluster]) -> str | None:
    return clusters[0].symbol if clusters else None


def _same_nonzero_sign(left: float, right: float) -> bool:
    return (left > 0.0 and right > 0.0) or (left < 0.0 and right < 0.0)


def _opposite_sign(left: float, right: float) -> bool:
    return (left > 0.0 and right < 0.0) or (left < 0.0 and right > 0.0)


def _append_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))
