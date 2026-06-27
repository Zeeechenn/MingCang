"""Shared news data models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawNews:
    title: str
    url: str
    published_at: datetime
    source: str
    symbol: str | None = None
    content: str | None = None
    provider: str | None = None
