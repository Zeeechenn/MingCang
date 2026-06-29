"""iFinD wrapper for the M54 source-agnostic news adapter layer."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.data.news import fetch_news_ifind
from backend.data.news_evidence import NewsEvidence, NewsWindow, evidence_from_raw_news

NameResolver = Callable[[str], str]


class IFindAdapter:
    name = "ifind"
    requires_key = True
    provides_content = True

    def __init__(self, name_resolver: NameResolver | None = None) -> None:
        self._name_resolver = name_resolver or (lambda symbol: symbol)

    def fetch(self, symbol: str, window: NewsWindow) -> list[NewsEvidence]:
        """Fetch iFinD MCP news/notice rows as content-bearing evidence."""
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        days = window.lookback_days if window.lookback_days is not None else 7
        max_results = window.max_results if window.max_results is not None else 20
        return [
            evidence_from_raw_news(
                item,
                symbol=symbol,
                provider=self.name,
                fetched_at=fetched_at,
            )
            for item in fetch_news_ifind(
                symbol,
                self._name_resolver(symbol),
                days=days,
                max_results=max_results,
            )
        ]
