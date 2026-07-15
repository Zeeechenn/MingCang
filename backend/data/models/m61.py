"""M61 category data models."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.orm import Base, _utcnow


class Announcement(Base):
    """Company announcement captured from normalized category providers."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    asset_key: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    market: Mapped[str] = mapped_column(String, default="CN", index=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    ann_type: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


def _fill_announcement_identity(_mapper, _connection, target: Announcement) -> None:
    from backend.data.market_profiles import (
        get_market_profile,
        instrument_key,
        normalize_market,
        normalize_symbol,
    )

    target.market = normalize_market(target.market)
    target.symbol = normalize_symbol(target.symbol, target.market)
    target.asset_key = instrument_key(target.market, target.symbol)
    target.currency = target.currency or get_market_profile(target.market).currency


event.listen(Announcement, "before_insert", _fill_announcement_identity)
event.listen(Announcement, "before_update", _fill_announcement_identity)


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


class FundFlow(Base):
    """Daily fund-flow snapshot from M61 category providers.

    Net-flow amounts are stored in raw yuan.
    """

    __tablename__ = "fund_flows"
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", "provider", name="uq_fund_flow_symbol_date_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    trade_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    main_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    super_large_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    large_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    medium_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    small_net: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MarketTemperatureSnapshot(Base):
    """Observe-only postmarket snapshot for limit-up board pools."""

    __tablename__ = "market_temperature_snapshots"
    __table_args__ = (
        UniqueConstraint("snap_date", "pool_type", "code", name="uq_market_temperature_snap_pool_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snap_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    pool_type: Mapped[str] = mapped_column(String, index=True)
    code: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fields_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class OverseasSnapshot(Base):
    """Research-only overseas leading-indicator snapshot."""

    __tablename__ = "overseas_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "snap_date", "provider", name="uq_overseas_snapshot_symbol_date_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    snap_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    chg_pct_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    chg_pct_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
