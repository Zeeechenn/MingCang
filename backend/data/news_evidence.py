"""Source-agnostic news evidence contracts for the M54 adapter layer."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from backend.data.news_models import RawNews

ContentStatus = Literal["full", "excerpt", "title_only"]


@dataclass
class NewsEvidence:
    symbol: str
    title: str
    url: str
    published_at: datetime
    source_name: str
    provider: str
    content: str | None = None
    content_status: ContentStatus = "title_only"
    language: str = "zh"
    fetched_at: datetime | None = None
    raw: dict | None = None

    def __post_init__(self) -> None:
        content = self.content.strip() if self.content else ""
        self.content = content or None
        self.content_status = "full" if self.content else "title_only"


@dataclass(frozen=True)
class NewsWindow:
    lookback_days: int | None = None
    limit: int | None = None
    max_results: int | None = None
    as_of: datetime | None = None


class NewsSourceAdapter(Protocol):
    name: str
    requires_key: bool
    provides_content: bool

    def fetch(self, symbol: str, window: NewsWindow) -> list[NewsEvidence]: ...


def evidence_from_raw_news(
    item: RawNews,
    *,
    symbol: str,
    provider: str,
    fetched_at: datetime | None = None,
) -> NewsEvidence:
    """Map the legacy RawNews shape into source-agnostic evidence."""
    return NewsEvidence(
        symbol=item.symbol or symbol,
        title=item.title,
        url=item.url,
        published_at=item.published_at,
        source_name=item.source,
        provider=item.provider or provider,
        content=item.content,
        fetched_at=fetched_at,
    )


def evidence_from_title_only_news(
    title: str,
    *,
    symbol: str,
    provider: str,
    published_at: datetime | None = None,
    fetched_at: datetime | None = None,
) -> NewsEvidence:
    """Map a title-only source into evidence.

    Tavily/iFinD title fetchers do not expose canonical URLs, body content, or
    true publication timestamps. The synthetic URL is a stable local identity
    key, and ``published_at`` falls back to ``as_of``/fetch time, so freshness
    calculations for these sources are approximate.
    """
    current = fetched_at or datetime.now(UTC).replace(tzinfo=None)
    digest = hashlib.md5(title.strip().encode()).hexdigest()[:12]  # noqa: S324
    return NewsEvidence(
        symbol=symbol,
        title=title,
        url=f"{provider}://{symbol}#{digest}",
        published_at=published_at or current,
        source_name=provider,
        provider=provider,
        content=None,
        fetched_at=current,
    )
