"""M61 category data models."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.orm import Base, _utcnow


class Announcement(Base):
    """Company announcement captured from normalized category providers."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    ann_type: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ResearchReport(Base):
    """Sell-side research report metadata."""

    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    org_name: Mapped[str] = mapped_column(String)
    rating: Mapped[str | None] = mapped_column(String, nullable=True)
    eps_forecast_y1: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_forecast_y2: Mapped[float | None] = mapped_column(Float, nullable=True)
    publish_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    info_code: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class LhbRecord(Base):
    """Dragon tiger list record."""

    __tablename__ = "lhb_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    trade_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    net_buy_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_seats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sell_seats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CorporateEvent(Base):
    """Corporate event captured from normalized category providers."""

    __tablename__ = "corporate_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    event_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class HolderSnapshot(Base):
    """Share capital and top-holder snapshot."""

    __tablename__ = "holder_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    report_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    float_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    top10_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    holder_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
