"""ORM models package — domain-split, re-exported for a stable import surface.

All 31 models register on the shared ``backend.data.orm.Base``.
"""
from backend.data.orm import Base
from backend.data.models.market import (
    Stock,
    Position,
    Price,
    NewsItem,
    IndexPrice,
    MarketSnapshot,
    FinancialMetric,
)
from backend.data.models.signals import (
    Signal,
    SentimentCache,
    LongTermLabel,
)
from backend.data.models.decision import (
    DecisionRun,
    ResearchState,
    ReviewRun,
    PendingAIAction,
)
from backend.data.models.memory import (
    DecisionMemoryLayered,
    StockMemoryItem,
    MemoryAtom,
    MemoryScenario,
    MemoryProfile,
    MemoryPromotionCandidate,
)
from backend.data.models.chat import (
    ChatSession,
    ChatMessage,
    LlmUsageLog,
)
from backend.data.models.thesis import (
    ThesisRecord,
    ThesisConfidenceEntry,
    ForwardThesis,
)
from backend.data.models.theme import (
    ThemeRecord,
    ThemeHypothesis,
)
from backend.data.models.review import (
    ReviewCase,
)
from backend.data.models.universe import (
    UniverseSnapshot,
    GateBObservation,
)

__all__ = [
    "Base",
    "Stock",
    "Position",
    "Price",
    "NewsItem",
    "IndexPrice",
    "MarketSnapshot",
    "FinancialMetric",
    "Signal",
    "SentimentCache",
    "LongTermLabel",
    "DecisionRun",
    "ResearchState",
    "ReviewRun",
    "PendingAIAction",
    "DecisionMemoryLayered",
    "StockMemoryItem",
    "MemoryAtom",
    "MemoryScenario",
    "MemoryProfile",
    "MemoryPromotionCandidate",
    "ChatSession",
    "ChatMessage",
    "LlmUsageLog",
    "ThesisRecord",
    "ThesisConfidenceEntry",
    "ForwardThesis",
    "ThemeRecord",
    "ThemeHypothesis",
    "ReviewCase",
    "UniverseSnapshot",
    "GateBObservation",
]
