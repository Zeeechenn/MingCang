"""Decision/experiment harness, research state, review runs, pending AI actions."""
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


class DecisionRun(Base):
    """
    统一决策/实验 harness 记录。

    用于回放一次信号或实验当时的输入、规则版本、Agent 输出、风控和复盘结果。
    """
    __tablename__ = "decision_runs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_decision_run_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    run_type: Mapped[str] = mapped_column(String, index=True)          # postmarket/backtest/paper_trade/...
    symbol: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    as_of: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    profile: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_outputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_action_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    eval_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ResearchState(Base):
    """
    单股研究状态。

    持久化 thesis、风险、待验证假设和系统复盘摘要，供后续 Agent/前端复用。
    """
    __tablename__ = "research_states"
    __table_args__ = (UniqueConstraint("symbol", name="uq_research_state_symbol"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    copilot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_signal_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ReviewRun(Base):
    """复盘运行记录：daily / long_term。"""
    __tablename__ = "review_runs"
    __table_args__ = (UniqueConstraint("kind", "as_of", name="uq_review_kind_as_of"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="created")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PendingAIAction(Base):
    """AI 对话生成、等待用户确认的项目内操作。"""
    __tablename__ = "pending_ai_actions"
    action_id: Mapped[str] = mapped_column(String, primary_key=True)
    action: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending / executed / cancelled / failed
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
