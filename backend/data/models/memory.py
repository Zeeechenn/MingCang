"""Layered decision memory and L0 memory atoms/scenarios/profiles."""
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


class DecisionMemoryLayered(Base):
    """M9.1 分层决策记忆迁 DB：medium(symbol) / long(symbol=NULL) 两层。

    content 是整段 markdown（与原 `~/.stock-sage/memory/{medium_X.md,
    long_term_reflection.md}` 文件 1:1 对应），写入时整体覆盖。
    旧文件保留 30 天作为只读兜底。
    """
    __tablename__ = "decision_memory_layered"
    __table_args__ = (UniqueConstraint("symbol", "layer", name="uq_decision_memory_layered"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # NULL for long
    layer: Mapped[str] = mapped_column(String, nullable=False, index=True)   # 'medium' / 'long'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class StockMemoryItem(Base):
    """Structured long-term memory for stock research and decision experience."""
    __tablename__ = "stock_memory_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MemoryAtom(Base):
    """
    L0 Memory / Knowledge Base — one minimal memory unit.

    Inspired by TencentDB-Agent-Memory's local layered design, but kept as a
    明仓 / MingCang-owned SQLite contract.  LLM/tool paths may create raw/pending
    atoms; trusted/refuted states are reserved for explicit human/review gates.
    """
    __tablename__ = "memory_atoms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)
    scope_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    trust_state: Mapped[str] = mapped_column(String, default="raw", index=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    valid_from: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String, nullable=True)
    ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stock_memory_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promoted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    refuted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    refutation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MemoryScenario(Base):
    """L0 scenario rollup: a compact cluster of related memory atoms."""
    __tablename__ = "memory_scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)
    scope_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    atom_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_state: Mapped[str] = mapped_column(String, default="pending", index=True)
    source_type: Mapped[str] = mapped_column(String, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MemoryProfile(Base):
    """L0 profile rollup for user rules, methodology, and project preferences."""
    __tablename__ = "memory_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_type: Mapped[str] = mapped_column(String, index=True)
    profile_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    atom_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_state: Mapped[str] = mapped_column(String, default="pending", index=True)
    source_type: Mapped[str] = mapped_column(String, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MemoryPromotionCandidate(Base):
    """
    M37 Review Loop — pending/trusted/rejected memory promotion candidates.

    State machine: pending -> trusted (via promote_memory, explicit human-confirmed call)
                   pending -> rejected (via reject_memory_candidate, explicit human-confirmed call)
    Both 'trusted' and 'rejected' are terminal — no further transitions.

    source_trust is always created as 'pending'. The only functions that write
    'trusted' or 'rejected' are promote_memory and reject_memory_candidate
    respectively, neither of which is callable from any LLM agent code path.
    """
    __tablename__ = "memory_promotion_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True)         # bare int ref to review_cases.id
    memory_atom_id: Mapped[int | None] = mapped_column(Integer, nullable=True)         # set after L0 promotion/rejection
    stock_memory_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # set after promotion fires the stock_memory write
    symbol: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String)
    source_trust: Mapped[str] = mapped_column(String, default="pending", index=True)   # pending / trusted / rejected
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)              # part of the explicit idempotency key
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # set when trusted
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # set when rejected
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
