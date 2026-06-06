"""Review / calibration / memory-loop case records."""
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


class ReviewCase(Base):
    """
    M37 Review / Calibration / Memory Loop — one row per signal-review event.

    Links a signal (by id), an optional thesis (by id), and an optional
    ResearchCase (by symbol+as_of) into a single review record.  Outcome
    attribution data is stored verbatim from review_latest_signal().
    position_case_ref_json is a nullable stub for a future PositionCase milestone.

    No ForeignKey() constraints — plain integer references following M35 style.
    UniqueConstraint on (symbol, as_of) makes create_review_case idempotent.
    """
    __tablename__ = "review_cases"
    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_review_cases_symbol_as_of"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[str] = mapped_column(String, index=True)            # ISO date — the signal/review date
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # bare int, no FK constraint
    thesis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # bare int, links to ThesisRecord.id
    research_case_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    research_case_as_of: Mapped[str | None] = mapped_column(String, nullable=True)
    position_case_ref_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="populated when PositionCase is built (future milestone)",
    )
    outcome_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # True/False/None from review
    next_day_return: Mapped[float | None] = mapped_column(Float, nullable=True)    # percent, 2dp
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String, nullable=True)      # BUY/HOLD/SELL
    attribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON list of Chinese attribution strings
    review_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # full JSON blob from review_latest_signal
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
