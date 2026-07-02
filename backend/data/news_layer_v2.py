"""Observe-only M54 news layer v2 orchestration and PIT DB evidence helpers.

M54 阶段7 event pyramid: score_news_v2()/news_v2_score_from_db() are the sole
insertion points. The pyramid (L1 deterministic trigger gating, L2 scope-based
shared digest caching, L2/7c LLM token budget guardrail) only activates when
``settings.news_v2_pyramid_enabled`` is True; when False (default) both
functions fall through byte-identical to the pre-pyramid path
(cluster_evidence -> extract_clusters -> fuse_signal, no trigger/scope/budget
logic at all). This module never touches backend/analysis/sentiment.py or any
production/test1/test2 weight.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.models.market import NewsItem
from backend.data.news_clustering import EventCluster, cluster_evidence
from backend.data.news_evidence import NewsEvidence
from backend.data.news_extraction import ClusterScore, extract_clusters, score_cluster_title_only
from backend.data.news_fusion import NewsSignalV2, fuse_signal
from backend.data.news_scope import plan_scope_sharing
from backend.data.news_trigger import decide_trigger
from backend.ops.llm_budget import check_budget

# Degradation flags appended by the pyramid orchestrator. These live alongside
# (not inside) backend/data/news_fusion.py's existing flag vocabulary — the
# pyramid is purely an upstream gating layer, fuse_signal() itself is
# untouched and has no notion of these flags.
PYRAMID_NOT_TRIGGERED = "PYRAMID_NOT_TRIGGERED"
PYRAMID_BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

# Process-local caches for the pyramid orchestrator only (never consulted or
# populated when news_v2_pyramid_enabled is False). Deliberately in-memory:
# 7a/7b provide the deterministic trigger/scope *decisions*, this module owns
# reusing prior results across calls within a process.
_SHARED_DIGEST_CACHE: dict[str, ClusterScore] = {}
_SYMBOL_LAST_SIGNAL_CACHE: dict[str, NewsSignalV2] = {}


def score_news_v2(
    evidence: list[NewsEvidence],
    as_of: datetime,
    *,
    tier: str = "capable",
    flow_value: float | None = None,
) -> NewsSignalV2:
    """Score already-collected news evidence through the M54 v2 observe-only stack."""
    clusters = cluster_evidence(evidence)
    if not settings.news_v2_pyramid_enabled:
        cluster_scores = extract_clusters(clusters, tier=tier)
        return fuse_signal(
            cluster_scores,
            clusters,
            as_of,
            flow_value=flow_value,
        )
    return _score_news_v2_pyramid(clusters, as_of, tier=tier, flow_value=flow_value)


def _score_news_v2_pyramid(
    clusters: list[EventCluster],
    as_of: datetime,
    *,
    tier: str,
    flow_value: float | None,
) -> NewsSignalV2:
    """Pyramid path: L1 trigger gate -> L2 scope-shared digest cache -> 7c budget guardrail."""
    if not clusters:
        return fuse_signal([], clusters, as_of, flow_value=flow_value)

    symbol = clusters[0].symbol
    pyramid_flags: list[str] = []
    attribution_card = None

    if settings.news_v2_pyramid_trigger_only:
        trigger_decision = decide_trigger(symbol, as_of, clusters)
        if not trigger_decision.triggered:
            pyramid_flags.append(PYRAMID_NOT_TRIGGERED)
            cached_signal = _SYMBOL_LAST_SIGNAL_CACHE.get(symbol)
            if cached_signal is not None:
                return _with_extra_flags(cached_signal, pyramid_flags)
            # No prior cached result to reuse yet — score deterministically
            # (title-only, zero LLM calls) rather than spending budget on an
            # untriggered symbol.
            cluster_scores = [score_cluster_title_only(cluster) for cluster in clusters]
            signal = fuse_signal(cluster_scores, clusters, as_of, flow_value=flow_value)
            signal = _with_extra_flags(signal, pyramid_flags)
            _SYMBOL_LAST_SIGNAL_CACHE[symbol] = signal
            return signal
        attribution_card = trigger_decision.attribution_card

    scope_plan = plan_scope_sharing(clusters)
    cluster_by_id = {cluster.cluster_id: cluster for cluster in clusters}

    budget_status = check_budget("sentiment", settings.llm_daily_budget_tokens_sentiment)
    if budget_status.exceeded:
        pyramid_flags.append(PYRAMID_BUDGET_EXCEEDED)
        scores_by_id = {
            cluster.cluster_id: score_cluster_title_only(cluster) for cluster in clusters
        }
    else:
        scores_by_id = {}
        stock_only_clusters = [cluster_by_id[cid] for cid in scope_plan.stock_only_clusters]
        if stock_only_clusters:
            for cid, score in zip(
                scope_plan.stock_only_clusters,
                extract_clusters(stock_only_clusters, tier=tier),
                strict=True,
            ):
                scores_by_id[cid] = score

        for shared_key, member_ids in scope_plan.shared_clusters.items():
            cached_score = _SHARED_DIGEST_CACHE.get(shared_key)
            if cached_score is None:
                representative = cluster_by_id[member_ids[0]]
                cached_score = extract_clusters([representative], tier=tier)[0]
                _SHARED_DIGEST_CACHE[shared_key] = cached_score
            for cid in member_ids:
                scores_by_id[cid] = cached_score

    cluster_scores = [scores_by_id[cluster.cluster_id] for cluster in clusters]
    signal = fuse_signal(cluster_scores, clusters, as_of, flow_value=flow_value)
    signal = _with_extra_flags(signal, pyramid_flags)
    if attribution_card is not None:
        signal.attribution_card = attribution_card
    _SYMBOL_LAST_SIGNAL_CACHE[symbol] = signal
    return signal


def _with_extra_flags(signal: NewsSignalV2, extra_flags: list[str]) -> NewsSignalV2:
    """Return `signal` with `extra_flags` merged into degradation_flags, without
    mutating a possibly-cached/shared instance."""
    if not extra_flags:
        return signal
    flags = list(signal.degradation_flags)
    for flag in extra_flags:
        if flag not in flags:
            flags.append(flag)
    return dataclasses.replace(signal, degradation_flags=flags)


def evidence_from_db(
    symbol: str,
    as_of: datetime,
    lookback_days: int,
    db: Session,
) -> list[NewsEvidence]:
    """Load point-in-time historical news evidence without calling live adapters."""
    start = as_of - timedelta(days=lookback_days)
    rows = (
        db.query(NewsItem)
        .filter(
            NewsItem.symbol == symbol,
            NewsItem.published_at >= start,
            NewsItem.published_at <= as_of,
        )
        .order_by(NewsItem.published_at.asc(), NewsItem.id.asc())
        .all()
    )

    return [_evidence_from_news_item(row, symbol=symbol) for row in rows]


def news_v2_score_from_db(
    symbol: str,
    as_of: datetime,
    lookback_days: int,
    db: Session,
    *,
    tier: str = "capable",
    flow_value: float | None = None,
) -> NewsSignalV2:
    """Load PIT DB evidence and score it through the M54 v2 stack."""
    evidence = evidence_from_db(symbol, as_of, lookback_days, db)
    return score_news_v2(
        evidence,
        as_of,
        tier=tier,
        flow_value=flow_value,
    )


def _evidence_from_news_item(row: NewsItem, *, symbol: str) -> NewsEvidence:
    provider = row.provider or row.source or "db"
    return NewsEvidence(
        symbol=row.symbol or symbol,
        title=row.title,
        url=row.url,
        published_at=row.published_at,
        source_name=row.source or provider,
        provider=provider,
        content=row.content,
        fetched_at=row.fetched_at,
    )
