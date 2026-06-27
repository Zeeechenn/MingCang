"""Observe-only M54 tiered news extraction for event clusters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.data.news_clustering import EventCluster
from backend.llm import get_provider

ContentDepth = Literal["full", "title_only"]

MATERIALITY_UPGRADE_THRESHOLD = 0.70
DIRECT_RELEVANCE_UPGRADE_THRESHOLD = 0.75
DIVERGENCE_SOURCE_DIVERSITY_THRESHOLD = 3
FULL_CONTENT_CHAR_LIMIT = 6000
MEMBER_CONTENT_CHAR_LIMIT = 1800
TITLE_ONLY_CONFIDENCE_DISCOUNT = 0.65

_FULL_MAX_TOKENS = 900
_TITLE_MAX_CATALYSTS = 3
_TITLE_MAX_RISKS = 3

_MATERIAL_EVENT_TYPES = {
    "contract": 0.74,
    "earnings": 0.74,
    "regulatory": 0.70,
    "flow": 0.56,
    "opinion": 0.40,
    "unknown": 0.30,
}
_DIRECT_EVENT_TYPES = {"contract", "earnings", "regulatory"}
_DIVERGENCE_EVENT_TYPES = {"opinion", "regulatory", "flow"}
_BROAD_ENTITIES = {
    "半导体",
    "新能源",
    "机器人",
    "算力",
    "芯片",
    "电池",
    "白酒",
    "存储芯片",
    "光刻胶",
    "DRAM",
    "HBM",
    "GPU",
    "CPO",
    "AI",
}
_MATERIAL_TITLE_TERMS = (
    "中标",
    "合同",
    "订单",
    "签署",
    "采购",
    "公告",
    "回购",
    "增持",
    "减持",
    "立案",
    "处罚",
    "问询",
    "停牌",
    "复牌",
    "业绩",
    "净利润",
    "营收",
    "预增",
    "预减",
    "亏损",
)
_POSITIVE_TERMS = (
    "中标",
    "签署",
    "订单",
    "合作",
    "回购",
    "增持",
    "预增",
    "增长",
    "获批",
    "突破",
    "上调",
    "净买入",
)
_NEGATIVE_TERMS = (
    "处罚",
    "立案",
    "问询",
    "减持",
    "预减",
    "亏损",
    "下滑",
    "风险提示",
    "终止",
    "净卖出",
    "走弱",
)

_CLUSTER_SCORE_SYSTEM = (
    "你是A股新闻事件抽取器。只做结构化观察，不给买卖建议、不预测确定价格。"
    "请基于正文判断事件与目标股票的相关度、方向、材料性和验证点。"
)

CLUSTER_SCORE_TOOL = {
    "name": "record_cluster_score",
    "description": "记录单个新闻事件簇的结构化评分",
    "input_schema": {
        "type": "object",
        "properties": {
            "relevance": {
                "type": "number",
                "description": "0.0到1.0，事件与目标股票基本面/交易关注的相关度",
            },
            "sentiment": {
                "type": "number",
                "description": "-1.0到1.0，负面到正面；不确定或冲突时靠近0",
            },
            "materiality": {
                "type": "number",
                "description": "0.0到1.0，事件是否可能改变基本面、预期或风险认知",
            },
            "horizon": {
                "type": "string",
                "enum": ["short", "medium", "long", "unknown"],
                "description": "影响周期：short/medium/long/unknown",
            },
            "event_type": {
                "type": "string",
                "description": "事件类型，如 earnings/contract/regulatory/flow/opinion/unknown",
            },
            "catalysts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "正向或待验证催化因素，最多5条",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "负向风险或验证失败条件，最多5条",
            },
            "confidence": {
                "type": "number",
                "description": "0.0到1.0，对本次结构化判断的置信度",
            },
        },
        "required": [
            "relevance",
            "sentiment",
            "materiality",
            "horizon",
            "event_type",
            "catalysts",
            "risks",
            "confidence",
        ],
    },
}


@dataclass
class ClusterScore:
    relevance: float
    sentiment: float
    materiality: float
    horizon: str
    event_type: str
    catalysts: list[str]
    risks: list[str]
    evidence_refs: list[str]
    confidence: float
    content_depth_used: ContentDepth


def prescreen_cluster(cluster: EventCluster) -> dict[str, Any]:
    """Cheap deterministic router for deciding whether a cluster deserves full text."""
    title = cluster.representative_title
    event_type = cluster.event_type or "unknown"
    direct = _has_direct_company_signal(cluster)
    materiality = _rough_materiality(title, event_type, cluster.source_diversity)
    relevance = _rough_relevance(cluster, direct, materiality)
    divergence_proxy = _has_divergence_proxy(cluster)

    reasons: list[str] = []
    if materiality >= MATERIALITY_UPGRADE_THRESHOLD:
        reasons.append("materiality")
    if direct and relevance >= DIRECT_RELEVANCE_UPGRADE_THRESHOLD:
        reasons.append("direct_relevance")
    if divergence_proxy:
        reasons.append("divergence_proxy")

    return {
        "upgrade": bool(reasons),
        "relevance": relevance,
        "materiality": materiality,
        "event_type": event_type,
        "direct_relevance": direct,
        "divergence_proxy": divergence_proxy,
        "upgrade_reasons": reasons,
    }


def extract_cluster_full(cluster: EventCluster, tier: str = "capable") -> ClusterScore:
    """Extract a ClusterScore from full article content using the configured provider."""
    prompt = _build_full_prompt(cluster)
    data = get_provider().complete_structured(
        prompt=prompt,
        tool=CLUSTER_SCORE_TOOL,
        system=_CLUSTER_SCORE_SYSTEM,
        max_tokens=_FULL_MAX_TOKENS,
        model_tier=tier,
    )
    return ClusterScore(
        relevance=_clamp_float(data.get("relevance"), 0.0, 1.0),
        sentiment=_clamp_float(data.get("sentiment"), -1.0, 1.0),
        materiality=_clamp_float(data.get("materiality"), 0.0, 1.0),
        horizon=_string_value(data.get("horizon"), fallback="unknown"),
        event_type=_string_value(data.get("event_type"), fallback=cluster.event_type or "unknown"),
        catalysts=_string_list(data.get("catalysts")),
        risks=_string_list(data.get("risks")),
        evidence_refs=_evidence_refs(cluster),
        confidence=_clamp_float(data.get("confidence"), 0.0, 1.0),
        content_depth_used="full",
    )


def score_cluster_title_only(cluster: EventCluster) -> ClusterScore:
    """Score a non-upgraded or content-thin cluster without spending LLM budget."""
    decision = prescreen_cluster(cluster)
    title = cluster.representative_title
    sentiment = _rough_sentiment(title)
    confidence_base = 0.38
    if decision["direct_relevance"]:
        confidence_base += 0.10
    if cluster.event_type != "unknown":
        confidence_base += 0.06
    confidence_base += min(cluster.source_diversity, 3) * 0.04

    return ClusterScore(
        relevance=decision["relevance"],
        sentiment=sentiment,
        materiality=decision["materiality"],
        horizon=_title_horizon(cluster.event_type),
        event_type=decision["event_type"],
        catalysts=_title_catalysts(title),
        risks=_title_risks(title),
        evidence_refs=_evidence_refs(cluster),
        confidence=_clamp_float(
            confidence_base * TITLE_ONLY_CONFIDENCE_DISCOUNT,
            0.0,
            TITLE_ONLY_CONFIDENCE_DISCOUNT,
        ),
        content_depth_used="title_only",
    )


def extract_clusters(clusters: list[EventCluster], tier: str = "capable") -> list[ClusterScore]:
    """Run deterministic prescreening, then route each cluster to full or title-only scoring."""
    scores: list[ClusterScore] = []
    for cluster in clusters:
        decision = prescreen_cluster(cluster)
        if decision["upgrade"] and _full_content_chunks(cluster):
            scores.append(extract_cluster_full(cluster, tier=tier))
        else:
            scores.append(score_cluster_title_only(cluster))
    return scores


def _rough_materiality(title: str, event_type: str, source_diversity: int) -> float:
    score = _MATERIAL_EVENT_TYPES.get(event_type, _MATERIAL_EVENT_TYPES["unknown"])
    if any(term in title for term in _MATERIAL_TITLE_TERMS):
        score += 0.10
    if source_diversity >= 2:
        score += 0.04
    if source_diversity >= DIVERGENCE_SOURCE_DIVERSITY_THRESHOLD:
        score += 0.04
    return _clamp_float(score, 0.0, 1.0)


def _rough_relevance(cluster: EventCluster, direct: bool, materiality: float) -> float:
    score = 0.35
    if direct:
        score += 0.35
    if cluster.event_type in _DIRECT_EVENT_TYPES:
        score += 0.10
    if materiality >= MATERIALITY_UPGRADE_THRESHOLD:
        score += 0.08
    if cluster.source_diversity >= 2:
        score += 0.04
    return _clamp_float(score, 0.0, 1.0)


def _has_direct_company_signal(cluster: EventCluster) -> bool:
    title = cluster.representative_title
    if cluster.symbol and cluster.symbol in title:
        return True
    entities = {entity.strip() for entity in cluster.entities if entity.strip()}
    company_entities = {
        entity
        for entity in entities
        if entity != cluster.symbol and entity not in _BROAD_ENTITIES and not entity.isdigit()
    }
    if any(entity in title for entity in company_entities):
        return True
    return cluster.event_type in _DIRECT_EVENT_TYPES and bool(company_entities)


def _has_divergence_proxy(cluster: EventCluster) -> bool:
    return (
        cluster.source_diversity >= DIVERGENCE_SOURCE_DIVERSITY_THRESHOLD
        or (cluster.source_diversity >= 2 and cluster.event_type in _DIVERGENCE_EVENT_TYPES)
    )


def _rough_sentiment(title: str) -> float:
    positive = sum(1 for term in _POSITIVE_TERMS if term in title)
    negative = sum(1 for term in _NEGATIVE_TERMS if term in title)
    if positive == negative:
        return 0.0
    return _clamp_float((positive - negative) * 0.25, -0.75, 0.75)


def _title_horizon(event_type: str) -> str:
    if event_type in {"contract", "earnings"}:
        return "medium"
    if event_type == "regulatory":
        return "short"
    return "unknown"


def _title_catalysts(title: str) -> list[str]:
    return _matched_terms(title, _POSITIVE_TERMS, _TITLE_MAX_CATALYSTS)


def _title_risks(title: str) -> list[str]:
    return _matched_terms(title, _NEGATIVE_TERMS, _TITLE_MAX_RISKS)


def _matched_terms(title: str, terms: tuple[str, ...], limit: int) -> list[str]:
    return [term for term in terms if term in title][:limit]


def _build_full_prompt(cluster: EventCluster) -> str:
    chunks = _full_content_chunks(cluster)
    articles = "\n\n".join(
        (
            f"[{index}] title={title}\n"
            f"source={source} provider={provider} url={url} published_at={published_at}\n"
            f"content={content}"
        )
        for index, (title, source, provider, url, published_at, content) in enumerate(chunks, start=1)
    )
    entities = ", ".join(cluster.entities) if cluster.entities else "none"
    return (
        f"symbol: {cluster.symbol}\n"
        f"cluster_id: {cluster.cluster_id}\n"
        f"event_type_hint: {cluster.event_type}\n"
        f"representative_title: {cluster.representative_title}\n"
        f"source_diversity: {cluster.source_diversity}\n"
        f"entities: {entities}\n\n"
        "Full-text evidence articles:\n"
        f"{articles}\n\n"
        "Return only the structured tool payload. Keep catalysts and risks concise."
    )


def _full_content_chunks(cluster: EventCluster) -> list[tuple[str, str, str, str, str, str]]:
    chunks: list[tuple[str, str, str, str, str, str]] = []
    remaining = FULL_CONTENT_CHAR_LIMIT
    for member in cluster.members:
        if member.content_status != "full" or not member.content:
            continue
        content = member.content.strip()
        if not content:
            continue
        clipped_content = content[: min(len(content), MEMBER_CONTENT_CHAR_LIMIT, remaining)]
        if not clipped_content:
            break
        chunks.append(
            (
                member.title,
                member.source_name,
                member.provider,
                member.url,
                member.published_at.isoformat(),
                clipped_content,
            )
        )
        remaining -= len(clipped_content)
        if remaining <= 0:
            break
    return chunks


def _evidence_refs(cluster: EventCluster) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for member in cluster.members:
        url = member.url.strip()
        if url and url not in seen:
            seen.add(url)
            refs.append(url)
    return refs


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_value(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _clamp_float(value: Any, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    return min(max(number, low), high)
