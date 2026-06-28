"""Observe-only M54 news layer v2 orchestration and PIT DB evidence helpers."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.data.models.market import NewsItem
from backend.data.news_clustering import cluster_evidence
from backend.data.news_evidence import NewsEvidence
from backend.data.news_extraction import extract_clusters
from backend.data.news_fusion import NewsSignalV2, fuse_signal


def score_news_v2(
    evidence: list[NewsEvidence],
    as_of: datetime,
    *,
    tier: str = "capable",
    flow_value: float | None = None,
) -> NewsSignalV2:
    """Score already-collected news evidence through the M54 v2 observe-only stack."""
    clusters = cluster_evidence(evidence)
    cluster_scores = extract_clusters(clusters, tier=tier)
    return fuse_signal(
        cluster_scores,
        clusters,
        as_of,
        flow_value=flow_value,
    )


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
