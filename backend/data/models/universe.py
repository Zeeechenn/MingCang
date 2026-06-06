"""Dynamic universe snapshots and Gate-B prospective observations."""
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


class UniverseSnapshot(Base):
    """
    M38 Dynamic Universe / Survivorship Guard — one row per point-in-time universe snapshot.

    Append-only: past rows are never mutated.  The (cutoff_date, market_filter,
    universe_hash) triple is unique, making snapshot_universe() idempotent.
    Used exclusively by backtest and forward-validation contexts.
    """
    __tablename__ = "universe_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "cutoff_date", "market_filter", "universe_hash",
            name="uq_universe_snapshot_cutoff_market_hash",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    universe_hash: Mapped[str] = mapped_column(String(64), index=True)
    cutoff_date: Mapped[str] = mapped_column(String, index=True)   # "YYYY-MM-DD"
    market_filter: Mapped[str] = mapped_column(String, default="ALL")  # CN | US | ALL
    symbols_json: Mapped[str] = mapped_column(Text)                # JSON array of sorted symbol strings
    n_symbols: Mapped[int] = mapped_column(Integer)
    provenance_completeness_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GateBObservation(Base):
    """
    M40 Gate-B prospective tracker — one row per live signal evaluated AS-OF its signal date.

    Accumulates gate verdicts (with copilot_present stripped for the experiment variant)
    and later fills in the 5-trading-day after-cost forward return for Gate-B dataset.
    Additive only — never updates any production table.
    """
    __tablename__ = "gate_b_observations"
    __table_args__ = (
        UniqueConstraint("signal_id", "as_of", name="uq_gate_b_obs_signal_as_of"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    signal_date: Mapped[str] = mapped_column(String, index=True)   # ISO date of source Signal row
    as_of: Mapped[str] = mapped_column(String, index=True)         # evaluation window date (== signal_date for prospective)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)    # bare int ref, no FK
    label_id: Mapped[int | None] = mapped_column(Integer, nullable=True)     # bare int ref to LongTermLabel.id
    gate_pass_full: Mapped[bool] = mapped_column(Boolean)                    # raw M33 gate_pass with all blockers
    gate_pass_variant: Mapped[bool] = mapped_column(Boolean)                 # copilot_present excluded
    card_pass: Mapped[bool] = mapped_column(Boolean)                         # validity_card['card_pass']
    ready_variant: Mapped[bool] = mapped_column(Boolean)                     # gate_pass_variant AND card_pass
    recommendation: Mapped[str | None] = mapped_column(String, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_close: Mapped[float | None] = mapped_column(Float, nullable=True)  # Price.close on signal_date
    horizon_days: Mapped[int] = mapped_column(Integer, default=5)
    forward_status: Mapped[str] = mapped_column(String, default="pending")   # 'pending' | 'realized' | 'unrealizable'
    realized_at: Mapped[str | None] = mapped_column(String, nullable=True)   # ISO date when fwd return was filled
    forward_return_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    forward_return_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    blockers_json: Mapped[str | None] = mapped_column(Text, nullable=True)         # raw blockers incl. copilot_present
    blockers_variant_json: Mapped[str | None] = mapped_column(Text, nullable=True) # after removing copilot_present
    checks_json: Mapped[str | None] = mapped_column(Text, nullable=True)           # full checks dict
    gate_b_tracker_version: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
