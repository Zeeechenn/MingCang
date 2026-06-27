"""Anspire wrapper for the M54 source-agnostic news adapter layer."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from backend.data.news import fetch_stock_news_anspire
from backend.data.news_evidence import NewsEvidence, NewsWindow, evidence_from_raw_news

NameResolver = Callable[[str], str]


class AnspireAdapter:
    name = "anspire"
    requires_key = True
    provides_content = True

    def __init__(self, name_resolver: NameResolver | None = None) -> None:
        self._name_resolver = name_resolver or (lambda symbol: symbol)

    def fetch(self, symbol: str, window: NewsWindow) -> list[NewsEvidence]:
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        return [
            evidence_from_raw_news(
                item,
                symbol=symbol,
                provider=self.name,
                fetched_at=fetched_at,
            )
            for item in fetch_stock_news_anspire(
                symbol,
                self._name_resolver(symbol),
                days=window.lookback_days,
                max_results=window.max_results,
                limit=window.limit,
            )
        ]
