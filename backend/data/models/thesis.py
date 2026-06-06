"""Thesis ledger, confidence history, and forward thesis records."""
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


class ThesisRecord(Base):
    """
    M35 Thesis Ledger — one row per investment thesis.

    Status state machine:
      active <-> watch; active/watch -> broken/retired; broken -> retired.
      retired is terminal.
    """
    __tablename__ = "thesis_records"
    __table_args__ = (UniqueConstraint("symbol", "title", name="uq_thesis_records_symbol_title"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")  # active / watch / broken / retired
    kill_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON array of strings
    update_cadence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_case_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    research_case_as_of: Mapped[str | None] = mapped_column(String, nullable=True)  # ISO date string
    review_case_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # populated by M37
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ThesisConfidenceEntry(Base):
    """
    M35 Thesis Ledger — append-only confidence history per thesis.

    Never updated; a new row is inserted on each confidence reading.
    """
    __tablename__ = "thesis_confidence_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float)          # clamped [0.0, 1.0]
    as_of: Mapped[str] = mapped_column(String)           # ISO date string
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ForwardThesis(Base):
    """
    M39 Forward Thesis Beta — bounded forward judgment record.

    confidence_low / confidence_high are a judgment band only, NEVER a buy score.
    No price_target, direction, or buy_score columns by design.

    Append-on-update: past rows are updated in place (status transitions, band updates).
    The (symbol, statement, horizon_date) tuple is unique for non-NULL horizons.
    Runtime schema setup also creates a normalised unique index so SQLite NULLs
    do not bypass direct-SQL duplicate checks. create_forward_thesis keeps an
    explicit NULL-horizon lookup for application-level idempotency.
    """
    __tablename__ = "forward_theses"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "statement", "horizon_date",
            name="uq_forward_theses_symbol_statement_horizon",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    statement: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="draft", index=True)
    horizon_date: Mapped[str | None] = mapped_column(String, nullable=True)
    # Confidence band — bounded judgment only, NOT a buy score or signal score
    confidence_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON columns
    evidence_manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Review schedule
    next_review_date: Mapped[str | None] = mapped_column(String, nullable=True)
    review_cadence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bare int cross-references (no FK constraints)
    thesis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    theme_hypothesis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    universe_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
