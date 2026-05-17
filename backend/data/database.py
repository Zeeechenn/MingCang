from datetime import datetime
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text, Boolean, UniqueConstraint, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
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
    symbol = Column(String, primary_key=True)   # e.g. "600519" or "AAPL"
    name = Column(String)
    market = Column(String)                      # "CN" or "US"
    active = Column(Boolean, default=True)
    industry = Column(String, nullable=True)     # 申万一级行业（由 sync_industry 回填）
    added_at = Column(DateTime, default=datetime.utcnow)


class Price(Base):
    """日线行情"""
    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_price_symbol_date"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    date = Column(String, index=True)           # "2024-01-15"
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    atr14 = Column(Float, nullable=True)        # 预计算 ATR(14)


class NewsItem(Base):
    """新闻条目"""
    __tablename__ = "news"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True, nullable=True)  # None = 宏观新闻
    title = Column(String)
    url = Column(String, unique=True)
    published_at = Column(DateTime)
    source = Column(String)
    summary = Column(Text, nullable=True)       # LLM 生成摘要
    sentiment_score = Column(Float, nullable=True)  # -1.0 ~ +1.0
    fetched_at = Column(DateTime, default=datetime.utcnow)


class IndexPrice(Base):
    """大盘指数日线（用于宏观相对强弱对比）"""
    __tablename__ = "index_prices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)    # e.g. "sh000300"（沪深300）
    date = Column(String, index=True)      # "2024-01-15"
    close = Column(Float)
    change_pct = Column(Float, nullable=True)


class Signal(Base):
    """信号记录"""
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    date = Column(String, index=True)
    quant_score = Column(Float, nullable=True)      # Qlib 量化得分
    technical_score = Column(Float, nullable=True)  # 技术分析得分
    sentiment_score = Column(Float, nullable=True)  # 新闻情感得分
    composite_score = Column(Float)                 # 综合得分 -100~+100
    recommendation = Column(String)                 # 强买/买/观望/卖/强卖
    confidence = Column(String)                     # 高/中/低
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    limit_status = Column(String, nullable=True)    # normal / limit_up / limit_down
    llm_rationale = Column(Text, nullable=True)     # LLM 综合判断理由
    rule_version = Column(String, nullable=True)     # 决策规则版本
    data_timestamp = Column(String, nullable=True)   # 信号使用的数据日期/时间戳
    created_at = Column(DateTime, default=datetime.utcnow)


class FinancialMetric(Base):
    """
    季度财务指标（长期分析师团数据基础）
    来源：akshare stock_lrb_em / stock_zcfz_em / stock_xjll_em
    """
    __tablename__ = "financial_metrics"
    __table_args__ = (UniqueConstraint("symbol", "report_date", name="uq_fm_symbol_date"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    report_date = Column(String, index=True)        # "2024-09-30"
    disclosure_date = Column(String, index=True, nullable=True)  # 实际披露日，缺失时回退 report_date
    period_type = Column(String, nullable=True)     # "Q1"/"Q2"/"Q3"/"Annual"
    revenue = Column(Float, nullable=True)
    revenue_yoy = Column(Float, nullable=True)      # 营业总收入同比 %
    net_profit = Column(Float, nullable=True)
    net_profit_yoy = Column(Float, nullable=True)   # 净利润同比 %
    total_assets = Column(Float, nullable=True)
    total_equity = Column(Float, nullable=True)
    long_term_debt = Column(Float, nullable=True)
    current_ratio = Column(Float, nullable=True)
    operating_cf = Column(Float, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    gross_margin = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)              # 计算: 净利润 / 净资产
    asset_turnover = Column(Float, nullable=True)   # 计算: 收入 / 总资产
    raw_json = Column(Text, nullable=True)          # 完整原始字段备份
    fetched_at = Column(DateTime, default=datetime.utcnow)


class MarketSnapshot(Base):
    """
    日频市值/股本/资金流快照。

    作为 M6.1 数据底座，字段可由 Tushare/AkShare/yfinance 等来源逐步填充。
    """
    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_ms_symbol_date"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    date = Column(String, index=True)
    market_cap = Column(Float, nullable=True)
    float_market_cap = Column(Float, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    north_net_buy = Column(Float, nullable=True)
    margin_balance = Column(Float, nullable=True)
    large_order_net_inflow = Column(Float, nullable=True)
    source = Column(String, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class LongTermLabel(Base):
    """
    长期分析师团输出标签（周频更新，10 天 TTL）
    label ∈ {值得持有, 估值偏高, 观望, 规避}
    """
    __tablename__ = "long_term_labels"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_ltl_symbol_date"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    date = Column(String, index=True)               # 生成日 "2026-05-17"
    label = Column(String)                          # 值得持有/估值偏高/观望/规避
    score = Column(Float)                           # 团综合分 -100~+100
    votes_json = Column(Text, nullable=True)        # {role: vote} JSON
    key_findings_json = Column(Text, nullable=True) # [str] JSON，≤6 条
    expires_at = Column(String)                     # "2026-05-27"
    created_at = Column(DateTime, default=datetime.utcnow)


class DecisionRun(Base):
    """
    统一决策/实验 harness 记录。

    用于回放一次信号或实验当时的输入、规则版本、Agent 输出、风控和复盘结果。
    """
    __tablename__ = "decision_runs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_decision_run_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, index=True)
    run_type = Column(String, index=True)          # postmarket/backtest/paper_trade/...
    symbol = Column(String, index=True, nullable=True)
    as_of = Column(String, index=True, nullable=True)
    profile = Column(String, nullable=True)
    rule_version = Column(String, nullable=True)
    recommendation = Column(String, nullable=True)
    composite_score = Column(Float, nullable=True)
    input_snapshot_json = Column(Text, nullable=True)
    agent_outputs_json = Column(Text, nullable=True)
    risk_decision_json = Column(Text, nullable=True)
    final_action_json = Column(Text, nullable=True)
    eval_result_json = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ResearchState(Base):
    """
    单股研究状态。

    持久化 thesis、风险、待验证假设和系统复盘摘要，供后续 Agent/前端复用。
    """
    __tablename__ = "research_states"
    __table_args__ = (UniqueConstraint("symbol", name="uq_research_state_symbol"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    thesis = Column(Text, nullable=True)
    risks_json = Column(Text, nullable=True)
    open_questions_json = Column(Text, nullable=True)
    last_signal_summary = Column(Text, nullable=True)
    last_review_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


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


def init_db() -> None:
    """Create all ORM tables and apply runtime schema patches."""
    Base.metadata.create_all(engine)
    _ensure_runtime_schema()


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
