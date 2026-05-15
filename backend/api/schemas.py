"""Pydantic response schemas"""
from __future__ import annotations
import json
from pydantic import BaseModel, field_validator
from typing import Optional


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
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    limit_status: Optional[str] = None
    quant_score: Optional[float] = None
    technical_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    llm_arbitration: Optional[LLMArbitration] = None

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


class WatchlistItem(BaseModel):
    symbol: str
    name: str
    market: str
    industry: Optional[str] = None
    latest_signal: Optional[SignalOut] = None
    long_term_label: Optional[LongTermLabelOut] = None


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
    next_day_return: Optional[float] = None   # 次日收益率 %
    correct: Optional[bool] = None            # 方向是否正确


class SignalEvalOut(BaseModel):
    symbol: str
    days: int
    total_signals: int
    evaluated: int           # 有后续价格数据的信号数
    win_rate: Optional[float] = None          # 方向正确率 %
    avg_return: Optional[float] = None        # 平均次日收益 %
    avg_return_on_buy: Optional[float] = None # 买入信号的平均次日收益 %
    avg_return_on_neutral: Optional[float] = None
    avg_return_on_sell: Optional[float] = None
    records: list[SignalEvalRecord] = []


class NewsOut(BaseModel):
    id: int
    title: str
    url: str
    published_at: str
    source: str
    sentiment_score: Optional[float] = None

    model_config = {"from_attributes": True}
