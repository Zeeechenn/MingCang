"""iFinD title-only wrapper for the M54 news adapter layer."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.data.news import fetch_titles_ifind
from backend.data.news_evidence import (
    NewsEvidence,
    NewsWindow,
    evidence_from_title_only_news,
)

NameResolver = Callable[[str], str]


class IFindAdapter:
    name = "ifind"
    requires_key = True
    provides_content = False

    def __init__(self, name_resolver: NameResolver | None = None) -> None:
        self._name_resolver = name_resolver or (lambda symbol: symbol)

    def fetch(self, symbol: str, window: NewsWindow) -> list[NewsEvidence]:
        """Fetch iFinD MCP titles as title-only evidence.

        The current iFinD fetcher returns only titles from news/notice search.
        It has no canonical URL, body text, or real publication timestamp, so
        freshness uses ``window.as_of`` when supplied and otherwise fetch time.
        """
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        published_at = window.as_of or fetched_at
        days = window.lookback_days if window.lookback_days is not None else 2
        max_results = window.max_results if window.max_results is not None else 5
        return [
            evidence_from_title_only_news(
                title,
                symbol=symbol,
                provider=self.name,
                published_at=published_at,
                fetched_at=fetched_at,
            )
            for title in fetch_titles_ifind(
                symbol,
                self._name_resolver(symbol),
                days=days,
                max_results=max_results,
            )
        ]
