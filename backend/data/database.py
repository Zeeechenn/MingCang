from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.config import BASE_DIR, settings


def _utcnow() -> datetime:
    """Return current UTC time as timezone-naive datetime (SQLite compatible).

    M21.4: 替代已弃用的 datetime.utcnow()，保持存储格式不变（naive UTC）。
    """
    return datetime.now(UTC).replace(tzinfo=None)


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
_DEFAULT_DB_PATH = (BASE_DIR / "stock-sage.db").resolve()


@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_conn, _) -> None:
    """开启 WAL 模式，避免 APScheduler + FastAPI 并发写锁冲突"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Base(DeclarativeBase):
    pass


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


class ChatSession(Base):
    """Project AI chat window; memory is scoped to this session only."""
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String, default="general")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # M9.3 window summarizer output
    summary_until_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # last compressed msg id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ChatMessage(Base):
    """Messages stored per chat window."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class LlmUsageLog(Base):
    """Per-call LLM token usage log for cost observability."""
    __tablename__ = "llm_usage_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String, index=True)  # sentiment/copilot/debate/chat/deep_research
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate_cny: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class ThesisRecord(Base):
    """
    M35 Thesis Ledger — one row per investment thesis.

    Status state machine:
      active <-> watch; active/watch -> broken/retired; broken -> retired.
      retired is terminal.
    """
    __tablename__ = "thesis_records"
    __table_args__ = (UniqueConstraint("symbol", "title", name="uq_thesis_records_symbol_title"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")  # active / watch / broken / retired
    kill_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON array of strings
    update_cadence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_case_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    research_case_as_of: Mapped[str | None] = mapped_column(String, nullable=True)  # ISO date string
    review_case_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # populated by M37
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ThesisConfidenceEntry(Base):
    """
    M35 Thesis Ledger — append-only confidence history per thesis.

    Never updated; a new row is inserted on each confidence reading.
    """
    __tablename__ = "thesis_confidence_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thesis_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float)          # clamped [0.0, 1.0]
    as_of: Mapped[str] = mapped_column(String)           # ISO date string
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


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
    forward_evidence_ref_json: Mapped[str | None] = mapped_column(Text, nullable=True) # populated by M39 when M29 promotion gate passes
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ReviewCase(Base):
    """
    M37 Review / Calibration / Memory Loop — one row per signal-review event.

    Links a signal (by id), an optional thesis (by id), and an optional
    ResearchCase (by symbol+as_of) into a single review record.  Outcome
    attribution data is stored verbatim from review_latest_signal().
    position_case_ref_json is a nullable stub for a future PositionCase milestone.

    No ForeignKey() constraints — plain integer references following M35 style.
    UniqueConstraint on (symbol, as_of) makes create_review_case idempotent.
    """
    __tablename__ = "review_cases"
    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_review_cases_symbol_as_of"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[str] = mapped_column(String, index=True)            # ISO date — the signal/review date
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # bare int, no FK constraint
    thesis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)          # bare int, links to ThesisRecord.id
    research_case_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    research_case_as_of: Mapped[str | None] = mapped_column(String, nullable=True)
    position_case_ref_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="populated when PositionCase is built (future milestone)",
    )
    outcome_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)   # True/False/None from review
    next_day_return: Mapped[float | None] = mapped_column(Float, nullable=True)    # percent, 2dp
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String, nullable=True)      # BUY/HOLD/SELL
    attribution_json: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON list of Chinese attribution strings
    review_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # full JSON blob from review_latest_signal
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
    stock_memory_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # set after promotion fires the stock_memory write
    symbol: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String)
    source_trust: Mapped[str] = mapped_column(String, default="pending", index=True)   # pending / trusted / rejected
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)              # idempotency key
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # set when trusted
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # set when rejected
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


def get_latest_price_date(symbol: str, db) -> str | None:
    """返回该股最新一条价格记录的日期字符串，无数据时返回 None"""
    result = db.query(Price.date).filter(Price.symbol == symbol)\
               .order_by(Price.date.desc()).first()
    return result[0] if result else None


def _ensure_runtime_schema() -> None:
    """Compatibility wrapper for runtime schema patches."""
    from backend.data.schema_runtime import _ensure_runtime_schema as ensure_runtime_schema

    ensure_runtime_schema()


def _verify_schema_consistency() -> list[str]:
    """
    M21.4 schema 单一化：检查 ORM 模型列与 PRAGMA table_info 的差异，
    以日志警告形式暴露"meta vs PRAGMA diff"问题，不阻断启动。

    返回所有差异描述列表（空列表表示一致）。
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    diffs: list[str] = []
    try:
        from sqlalchemy import inspect as _inspect
        inspector = _inspect(engine)
        for mapper in Base.registry.mappers:
            table = cast(Any, mapper.local_table)
            table_name = table.name
            try:
                pragma_cols = {r["name"] for r in inspector.get_columns(table_name)}
            except Exception:
                continue
            orm_cols = {c.name for c in table.columns}
            extra_in_pragma = pragma_cols - orm_cols
            missing_in_pragma = orm_cols - pragma_cols
            if extra_in_pragma:
                msg = f"[schema] {table_name}: PRAGMA 有但 ORM 无 → {extra_in_pragma}"
                _log.debug(msg)
                diffs.append(msg)
            if missing_in_pragma:
                msg = f"[schema] {table_name}: ORM 有但 PRAGMA 无 → {missing_in_pragma}"
                _log.warning(msg)
                diffs.append(msg)
    except Exception as e:
        diffs.append(f"[schema] consistency check 失败: {e}")
    return diffs


def init_db() -> None:
    """Create all ORM tables and apply runtime schema patches."""
    Base.metadata.create_all(engine)
    _ensure_runtime_schema()
    _verify_schema_consistency()
    _seed_default_memory()


def _seed_default_memory() -> None:
    """Compatibility wrapper for default seed routines."""
    from backend.data.seed import _seed_default_memory as seed_default_memory

    seed_default_memory()


def _should_migrate_local_memory() -> bool:
    """Compatibility wrapper for seed migration gating."""
    from backend.data.seed import _should_migrate_local_memory as should_migrate_local_memory

    return should_migrate_local_memory()


def get_db():
    """FastAPI dependency: yield a DB session and close it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
