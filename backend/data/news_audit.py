"""Lightweight news source audit for sentiment inputs."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timezone
from urllib.parse import urlparse

from backend.data.news import RawNews

STRONG_SOURCES = {
    "上交所", "深交所", "巨潮资讯", "证监会", "交易所",
    "证券时报", "中国证券报", "上海证券报", "经济参考报",
}
NORMAL_SOURCES = {
    "东方财富", "财联社", "界面新闻", "证券日报", "新浪财经",
    "腾讯财经", "网易财经", "同花顺", "格隆汇",
}
WEAK_SOURCE_KEYWORDS = ("股吧", "论坛", "自媒体", "雪球用户", "网传", "传闻")


@dataclass(frozen=True)
class NewsAudit:
    """Audited news item with a confidence score and source-risk flags."""

    news: RawNews
    score: int
    usable: bool
    risk_flags: list[str]
    duplicate_group: str

    @property
    def title(self) -> str:
        """Return the underlying news title."""
        return self.news.title


def _normalized_title(title: str) -> str:
    """Normalize a title for duplicate grouping."""
    text = re.sub(r"\s+", "", title or "").lower()
    text = re.sub(r"[，。、“”‘’：:；;！!？?（）()\[\]【】]", "", text)
    return text


def _duplicate_group(title: str) -> str:
    """Stable short hash for a normalized title."""
    return hashlib.md5(_normalized_title(title).encode()).hexdigest()[:10]


def _source_score(source: str) -> tuple[int, list[str]]:
    """Score source credibility using a small explicit allow/degrade list."""
    flags: list[str] = []
    if any(key in source for key in STRONG_SOURCES):
        return 100, flags
    if any(key in source for key in NORMAL_SOURCES):
        return 80, flags
    if any(key in source for key in WEAK_SOURCE_KEYWORDS):
        flags.append("weak_source")
        return 35, flags
    return 60, flags


def _url_score(url: str) -> tuple[int, list[str]]:
    """Score whether the URL is externally traceable."""
    flags: list[str] = []
    parsed = urlparse(url or "")
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return 100, flags
    if parsed.scheme == "em":
        flags.append("synthetic_url")
        return 35, flags
    flags.append("invalid_url")
    return 20, flags


def _freshness_score(published_at: datetime, now: datetime) -> tuple[int, list[str]]:
    """Score news freshness for short-term sentiment use."""
    flags: list[str] = []
    age_days = max(0, (now - published_at).total_seconds() / 86400)
    if age_days <= 1:
        return 100, flags
    if age_days <= 3:
        return 80, flags
    if age_days <= 7:
        return 55, flags
    flags.append("stale")
    return 20, flags


def audit_news_items(
    items: list[RawNews],
    *,
    now: datetime | None = None,
    min_score: int = 50,
) -> list[NewsAudit]:
    """Audit news items and return score-sorted results.

    This is intentionally deterministic and cheap enough for the daily signal
    path. It does not crawl pages or call an LLM.
    """
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    seen_groups: set[str] = set()
    audits: list[NewsAudit] = []
    for item in items:
        group = _duplicate_group(item.title)
        source_score, source_flags = _source_score(item.source or "")
        url_score, url_flags = _url_score(item.url or "")
        fresh_score, fresh_flags = _freshness_score(item.published_at, current)
        flags = [*source_flags, *url_flags, *fresh_flags]

        score = round(source_score * 0.45 + url_score * 0.30 + fresh_score * 0.25)
        if group in seen_groups:
            flags.append("duplicate_title")
            score = max(0, score - 20)
        seen_groups.add(group)

        audits.append(NewsAudit(
            news=item,
            score=int(score),
            usable=score >= min_score and "stale" not in flags,
            risk_flags=flags,
            duplicate_group=group,
        ))
    return sorted(audits, key=lambda audit: audit.score, reverse=True)


def audited_titles(
    items: list[RawNews],
    *,
    now: datetime | None = None,
    min_score: int = 50,
    limit: int = 15,
) -> tuple[list[str], list[NewsAudit]]:
    """Return usable titles plus the full audit trail."""
    audits = audit_news_items(items, now=now, min_score=min_score)
    titles = [audit.title for audit in audits if audit.usable][:limit]
    return titles, audits
