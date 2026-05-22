from datetime import datetime

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
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


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
    market: Mapped[str] = mapped_column(String)                      # "CN" or "US"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)     # 申万一级行业（由 sync_industry 回填）
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IndexPrice(Base):
    """大盘指数日线（用于宏观相对强弱对比）"""
    __tablename__ = "index_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)    # e.g. "sh000300"（沪深300）
    date: Mapped[str] = mapped_column(String, index=True)      # "2024-01-15"
    close: Mapped[float] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    last_signal_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PendingAIAction(Base):
    """AI 对话生成、等待用户确认的项目内操作。"""
    __tablename__ = "pending_ai_actions"
    action_id: Mapped[str] = mapped_column(String, primary_key=True)
    action: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending / executed / cancelled / failed
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    """Messages stored per chat window."""
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def get_latest_price_date(symbol: str, db) -> str | None:
    """返回该股最新一条价格记录的日期字符串，无数据时返回 None"""
    result = db.query(Price.date).filter(Price.symbol == symbol)\
               .order_by(Price.date.desc()).first()
    return result[0] if result else None


def _ensure_runtime_schema() -> None:
    """SQLite create_all 不会补既有表字段，这里做轻量幂等迁移。"""
    with engine.begin() as conn:
        signal_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(signals)")).fetchall()]
        if "rule_version" not in signal_cols:
            conn.execute(text("ALTER TABLE signals ADD COLUMN rule_version TEXT"))
        if "data_timestamp" not in signal_cols:
            conn.execute(text("ALTER TABLE signals ADD COLUMN data_timestamp TEXT"))

        position_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(positions)")).fetchall()]
        for col, ddl in {
            "closed_at": "ALTER TABLE positions ADD COLUMN closed_at TEXT",
            "close_price": "ALTER TABLE positions ADD COLUMN close_price REAL",
            "realized_pnl": "ALTER TABLE positions ADD COLUMN realized_pnl REAL",
            "realized_pnl_pct": "ALTER TABLE positions ADD COLUMN realized_pnl_pct REAL",
        }.items():
            if col not in position_cols:
                conn.execute(text(ddl))

        fm_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(financial_metrics)")).fetchall()]
        if "disclosure_date" not in fm_cols:
            conn.execute(text("ALTER TABLE financial_metrics ADD COLUMN disclosure_date TEXT"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT,
                scope TEXT DEFAULT 'global',
                ttl_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(key, scope)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_memory_scope_cat
            ON ai_memory(scope, category)
        """))
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS audit_log_fts USING fts5(
                timestamp, event_type, content, related_symbol, related_scope
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                memory_type TEXT,
                summary TEXT NOT NULL,
                evidence_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                importance INTEGER DEFAULT 3,
                confidence REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                ttl_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                last_used_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_stock_memory_symbol_type
            ON stock_memory_items(symbol, memory_type)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_stock_memory_status_updated
            ON stock_memory_items(status, updated_at)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS decision_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                run_type TEXT,
                symbol TEXT,
                as_of TEXT,
                profile TEXT,
                rule_version TEXT,
                recommendation TEXT,
                composite_score REAL,
                input_snapshot_json TEXT,
                agent_outputs_json TEXT,
                risk_decision_json TEXT,
                final_action_json TEXT,
                eval_result_json TEXT,
                notes TEXT,
                created_at DATETIME,
                UNIQUE(run_id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_decision_runs_symbol_as_of
            ON decision_runs(symbol, as_of)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS research_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE,
                thesis TEXT,
                risks_json TEXT,
                open_questions_json TEXT,
                last_signal_summary TEXT,
                last_review_json TEXT,
                updated_at DATETIME,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                date TEXT,
                market_cap REAL,
                float_market_cap REAL,
                shares_outstanding REAL,
                north_net_buy REAL,
                margin_balance REAL,
                large_order_net_inflow REAL,
                source TEXT,
                fetched_at DATETIME,
                UNIQUE(symbol, date)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_date
            ON market_snapshots(symbol, date)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                name TEXT,
                market TEXT DEFAULT 'CN',
                quantity REAL,
                avg_cost REAL,
                opened_at TEXT,
                stop_loss REAL,
                take_profit REAL,
                closed_at TEXT,
                close_price REAL,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                note TEXT,
                status TEXT DEFAULT 'open',
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_positions_symbol_status
            ON positions(symbol, status)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS review_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                as_of TEXT,
                summary TEXT,
                path TEXT,
                status TEXT DEFAULT 'created',
                payload_json TEXT,
                created_at DATETIME,
                UNIQUE(kind, as_of)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_review_runs_kind_as_of
            ON review_runs(kind, as_of)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_ai_actions (
                action_id TEXT PRIMARY KEY,
                action TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                result_json TEXT,
                user_message TEXT,
                created_at DATETIME,
                executed_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                mode TEXT DEFAULT 'general',
                archived_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        chat_session_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(chat_sessions)")).fetchall()]
        if "archived_at" not in chat_session_cols:
            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN archived_at DATETIME"))
        if "summary" not in chat_session_cols:
            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN summary TEXT"))
        if "summary_until_id" not in chat_session_cols:
            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN summary_until_id INTEGER"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                payload_json TEXT,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
            ON chat_messages(session_id, created_at)
        """))


def init_db() -> None:
    """Create all ORM tables and apply runtime schema patches."""
    Base.metadata.create_all(engine)
    _ensure_runtime_schema()
    _seed_default_memory()


def _seed_default_memory() -> None:
    """M9.0/M9.1：种子默认 bias-override + 一次性迁移分层记忆文件入 DB。"""
    from backend.decision.memory_layered import migrate_layered_files_to_db
    from backend.memory.bias_override import seed_default_overrides
    db = SessionLocal()
    try:
        seed_default_overrides(db)
        migrate_layered_files_to_db(db)
    finally:
        db.close()


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
