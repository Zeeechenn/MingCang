"""Observe-only M54 news layer v2 orchestration and PIT DB evidence helpers.

M54 阶段7 event pyramid: score_news_v2()/news_v2_score_from_db() are the sole
insertion points. The pyramid (L1 deterministic trigger gating, L2 scope-based
shared digest caching, L2/7c LLM token budget guardrail) only activates when
``settings.news_v2_pyramid_enabled`` is True; when False both functions fall
through byte-identical to the pre-pyramid path (cluster_evidence ->
extract_clusters -> fuse_signal, no trigger/scope/budget logic at all).

Default is True as of M54 §12-13 (docs/dev/M54_OOS_PREREGISTER.md) -- the
pyramid became the default v2-pipeline runner (owner-authorized token
optimization) once it was shown to save ~66% LLM spend with no signal loss on
its own triggered windows, independent of the still-open v2-vs-legacy verdict.
This module never touches backend/analysis/sentiment.py or any
production/test1/test2 weight.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.config import settings
from backend.data.models.m61 import Announcement
from backend.data.models.market import NewsItem
from backend.data.news_clustering import EventCluster, cluster_evidence
from backend.data.news_evidence import NewsEvidence
from backend.data.news_extraction import ClusterScore, extract_clusters, score_cluster_title_only
from backend.data.news_fusion import NewsSignalV2, fuse_signal
from backend.data.news_scope import plan_scope_sharing
from backend.data.news_trigger import PreviousTriggerState, decide_trigger
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
_SHARED_DIGEST_CACHE: dict[tuple[str, str, str], ClusterScore] = {}
_SYMBOL_LAST_SIGNAL_CACHE: dict[tuple[str, str, str], NewsSignalV2] = {}


def score_news_v2(
    evidence: list[NewsEvidence],
    as_of: datetime,
    *,
    tier: str = "capable",
    flow_value: float | None = None,
    previous_state: PreviousTriggerState | None = None,
    price_change_pct: float | None = None,
    volume_ratio: float | None = None,
    cache_namespace: str = "default",
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
    return _score_news_v2_pyramid(
        clusters,
        as_of,
        tier=tier,
        flow_value=flow_value,
        previous_state=previous_state,
        price_change_pct=price_change_pct,
        volume_ratio=volume_ratio,
        cache_namespace=cache_namespace,
    )


def _score_news_v2_pyramid(
    clusters: list[EventCluster],
    as_of: datetime,
    *,
    tier: str,
    flow_value: float | None,
    previous_state: PreviousTriggerState | None,
    price_change_pct: float | None,
    volume_ratio: float | None,
    cache_namespace: str,
) -> NewsSignalV2:
    """Pyramid path: L1 trigger gate -> L2 scope-shared digest cache -> 7c budget guardrail."""
    if not clusters:
        return fuse_signal([], clusters, as_of, flow_value=flow_value)

    symbol = clusters[0].symbol
    symbol_cache_key = (cache_namespace, tier, symbol)
    pyramid_flags: list[str] = []
    attribution_card = None
    trigger_reasons: list[str] = []

    if settings.news_v2_pyramid_trigger_only:
        trigger_decision = decide_trigger(
            symbol,
            as_of,
            clusters,
            previous_state=previous_state,
            price_change_pct=price_change_pct,
            volume_ratio=volume_ratio,
        )
        trigger_reasons = list(trigger_decision.reasons)
        if not trigger_decision.triggered:
            pyramid_flags.append(PYRAMID_NOT_TRIGGERED)
            cached_signal = _SYMBOL_LAST_SIGNAL_CACHE.get(symbol_cache_key)
            if cached_signal is not None:
                return _with_trigger_metadata(
                    _with_extra_flags(cached_signal, pyramid_flags),
                    trigger_reasons=trigger_reasons,
                    attribution_card=None,
                )
            # No prior cached result to reuse yet — score deterministically
            # (title-only, zero LLM calls) rather than spending budget on an
            # untriggered symbol.
            cluster_scores = [score_cluster_title_only(cluster) for cluster in clusters]
            signal = fuse_signal(cluster_scores, clusters, as_of, flow_value=flow_value)
            signal = _with_extra_flags(signal, pyramid_flags)
            signal = _with_trigger_metadata(
                signal,
                trigger_reasons=trigger_reasons,
                attribution_card=None,
            )
            _SYMBOL_LAST_SIGNAL_CACHE[symbol_cache_key] = signal
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
            digest_cache_key = (cache_namespace, tier, shared_key)
            cached_score = _SHARED_DIGEST_CACHE.get(digest_cache_key)
            if cached_score is None:
                representative = cluster_by_id[member_ids[0]]
                cached_score = extract_clusters([representative], tier=tier)[0]
                _SHARED_DIGEST_CACHE[digest_cache_key] = cached_score
            for cid in member_ids:
                scores_by_id[cid] = cached_score

    cluster_scores = [scores_by_id[cluster.cluster_id] for cluster in clusters]
    signal = fuse_signal(cluster_scores, clusters, as_of, flow_value=flow_value)
    signal = _with_extra_flags(signal, pyramid_flags)
    signal = _with_trigger_metadata(
        signal,
        trigger_reasons=trigger_reasons,
        attribution_card=attribution_card,
    )
    _SYMBOL_LAST_SIGNAL_CACHE[symbol_cache_key] = signal
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


def _with_trigger_metadata(
    signal: NewsSignalV2,
    *,
    trigger_reasons: list[str],
    attribution_card: object | None,
) -> NewsSignalV2:
    """Attach current-run L1 metadata without mutating shared cached signals."""
    return dataclasses.replace(
        signal,
        trigger_reasons=list(trigger_reasons),
        attribution_card=attribution_card,
    )


def evidence_from_db(
    symbol: str,
    as_of: datetime,
    lookback_days: int,
    db: Session,
    *,
    include_announcements: bool = False,
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

    evidence = [_evidence_from_news_item(row, symbol=symbol) for row in rows]
    if not include_announcements:
        return evidence

    announcement_rows = (
        db.query(Announcement)
        .filter(
            Announcement.symbol == symbol,
            Announcement.published_at >= start,
            Announcement.published_at <= as_of,
        )
        .order_by(Announcement.published_at.asc(), Announcement.id.asc())
        .all()
    )
    evidence.extend(_evidence_from_announcement(row, symbol=symbol) for row in announcement_rows)
    return evidence


def news_v2_score_from_db(
    symbol: str,
    as_of: datetime,
    lookback_days: int,
    db: Session,
    *,
    tier: str = "capable",
    flow_value: float | None = None,
    include_announcements: bool = False,
    previous_state: PreviousTriggerState | None = None,
    price_change_pct: float | None = None,
    volume_ratio: float | None = None,
    cache_namespace: str = "default",
) -> NewsSignalV2:
    """Load PIT DB evidence and score it through the M54 v2 stack."""
    evidence = evidence_from_db(
        symbol,
        as_of,
        lookback_days,
        db,
        include_announcements=include_announcements,
    )
    return score_news_v2(
        evidence,
        as_of,
        tier=tier,
        flow_value=flow_value,
        previous_state=previous_state,
        price_change_pct=price_change_pct,
        volume_ratio=volume_ratio,
        cache_namespace=cache_namespace,
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


def _evidence_from_announcement(row: Announcement, *, symbol: str) -> NewsEvidence:
    provider = row.provider or "announcement"
    title = f"【公告】{row.title}"
    content = f"【公告】{row.content}" if row.content else None
    return NewsEvidence(
        symbol=row.symbol or symbol,
        title=title,
        url=row.source_url or f"announcement://{row.symbol or symbol}/{row.id}",
        published_at=row.published_at,
        source_name=provider,
        provider=provider,
        content=content,
        fetched_at=row.fetched_at,
    )
