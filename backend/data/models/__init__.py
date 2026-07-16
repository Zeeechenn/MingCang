"""ORM models package — domain-split, re-exported for a stable import surface.

All models register on the shared ``backend.data.orm.Base``.
"""
from backend.data.models.chat import (
    ChatMessage,
    ChatSession,
    LlmUsageLog,
)
from backend.data.models.decision import (
    DecisionRun,
    PendingAIAction,
    ResearchState,
    ReviewRun,
)
from backend.data.models.degradation import (
    DegradationEvent,
)
from backend.data.models.job import (
    JobRun,
)
from backend.data.models.m61 import (
    Announcement,
    CorporateEvent,
    FundFlow,
    HolderSnapshot,
    LhbRecord,
    MarketTemperatureSnapshot,
    OverseasSnapshot,
    ResearchReport,
)
from backend.data.models.market import (
    FinancialMetric,
    IndexPrice,
    MarketSnapshot,
    NewsItem,
    Position,
    Price,
    Stock,
)
from backend.data.models.memory import (
    DecisionMemoryLayered,
    MemoryAtom,
    MemoryProfile,
    MemoryPromotionCandidate,
    MemoryScenario,
    StockMemoryItem,
)
from backend.data.models.news_shadow import (
    NewsShadowFeedback,
    NewsShadowRun,
)
from backend.data.models.review import (
    ReviewCase,
)
from backend.data.models.signals import (
    LongTermLabel,
    SentimentCache,
    Signal,
)
from backend.data.models.theme import (
    ThemeHypothesis,
    ThemeRecord,
)
from backend.data.models.thesis import (
    ForwardThesis,
    ThesisConfidenceEntry,
    ThesisRecord,
)
from backend.data.models.universe import (
    GateBObservation,
    UniverseSnapshot,
)
from backend.data.orm import Base

__all__ = [
    "Base",
    "Stock",
    "Position",
    "Price",
    "NewsItem",
    "IndexPrice",
    "MarketSnapshot",
    "FinancialMetric",
    "Announcement",
    "ResearchReport",
    "LhbRecord",
    "CorporateEvent",
    "HolderSnapshot",
    "FundFlow",
    "MarketTemperatureSnapshot",
    "OverseasSnapshot",
    "Signal",
    "SentimentCache",
    "LongTermLabel",
    "DecisionRun",
    "ResearchState",
    "ReviewRun",
    "PendingAIAction",
    "DegradationEvent",
    "JobRun",
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
    "NewsShadowRun",
    "NewsShadowFeedback",
]
