"""Data degradation event model."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
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
