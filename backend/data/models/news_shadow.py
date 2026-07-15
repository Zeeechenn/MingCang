"""M68 production-mirror news pyramid runs and operator feedback."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.orm import Base, _utcnow


class NewsShadowRun(Base):
    """One idempotent, observe-only comparison for a symbol and as-of date."""

    __tablename__ = "news_shadow_runs"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "as_of",
            "profile",
            name="uq_news_shadow_symbol_as_of_profile",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[str] = mapped_column(String, index=True)
    profile: Mapped[str] = mapped_column(String, default="production_mirror", index=True)
    status: Mapped[str] = mapped_column(String, index=True)

    legacy_signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_signal_date: Mapped[str | None] = mapped_column(String, nullable=True)
    legacy_sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    legacy_composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    legacy_recommendation: Mapped[str | None] = mapped_column(String, nullable=True)
    legacy_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    pyramid_sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pyramid_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    flow_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    counterfactual_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    counterfactual_recommendation: Mapped[str | None] = mapped_column(String, nullable=True)
    counterfactual_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    would_change_action: Mapped[bool] = mapped_column(Boolean, default=False)
    event_risk_level: Mapped[str] = mapped_column(String, default="unavailable", index=True)
    event_risk_reasons_json: Mapped[str] = mapped_column(Text, default="[]")

    price_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    attribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    degradation_flags_json: Mapped[str] = mapped_column(Text, default="[]")

    model_tier: Mapped[str] = mapped_column(String, default="capable")
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    cache_version: Mapped[str] = mapped_column(String, default="m68.news-shadow.v1")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_spent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class NewsShadowFeedback(Base):
    """Human trial feedback, kept separate from the immutable run evidence."""

    __tablename__ = "news_shadow_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    evidence_ref: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    preferred_path: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
