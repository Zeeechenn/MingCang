"""Pydantic response schemas"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class StockOut(BaseModel):
    symbol: str
    name: str
    market: str

    model_config = {"from_attributes": True}


class LLMArbitration(BaseModel):
    bull_points: list[str] = []
    bear_points: list[str] = []
    action_bias: str = "中性"
    rationale: str = ""


class SignalOut(BaseModel):
    id: int
    symbol: str
    date: str
    composite_score: float
    recommendation: str
    confidence: str
    stop_loss: float | None = None
    take_profit: float | None = None
    limit_status: str | None = None
    quant_score: float | None = None
    technical_score: float | None = None
    sentiment_score: float | None = None
    llm_arbitration: LLMArbitration | None = None

    model_config = {"from_attributes": True}

    @field_validator("llm_arbitration", mode="before")
    @classmethod
    def parse_llm_rationale(cls, v) -> dict | None:
        """llm_rationale 字段存的是 JSON 字符串，自动反序列化"""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {"rationale": v, "bull_points": [], "bear_points": [], "action_bias": "中性"}
        return None


class LongTermLabelOut(BaseModel):
    symbol: str
    date: str
    label: str                           # 值得持有/估值偏高/观望/规避
    score: float
    votes: dict[str, str] = {}           # {role: vote}
    key_findings: list[str] = []
    expires_at: str
    quality: Literal["trusted", "degraded", "failed"] = "degraded"
    constraint_eligible: bool = False
    quality_notes: list[str] = []


class WatchlistItem(BaseModel):
    symbol: str
    name: str
    market: str
    industry: str | None = None
    latest_signal: SignalOut | None = None
    long_term_label: LongTermLabelOut | None = None


Market = Literal["CN", "US"]
PositionStatus = Literal["open", "closed"]


class PositionCreate(BaseModel):
    symbol: str = Field(min_length=1)
    name: str | None = None
    market: Market = "CN"
    quantity: float = Field(gt=0)
    avg_cost: float = Field(gt=0)
    opened_at: str | None = None
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    note: str | None = None


class PositionUpdate(BaseModel):
    name: str | None = None
    market: Market | None = None
    quantity: float | None = Field(default=None, gt=0)
    avg_cost: float | None = Field(default=None, gt=0)
    opened_at: str | None = None
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    closed_at: str | None = None
    close_price: float | None = Field(default=None, gt=0)
    note: str | None = None
    status: PositionStatus | None = None


class PositionOut(BaseModel):
    id: int
    symbol: str
    name: str
    market: str
    quantity: float
    avg_cost: float
    opened_at: str
    stop_loss: float | None = None
    take_profit: float | None = None
    closed_at: str | None = None
    close_price: float | None = None
    realized_pnl: float | None = None
    realized_pnl_pct: float | None = None
    note: str | None = None
    status: str
    latest_price: float | None = None
    latest_price_date: str | None = None
    market_value: float | None = None
    cost_value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None


class PriceBar(BaseModel):
    time: str      # "YYYY-MM-DD"，TradingView Lightweight Charts 格式
    open: float
    high: float
    low: float
    close: float
    volume: float


class SignalEvalRecord(BaseModel):
    date: str
    recommendation: str
    composite_score: float
    next_day_return: float | None = None   # 次日收益率 %
    correct: bool | None = None            # 方向是否正确


class SignalEvalOut(BaseModel):
    symbol: str
    days: int
    total_signals: int
    evaluated: int           # 有后续价格数据的信号数
    win_rate: float | None = None          # 方向正确率 %
    avg_return: float | None = None        # 平均次日收益 %
    avg_return_on_buy: float | None = None # 买入信号的平均次日收益 %
    avg_return_on_neutral: float | None = None
    avg_return_on_sell: float | None = None
    records: list[SignalEvalRecord] = []


class NewsOut(BaseModel):
    id: int
    title: str
    url: str
    published_at: str
    source: str
    sentiment_score: float | None = None

    model_config = {"from_attributes": True}


class DecisionRunOut(BaseModel):
    run_id: str
    run_type: str
    symbol: str | None = None
    as_of: str | None = None
    profile: str | None = None
    rule_version: str | None = None
    recommendation: str | None = None
    composite_score: float | None = None
    input_snapshot: dict = {}
    agent_outputs: dict = {}
    trace: list[dict] = []
    risk_decision: dict = {}
    final_action: dict = {}
    eval_result: dict | None = None
    notes: str | None = None
    created_at: str | None = None


class ResearchStateOut(BaseModel):
    symbol: str
    thesis: str = ""
    risks: list[str] = []
    open_questions: list[str] = []
    copilot: dict | None = None
    last_signal_summary: str = ""
    last_review: dict | None = None
    updated_at: str | None = None


class ResearchDossierOut(BaseModel):
    symbol: str
    stock: dict | None = None
    latest_signal: SignalOut | None = None
    long_term_label: LongTermLabelOut | None = None
    research_state: ResearchStateOut
    evidence: list[DecisionRunOut] = []
    stock_memory: list[dict] = []
    deep_research: list[dict] = []
    pending_questions: list[str] = []
    conflicts: list[dict] = []
    official_action: dict = {}
    missing: list[str] = []


class DataCoverageStockOut(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    industry: str | None = None
    price_rows: int = 0
    first_price_date: str | None = None
    latest_price_date: str | None = None
    latest_financial_report: str | None = None
    news_24h_count: int = 0


class DataCoverageOut(BaseModel):
    summary: dict = {}
    provider_health: dict = {}
    freshness_contract: dict = {}
    intraday_zero_network_policy: dict = {}
    provider_fallback_chains: dict = {}
    cache_policy: dict = {}
    stocks: list[DataCoverageStockOut] = []


class DeepResearchRequest(BaseModel):
    topic: str
    symbols: list[str] = []
    as_of: str | None = None
    seed_queries: list[str] = []


class DeepResearchResponse(BaseModel):
    topic: str
    symbols: list[str] = []
    as_of: str
    summary: str
    report_path: str | None = None
    source_count: int = 0
    risk_flags: list[str] = []
    readiness: dict = {}


class AIChatRequest(BaseModel):
    message: str
    mode: str = "general"  # general / long_term_team
    history: list[dict] = []
    session_id: str | None = None


class AIChatResponse(BaseModel):
    answer: str
    citations: list[str] = []
    used_resources: list[str] = []
    pending_action: dict | None = None
