"""Deterministic M54 L1 trigger layer.

Decides, per symbol per as-of date, whether the event pyramid should spend
LLM budget today, using only deterministic rules over already-clustered
evidence (EventCluster) plus optionally injected price/volume signals. This
module makes zero LLM calls and does not fetch market data itself — callers
must inject price_change_pct / volume_ratio if they want that trigger to be
evaluated; when omitted the trigger is skipped and recorded as a reason
(never silently dropped).

Wiring into backend/data/news_layer_v2.py and config is left to a later
integration pass — this module is self-contained and imports nothing from
the orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from backend.data.news_clustering import _EVENT_KEYWORDS, _PRODUCT_KEYWORDS, EventCluster
from backend.data.news_extraction import prescreen_cluster

# Event types that represent a company-specific announcement/disclosure
# (as opposed to a broad-market or sector-wide mention).
ANNOUNCEMENT_EVENT_TYPES = frozenset({"regulatory", "earnings", "contract"})
# Event types that are inherently company-scoped (not sector/market chatter).
COMPANY_EVENT_TYPES = frozenset({"earnings", "contract"})

_POLICY_KEYWORDS = _EVENT_KEYWORDS["regulatory"]

DEFAULT_PRICE_CHANGE_PCT_THRESHOLD = 5.0
DEFAULT_VOLUME_RATIO_THRESHOLD = 2.0
DEFAULT_MATERIALITY_TRIGGER_THRESHOLD = 0.70
DEFAULT_SOURCE_DIVERSITY_SURGE_DELTA = 2
DEFAULT_SOURCE_DIVERSITY_SURGE_MIN = 3

REASON_NEW_ANNOUNCEMENT = "new_announcement_event"
REASON_PRICE_ANOMALY = "price_change_anomaly"
REASON_VOLUME_ANOMALY = "volume_anomaly"
REASON_PRICE_VOLUME_SKIPPED = "price_volume_input_missing"
REASON_POLICY_KEYWORD = "policy_keyword_hit"
REASON_SOURCE_DIVERSITY_SURGE = "source_diversity_surge"
REASON_L0_EVENT_SCORE = "l0_event_score_threshold"

MAIN_CAUSE_COMPANY_EVENT = "company_event"
MAIN_CAUSE_REGULATION_POLICY = "regulation_policy"
MAIN_CAUSE_INDUSTRY_PEER = "industry_peer"
MAIN_CAUSE_MARKET_SENTIMENT = "market_sentiment"


@dataclass
class PreviousTriggerState:
    """Minimal as-of-stamped state carried across trigger evaluations.

    Callers are responsible for persisting/loading this between runs; this
    module only reads it.
    """

    as_of: datetime | None = None
    triggered: bool = False
    max_source_diversity: int = 0


@dataclass
class AttributionCard:
    """Minimal deterministic 异动归因卡 attached to a triggered decision."""

    symbol: str
    as_of: datetime
    timeline: list[dict] = field(default_factory=list)
    main_cause: str = MAIN_CAUSE_MARKET_SENTIMENT
    thesis_recheck: bool = False


@dataclass
class TriggerDecision:
    symbol: str
    as_of: datetime
    triggered: bool
    reasons: list[str] = field(default_factory=list)
    attribution_card: AttributionCard | None = None


def decide_trigger(
    symbol: str,
    as_of: datetime,
    clusters: list[EventCluster],
    *,
    previous_state: PreviousTriggerState | None = None,
    price_change_pct: float | None = None,
    volume_ratio: float | None = None,
    price_change_pct_threshold: float = DEFAULT_PRICE_CHANGE_PCT_THRESHOLD,
    volume_ratio_threshold: float = DEFAULT_VOLUME_RATIO_THRESHOLD,
    materiality_threshold: float = DEFAULT_MATERIALITY_TRIGGER_THRESHOLD,
    source_diversity_surge_delta: int = DEFAULT_SOURCE_DIVERSITY_SURGE_DELTA,
    source_diversity_surge_min: int = DEFAULT_SOURCE_DIVERSITY_SURGE_MIN,
) -> TriggerDecision:
    """Decide whether `symbol` deserves LLM-budget spend as of `as_of`.

    Pure function, zero LLM calls. `clusters` should be the EventClusters
    already scoped/filterable to `symbol` (clusters for other symbols are
    ignored defensively). Price/volume signals are caller-injected; when
    both are absent the price/volume trigger is skipped and a flag is
    recorded in `reasons` rather than silently dropped.
    """
    symbol_clusters = [cluster for cluster in clusters if cluster.symbol == symbol]
    reasons: list[str] = []

    triggered_clusters = _clusters_with_announcement_event(symbol_clusters)
    if triggered_clusters:
        reasons.append(REASON_NEW_ANNOUNCEMENT)

    if price_change_pct is None and volume_ratio is None:
        reasons.append(REASON_PRICE_VOLUME_SKIPPED)
    else:
        if price_change_pct is not None and abs(price_change_pct) >= price_change_pct_threshold:
            reasons.append(REASON_PRICE_ANOMALY)
        if volume_ratio is not None and volume_ratio >= volume_ratio_threshold:
            reasons.append(REASON_VOLUME_ANOMALY)

    policy_clusters = _clusters_with_policy_keyword(symbol_clusters)
    if policy_clusters:
        reasons.append(REASON_POLICY_KEYWORD)

    previous_max_diversity = previous_state.max_source_diversity if previous_state else 0
    surge_clusters = _clusters_with_source_diversity_surge(
        symbol_clusters,
        previous_max_diversity=previous_max_diversity,
        surge_delta=source_diversity_surge_delta,
        surge_min=source_diversity_surge_min,
    )
    if surge_clusters:
        reasons.append(REASON_SOURCE_DIVERSITY_SURGE)

    l0_clusters = _clusters_above_materiality(symbol_clusters, materiality_threshold)
    if l0_clusters:
        reasons.append(REASON_L0_EVENT_SCORE)

    fired_reasons = [reason for reason in reasons if reason != REASON_PRICE_VOLUME_SKIPPED]
    triggered = bool(fired_reasons)

    attribution_card = None
    if triggered:
        attribution_card = _build_attribution_card(
            symbol=symbol,
            as_of=as_of,
            clusters=symbol_clusters,
            policy_hit=bool(policy_clusters),
            has_price_volume_anomaly=(
                REASON_PRICE_ANOMALY in reasons or REASON_VOLUME_ANOMALY in reasons
            ),
        )

    return TriggerDecision(
        symbol=symbol,
        as_of=as_of,
        triggered=triggered,
        reasons=reasons,
        attribution_card=attribution_card,
    )


def _clusters_with_announcement_event(clusters: list[EventCluster]) -> list[EventCluster]:
    return [cluster for cluster in clusters if cluster.event_type in ANNOUNCEMENT_EVENT_TYPES]


def _clusters_with_policy_keyword(clusters: list[EventCluster]) -> list[EventCluster]:
    hits: list[EventCluster] = []
    for cluster in clusters:
        text = " ".join(member.title for member in cluster.members)
        if any(keyword in text for keyword in _POLICY_KEYWORDS):
            hits.append(cluster)
    return hits


def _clusters_with_source_diversity_surge(
    clusters: list[EventCluster],
    *,
    previous_max_diversity: int,
    surge_delta: int,
    surge_min: int,
) -> list[EventCluster]:
    hits: list[EventCluster] = []
    for cluster in clusters:
        if cluster.source_diversity < surge_min:
            continue
        if cluster.source_diversity - previous_max_diversity >= surge_delta:
            hits.append(cluster)
    return hits


def _clusters_above_materiality(
    clusters: list[EventCluster], materiality_threshold: float
) -> list[EventCluster]:
    hits: list[EventCluster] = []
    for cluster in clusters:
        decision = prescreen_cluster(cluster)
        if decision["materiality"] >= materiality_threshold:
            hits.append(cluster)
    return hits


def _clusters_with_industry_keyword(clusters: list[EventCluster]) -> list[EventCluster]:
    hits: list[EventCluster] = []
    for cluster in clusters:
        entity_hit = any(entity in _PRODUCT_KEYWORDS for entity in cluster.entities)
        text = " ".join(member.title for member in cluster.members)
        keyword_hit = any(keyword in text for keyword in _PRODUCT_KEYWORDS)
        if entity_hit or keyword_hit:
            hits.append(cluster)
    return hits


def _build_attribution_card(
    *,
    symbol: str,
    as_of: datetime,
    clusters: list[EventCluster],
    policy_hit: bool,
    has_price_volume_anomaly: bool,
) -> AttributionCard:
    timeline = _build_timeline(clusters)
    main_cause = _classify_main_cause(
        clusters=clusters,
        policy_hit=policy_hit,
        has_price_volume_anomaly=has_price_volume_anomaly,
    )
    thesis_recheck = main_cause in (MAIN_CAUSE_COMPANY_EVENT, MAIN_CAUSE_REGULATION_POLICY)
    return AttributionCard(
        symbol=symbol,
        as_of=as_of,
        timeline=timeline,
        main_cause=main_cause,
        thesis_recheck=thesis_recheck,
    )


def _build_timeline(clusters: list[EventCluster]) -> list[dict]:
    entries: list[dict] = []
    for cluster in clusters:
        for member in cluster.members:
            entries.append(
                {
                    "time": member.published_at,
                    "title": member.title,
                    "source": member.provider,
                    "event_type": cluster.event_type,
                    "cluster_id": cluster.cluster_id,
                }
            )
    entries.sort(key=lambda entry: (entry["time"], entry["title"]))
    return entries


def _classify_main_cause(
    *,
    clusters: list[EventCluster],
    policy_hit: bool,
    has_price_volume_anomaly: bool,
) -> str:
    """Four-way deterministic classification, evaluated by fixed priority.

    Priority: regulation_policy > company_event > industry_peer >
    market_sentiment (fallback when no strong cluster-level signal exists).
    """
    if policy_hit or any(cluster.event_type == "regulatory" for cluster in clusters):
        return MAIN_CAUSE_REGULATION_POLICY
    if any(cluster.event_type in COMPANY_EVENT_TYPES for cluster in clusters):
        return MAIN_CAUSE_COMPANY_EVENT
    if _clusters_with_industry_keyword(clusters):
        return MAIN_CAUSE_INDUSTRY_PEER
    return MAIN_CAUSE_MARKET_SENTIMENT
