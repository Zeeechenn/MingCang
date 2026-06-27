"""Deterministic M54 news evidence normalization and event clustering."""
from __future__ import annotations

import difflib
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from backend.data.news_evidence import NewsEvidence

TITLE_SIMILARITY_THRESHOLD = 0.82
ENTITY_TITLE_SIMILARITY_THRESHOLD = 0.55
ENTITY_TOKEN_JACCARD_THRESHOLD = 0.30
CLUSTER_TIME_WINDOW = timedelta(hours=48)

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]+")
_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_PUNCT_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
_QUOTE_ONLY_RE = re.compile(r"^[0-9A-Za-z.\s:+\-/%]+$")

_COMPANY_SUFFIXES = (
    "半导体",
    "新能源",
    "股份",
    "集团",
    "科技",
    "电子",
    "创新",
    "能源",
    "银行",
    "证券",
    "药业",
    "医药",
    "材料",
    "电池",
    "汽车",
    "通信",
    "软件",
    "光电",
    "茅台",
    "长鑫",
)
_PRODUCT_KEYWORDS = (
    "存储芯片",
    "光刻胶",
    "新能源",
    "半导体",
    "机器人",
    "算力",
    "芯片",
    "电池",
    "白酒",
    "DRAM",
    "HBM",
    "GPU",
    "CPO",
    "AI",
)
_ENTITY_ACTION_TERMS = (
    "公告",
    "发布",
    "拟",
    "回购",
    "中标",
    "签署",
    "采购",
    "用于",
    "公司",
    "获",
)
_AD_TERMS = (
    "广告",
    "推广",
    "开户",
    "领取",
    "优惠",
    "福利",
    "扫码",
    "下载app",
    "直播间",
    "课程",
    "荐股",
    "免费诊股",
)
_LIST_NOISE_TERMS = (
    "涨幅榜",
    "跌幅榜",
    "涨停榜",
    "跌停榜",
    "成交额榜",
    "换手率榜",
    "排行榜",
    "排名",
    "前十名单",
)
_QUOTE_NOISE_TERMS = ("实时行情", "行情快照", "盘口", "分时图")
_EVENT_KEYWORDS = {
    "contract": ("合同", "中标", "订单", "采购", "签约", "合作", "协议"),
    "earnings": ("业绩", "营收", "净利润", "利润", "预增", "预减", "年报", "季报", "中报", "亏损"),
    "flow": ("主力资金", "资金流", "北向", "龙虎榜", "融资", "融券", "净买入"),
    "regulatory": ("公告", "监管", "问询", "处罚", "立案", "减持", "增持", "回购", "停牌", "复牌", "风险提示"),
    "opinion": ("研报", "评级", "机构", "券商", "看好", "建议", "观点", "分析"),
}


@dataclass
class EventCluster:
    cluster_id: str
    symbol: str
    members: list[NewsEvidence]
    event_type: str
    representative_title: str
    source_diversity: int
    entities: list[str]
    first_seen: datetime


@dataclass(frozen=True)
class _EvidenceFeatures:
    item: NewsEvidence
    normalized_url: str
    title_key: str
    title_tokens: frozenset[str]
    entities: tuple[str, ...]


def cluster_evidence(items: list[NewsEvidence]) -> list[EventCluster]:
    """Normalize, deduplicate, and group source evidence into event clusters."""
    features = _deduplicate_by_url(
        [_build_features(item) for item in items if not _is_obvious_noise(item)]
    )
    grouped = _group_related_features(features)
    clusters = [_build_cluster(group) for group in grouped]
    return sorted(
        clusters,
        key=lambda cluster: (cluster.first_seen, cluster.representative_title, cluster.cluster_id),
    )


def _deduplicate_by_url(features: list[_EvidenceFeatures]) -> list[_EvidenceFeatures]:
    best_by_url: dict[str, _EvidenceFeatures] = {}
    for feature in features:
        key = (
            feature.normalized_url
            or f"missing-url:{feature.title_key}:{feature.item.published_at.isoformat()}"
        )
        current = best_by_url.get(key)
        if current is None or _evidence_sort_key(feature.item) < _evidence_sort_key(current.item):
            best_by_url[key] = feature
    return sorted(best_by_url.values(), key=lambda feature: _evidence_sort_key(feature.item))


def _normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _group_related_features(features: list[_EvidenceFeatures]) -> list[list[_EvidenceFeatures]]:
    parent = list(range(len(features)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(features)):
        for right in range(left + 1, len(features)):
            if _features_match(features[left], features[right]):
                union(left, right)

    groups: dict[int, list[_EvidenceFeatures]] = defaultdict(list)
    for index, feature in enumerate(features):
        groups[find(index)].append(feature)
    return [sorted(group, key=lambda feature: _evidence_sort_key(feature.item)) for group in groups.values()]


def _features_match(left: _EvidenceFeatures, right: _EvidenceFeatures) -> bool:
    if left.item.symbol != right.item.symbol:
        return False
    if left.normalized_url and left.normalized_url == right.normalized_url:
        return True
    if abs(left.item.published_at - right.item.published_at) > CLUSTER_TIME_WINDOW:
        return False

    ratio = difflib.SequenceMatcher(None, left.title_key, right.title_key).ratio()
    jaccard = _jaccard(left.title_tokens, right.title_tokens)
    if max(ratio, jaccard) >= TITLE_SIMILARITY_THRESHOLD:
        return True

    shared_entities = (set(left.entities) & set(right.entities)) - {left.item.symbol}
    return bool(shared_entities) and (
        ratio >= ENTITY_TITLE_SIMILARITY_THRESHOLD or jaccard >= ENTITY_TOKEN_JACCARD_THRESHOLD
    )


def _build_cluster(features: list[_EvidenceFeatures]) -> EventCluster:
    sorted_features = sorted(features, key=lambda feature: _evidence_sort_key(feature.item))
    sorted_members = [feature.item for feature in sorted_features]
    symbol = sorted_members[0].symbol
    first_seen = min(member.published_at for member in sorted_members)
    representative = min(
        sorted_members,
        key=lambda member: (
            member.published_at,
            -_title_information_score(member.title, member.symbol),
            member.title,
        ),
    )
    providers = {_provider_key(member) for member in sorted_members if _provider_key(member)}
    entities = _merge_entities(sorted_features)
    return EventCluster(
        cluster_id=_cluster_id(symbol, sorted_features),
        symbol=symbol,
        members=sorted_members,
        event_type=_classify_event_type(sorted_members),
        representative_title=representative.title,
        source_diversity=len(providers),
        entities=entities,
        first_seen=first_seen,
    )


def _build_features(item: NewsEvidence) -> _EvidenceFeatures:
    title_key = _normalize_title(item.title)
    return _EvidenceFeatures(
        item=item,
        normalized_url=_normalize_url(item.url),
        title_key=title_key,
        title_tokens=frozenset(_title_tokens(title_key)),
        entities=tuple(_extract_entities(item.title, item.symbol)),
    )


def _cluster_id(symbol: str, features: list[_EvidenceFeatures]) -> str:
    basis = "|".join(
        sorted(feature.normalized_url or feature.title_key for feature in features)
    )
    digest = hashlib.sha1(f"{symbol}|{basis}".encode()).hexdigest()[:12]
    return f"evt_{symbol}_{digest}"


def _evidence_sort_key(item: NewsEvidence) -> tuple[datetime, str, str, str]:
    return (item.published_at, item.provider, item.source_name, _normalize_url(item.url))


def _normalize_title(title: str) -> str:
    return _PUNCT_RE.sub("", title).lower()


def _title_tokens(title_key: str) -> set[str]:
    tokens = {token.lower() for token in _ALNUM_RE.findall(title_key) if len(token) >= 2}
    for run in _CJK_RUN_RE.findall(title_key):
        if len(run) <= 2:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _extract_entities(title: str, symbol: str) -> list[str]:
    entities = [symbol] if symbol else []
    entities.extend(_CODE_RE.findall(title))
    compact_title = _normalize_title(title)

    for suffix in _COMPANY_SUFFIXES:
        for match in re.finditer(re.escape(suffix.lower()), compact_title):
            start = max(0, match.start() - 4)
            candidate = compact_title[start : match.end()]
            if _looks_like_entity_candidate(candidate):
                entities.append(candidate)

    lower_title = title.lower()
    for keyword in _PRODUCT_KEYWORDS:
        if keyword.lower() in lower_title:
            entities.append(keyword)

    return _dedupe_preserve_order(entities)


def _looks_like_entity_candidate(candidate: str) -> bool:
    return len(candidate) >= 2 and not any(term in candidate for term in _ENTITY_ACTION_TERMS)


def _merge_entities(features: list[_EvidenceFeatures]) -> list[str]:
    entities: list[str] = []
    for feature in features:
        entities.extend(feature.entities)
    return _dedupe_preserve_order(entities)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _title_information_score(title: str, symbol: str) -> int:
    return len(_normalize_title(title)) + 3 * len(_extract_entities(title, symbol))


def _provider_key(item: NewsEvidence) -> str:
    return item.provider.strip().lower()


def _classify_event_type(members: list[NewsEvidence]) -> str:
    text = " ".join(member.title for member in members)
    for event_type, keywords in _EVENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return event_type
    return "unknown"


def _is_obvious_noise(item: NewsEvidence) -> bool:
    title = item.title.strip()
    if not title:
        return True
    compact = _normalize_title(title)
    lowered = title.lower()
    return (
        _is_ad_noise(lowered)
        or _is_pure_list_noise(compact)
        or _is_pure_quote_noise(title, compact)
    )


def _is_ad_noise(lowered_title: str) -> bool:
    return any(term in lowered_title for term in _AD_TERMS)


def _is_pure_list_noise(compact_title: str) -> bool:
    if "龙虎榜" in compact_title:
        return False
    return any(term in compact_title for term in _LIST_NOISE_TERMS)


def _is_pure_quote_noise(title: str, compact_title: str) -> bool:
    if _has_event_keyword(title):
        return False
    if _QUOTE_ONLY_RE.fullmatch(title) and any(character.isdigit() for character in title):
        return "%" in title or "." in title
    return any(term in compact_title for term in _QUOTE_NOISE_TERMS)


def _has_event_keyword(title: str) -> bool:
    return any(keyword in title for keywords in _EVENT_KEYWORDS.values() for keyword in keywords)
