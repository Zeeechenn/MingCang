"""Data degradation event model."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.orm import Base, _utcnow


class DegradationEvent(Base):
    """Provider/data contract degradation event."""
    __tablename__ = "degradation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    component: Mapped[str] = mapped_column(String, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, index=True)
    error: Mapped[str] = mapped_column(String(500))
    context_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class AdjustmentBasisClearance(Base):
    """Operator's explicit "I looked at this drift and dealt with it" record.

    Before this table ``summarize_basis_drift_events`` had no clearance path at
    all: a same-source drift event marked its day ``uncleared`` forever, and
    because ``one_loop_continuity`` fails the whole window on *any* incomplete
    day, a single re-basing event permanently blocked the 20-day gate no matter
    how many clean days followed (2026-09-09 / 603993 is the case that surfaced
    it).  ``rebase_price_history`` cannot close the loop either — it refuses to
    write production by design.

    The clearance is deliberately a *separate row*, never an edit to the
    ``degradation_events`` row it refers to: the evidence that drift happened
    must survive, and acknowledging it is a claim by a named operator with a
    stated reason, which is itself evidence.  ``event_date`` is the day being
    cleared, not the day someone got around to clearing it, so a clearance
    recorded later still applies to the right panel.
    """

    __tablename__ = "adjustment_basis_clearances"
    __table_args__ = (
        UniqueConstraint("symbol", "event_date", name="uq_basis_clearance_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    event_date: Mapped[str] = mapped_column(String(10), index=True)
    operator: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(500))
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
