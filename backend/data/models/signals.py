"""Signal output, sentiment cache, and long-term analyst labels."""
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


class Signal(Base):
    """信号记录"""
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[str] = mapped_column(String, index=True)
    quant_score: Mapped[float | None] = mapped_column(Float, nullable=True)      # Qlib 量化得分
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 技术分析得分
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 新闻情感得分
    composite_score: Mapped[float] = mapped_column(Float)                 # 综合得分 -100~+100
    recommendation: Mapped[str] = mapped_column(String)                 # 强买/买/观望/卖/强卖
    confidence: Mapped[str] = mapped_column(String)                     # 高/中/低
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_status: Mapped[str | None] = mapped_column(String, nullable=True)    # normal / limit_up / limit_down
    llm_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)     # LLM 综合判断理由
    rule_version: Mapped[str | None] = mapped_column(String, nullable=True)     # 决策规则版本
    data_timestamp: Mapped[str | None] = mapped_column(String, nullable=True)   # 信号使用的数据日期/时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SentimentCache(Base):
    """Persistent cache for expensive news sentiment LLM calls."""
    __tablename__ = "sentiment_cache"
    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    titles_hash: Mapped[str] = mapped_column(String, index=True)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class LongTermLabel(Base):
    """
    长期分析师团输出标签（周频更新，10 天 TTL）
    label ∈ {值得持有, 估值偏高, 观望, 规避}
    """
    __tablename__ = "long_term_labels"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_ltl_symbol_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[str] = mapped_column(String, index=True)               # 生成日 "2026-05-17"
    label: Mapped[str] = mapped_column(String)                          # 值得持有/估值偏高/观望/规避
    score: Mapped[float] = mapped_column(Float)                           # 团综合分 -100~+100
    votes_json: Mapped[str | None] = mapped_column(Text, nullable=True)        # {role: vote} JSON
    key_findings_json: Mapped[str | None] = mapped_column(Text, nullable=True) # [str] JSON，≤6 条
    expires_at: Mapped[str] = mapped_column(String)                     # "2026-05-27"
    quality: Mapped[str] = mapped_column(String, default="degraded")    # trusted/degraded/failed
    constraint_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
