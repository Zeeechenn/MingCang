"""Market data: watchlist, positions, prices, news, index, snapshots, fundamentals."""
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


class Stock(Base):
    """自选股列表"""
    __tablename__ = "stocks"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)   # e.g. "600519" or "AAPL"
    name: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)                      # "CN", "HK", or "US"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)     # 申万一级行业（由 sync_industry 回填）
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Position(Base):
    """手动维护的真实/模拟持仓。"""
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    market: Mapped[str] = mapped_column(String, default="CN")
    quantity: Mapped[float] = mapped_column(Float)
    avg_cost: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[str] = mapped_column(String, index=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open / closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Price(Base):
    """日线行情"""
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_price_symbol_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[str] = mapped_column(String, index=True)           # "2024-01-15"
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    atr14: Mapped[float | None] = mapped_column(Float, nullable=True)        # 预计算 ATR(14)
    source: Mapped[str | None] = mapped_column(String, nullable=True)         # M29 provenance: provider id
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    adjustment: Mapped[str | None] = mapped_column(String, nullable=True)     # qfq / forward_additive / auto_adjust


class NewsItem(Base):
    """新闻条目"""
    __tablename__ = "news"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String, index=True, nullable=True)  # None = 宏观新闻
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)       # LLM 生成摘要
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1.0 ~ +1.0
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class IndexPrice(Base):
    """大盘指数日线（用于宏观相对强弱对比）"""
    __tablename__ = "index_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)    # e.g. "sh000300"（沪深300）
    date: Mapped[str] = mapped_column(String, index=True)      # "2024-01-15"
    close: Mapped[float] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    adjustment: Mapped[str | None] = mapped_column(String, nullable=True)


class MarketSnapshot(Base):
    """
    日频市值/股本/资金流快照。

    作为 M6.1 数据底座，字段可由 Tushare/AkShare/yfinance 等来源逐步填充。
    """
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_ms_symbol_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[str] = mapped_column(String, index=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    float_market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Float, nullable=True)
    north_net_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    large_order_net_inflow: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class FinancialMetric(Base):
    """
    季度财务指标（长期分析师团数据基础）
    来源：akshare stock_lrb_em / stock_zcfz_em / stock_xjll_em
    """
    __tablename__ = "financial_metrics"
    __table_args__ = (UniqueConstraint("symbol", "report_date", name="uq_fm_symbol_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    report_date: Mapped[str] = mapped_column(String, index=True)        # "2024-09-30"
    disclosure_date: Mapped[str | None] = mapped_column(String, index=True, nullable=True)  # 实际披露日，缺失时回退 report_date
    period_type: Mapped[str | None] = mapped_column(String, nullable=True)     # "Q1"/"Q2"/"Q3"/"Annual"
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_yoy: Mapped[float | None] = mapped_column(Float, nullable=True)      # 营业总收入同比 %
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_yoy: Mapped[float | None] = mapped_column(Float, nullable=True)   # 净利润同比 %
    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    long_term_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_cf: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)              # 计算: 净利润 / 净资产
    asset_turnover: Mapped[float | None] = mapped_column(Float, nullable=True)   # 计算: 收入 / 总资产
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)          # 完整原始字段备份
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
