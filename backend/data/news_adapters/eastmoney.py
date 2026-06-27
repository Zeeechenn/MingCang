"""Eastmoney wrapper for the M54 source-agnostic news adapter layer."""
from __future__ import annotations

from datetime import UTC, datetime

from backend.data.news import fetch_stock_news_cn
from backend.data.news_evidence import NewsEvidence, NewsWindow, evidence_from_raw_news


class EastmoneyAdapter:
    name = "eastmoney"
    requires_key = False
    provides_content = True

    def fetch(self, symbol: str, window: NewsWindow) -> list[NewsEvidence]:
        limit = window.limit if window.limit is not None else 20
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        return [
            evidence_from_raw_news(
                item,
                symbol=symbol,
                provider=self.name,
                fetched_at=fetched_at,
            )
            for item in fetch_stock_news_cn(symbol, limit=limit)
        ]
