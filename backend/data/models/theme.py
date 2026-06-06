"""Theme hypothesis engine records."""
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


class ThemeRecord(Base):
    """
    M36 Theme Hypothesis Engine — one row per theme/sector under study.

    Status values: 'active' | 'watch' | 'archived'.
    """
    __tablename__ = "theme_records"
    __table_args__ = (UniqueConstraint("theme_name", name="uq_theme_records_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theme_name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active / watch / archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ThemeHypothesis(Base):
    """
    M36 Theme Hypothesis Engine — one row per hypothesis under a theme.

    Status values: 'proposed' | 'supported' | 'contradicted' | 'invalidated'.
    beneficiary_tiers_json is advisory display metadata only — never read by
    aggregate(), aggregate_v2(), run_pipeline(), or apply_research_constraints().
    forward_evidence_ref_json is a reserved stub; populated by M39 when M29
    promotion gate passes.
    """
    __tablename__ = "theme_hypotheses"
    __table_args__ = (UniqueConstraint("theme_id", "statement", name="uq_theme_hypotheses_theme_statement"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theme_id: Mapped[int] = mapped_column(Integer, index=True)  # plain FK, no ForeignKey() constraint (M35 style)
    statement: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="proposed")  # proposed / supported / contradicted / invalidated
    beneficiary_tiers_json: Mapped[str | None] = mapped_column(Text, nullable=True)    # advisory display only — JSON array of {symbol, tier, rationale}
    evidence_gaps_json: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON array of strings
    invalidation_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of strings
    ai_supply_chain_json: Mapped[str | None] = mapped_column(Text, nullable=True)      # observe-only template payload; never used for scoring
    forward_evidence_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True) # populated by M39 when M29 promotion gate passes
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
