"""Bounded Tavily news adapter shared by research and maintenance workflows."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import requests

from backend.config import settings
from backend.data.database import Stock
from backend.data.news import RawNews

logger = logging.getLogger(__name__)


def fetch_tavily_news(stock: Stock, limit: int = 3) -> list[RawNews]:
    """Fetch a bounded recent-news fallback without persisting results."""
    if not settings.tavily_api_key:
        return []
    symbol = str(stock.symbol)
    name = str(stock.name)
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": f"{name} {symbol} 股票 最新消息 公告 业绩",
                "search_depth": "basic",
                "max_results": limit,
                "days": 1,
                "include_answer": False,
            },
            proxies={"http": "", "https": ""},
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("tavily news fallback failed %s: %s", symbol, exc)
        return []

    items: list[RawNews] = []
    for row in response.json().get("results", []):
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.") or "tavily"
        items.append(
            RawNews(
                title=title,
                url=url,
                published_at=datetime.now(UTC).replace(tzinfo=None),
                source=f"tavily:{host}",
                symbol=symbol,
            )
        )
    return items


__all__ = ["fetch_tavily_news"]
