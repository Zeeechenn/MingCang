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


Market = Literal["CN", "HK", "US"]
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


class QualityGateOut(BaseModel):
    checks: dict[str, bool] = {}
    blockers: list[str] = []
    warnings: list[dict] = []
    gate_pass: bool = False
    as_of: str | None = None
    generated_at: str | None = None


class StructuralValidityCardOut(BaseModel):
    status: dict = {}
    missing_provenance: list[str] = []
    card_pass: bool = False
    generated_at: str | None = None


class ResearchCaseOut(BaseModel):
    symbol: str
    as_of: str | None = None
    quality_gate: QualityGateOut = Field(default_factory=QualityGateOut)
    validity_card: StructuralValidityCardOut = Field(default_factory=StructuralValidityCardOut)
    ready: bool = False
    generated_at: str | None = None


class EvidenceCardOut(BaseModel):
    kind: str
    source_layer: str = "L1"
    source_type: str | None = None
    source_ref: str | None = None
    summary: str = ""
    as_of: str | None = None
    pit_ok: bool = False
    provenance: dict = {}
    write_policy: str = "no_database_writes"
    signal_impact: str = "none"


class MemoryCandidatePreviewOut(BaseModel):
    symbol: str
    summary: str
    memory_type: str
    importance: int = 3
    confidence: float = 0.5
    source_ref: str | None = None
    note: str | None = None
    eligible_for_creation: bool = False
    source_trust_after_create: str = "pending"


class DossierAdapterReviewOut(BaseModel):
    adapter: str
    symbol: str
    as_of: str | None = None
    read_only: bool = True
    research_case: ResearchCaseOut
    evidence_cards: list[EvidenceCardOut] = []
    memory_candidate_preview: MemoryCandidatePreviewOut
    promotion_gate: dict = {}


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
    case: ResearchCaseOut | None = None


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


class StressTestResponse(BaseModel):
    symbol: str
    as_of: str | None = None
    used_llm: bool = False
    llm_valid: bool = False
    overall_severity: str = "low"
    blockers: list[str] = Field(default_factory=list)
    decision_deltas: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    confidence_adjustments: dict = {}
    role_outputs: dict = {}
    fallback_reason: str | None = None
    generated_at: str = ""
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


# ── M40 Thesis Ledger schemas ─────────────────────────────────────────────────

class ThesisOut(BaseModel):
    id: int
    symbol: str
    title: str
    status: str = "active"
    kill_conditions: list[str] = []
    update_cadence_days: int | None = None
    research_case_as_of: str | None = None
    review_case_ref: dict | None = None
    confidence_history: list[dict] = []
    review_cases: list[dict] = []
    created_at: str | None = None
    updated_at: str | None = None


class ThesisListOut(BaseModel):
    symbol: str | None = None
    items: list[ThesisOut] = []
    total: int = 0


class ThesisCreateRequest(BaseModel):
    symbol: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kill_conditions: list[str] = []
    update_cadence_days: int | None = None
    research_case_as_of: str | None = None
    status: str = "active"


class ThesisStatusRequest(BaseModel):
    new_status: str = Field(min_length=1)
    note: str | None = None


class ThesisConfidenceRequest(BaseModel):
    score: float
    as_of: str
    note: str | None = None


class ThesisConfidenceOut(BaseModel):
    id: int
    thesis_id: int
    score: float
    as_of: str
    note: str | None = None
    created_at: str | None = None


class ThesisAttachReviewRequest(BaseModel):
    review_payload: dict = {}
    as_of: str


# ── M40 Theme Hypothesis Engine schemas ───────────────────────────────────────

class ThemeOut(BaseModel):
    id: int
    theme_name: str
    description: str | None = None
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None


class ThemeListOut(BaseModel):
    items: list[ThemeOut] = []
    total: int = 0


class ThemeCreateRequest(BaseModel):
    theme_name: str = Field(min_length=1)
    description: str | None = None
    status: str = "active"


class HypothesisOut(BaseModel):
    id: int
    theme_id: int
    statement: str
    status: str = "proposed"
    beneficiary_tiers: list[dict] = []
    evidence_gaps: list[str] = []
    invalidation_conditions: list[str] = []
    ai_supply_chain: dict | None = None
    forward_evidence: list[dict] = []
    forward_evidence_ref: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


class HypothesisListOut(BaseModel):
    theme_id: int | None = None
    items: list[HypothesisOut] = []
    total: int = 0


class HypothesisCreateRequest(BaseModel):
    statement: str = Field(min_length=1)
    beneficiary_tiers: list | None = None
    evidence_gaps: list | None = None
    invalidation_conditions: list | None = None
    template: str | None = None
    template_payload: dict | None = None
    status: str = "proposed"


class HypothesisStatusRequest(BaseModel):
    new_status: str = Field(min_length=1)
    note: str | None = None


class BeneficiaryTiersRequest(BaseModel):
    # NOTE: tiers are advisory display metadata ONLY — must NOT feed
    # aggregate/aggregate_v2/run_pipeline/apply_research_constraints
    tiers: list[dict] = []


class ForwardEvidenceRequest(BaseModel):
    evidence_payload: dict = {}
    as_of: str


# ── M40 Review Loop schemas ───────────────────────────────────────────────────

class ReviewCaseOut(BaseModel):
    id: int
    symbol: str
    as_of: str
    signal_id: int | None = None
    thesis_id: int | None = None
    research_case_as_of: str | None = None
    review_payload: dict | None = None
    created_at: str | None = None


class ReviewCaseListOut(BaseModel):
    symbol: str | None = None
    items: list[ReviewCaseOut] = []
    total: int = 0


class ReviewCaseCreateRequest(BaseModel):
    symbol: str = Field(min_length=1)
    as_of: str
    signal_id: int | None = None
    thesis_id: int | None = None
    research_case_as_of: str | None = None
    review_payload: dict | None = None


class MemoryCandidateOut(BaseModel):
    # source_trust is read-only in response; not accepted in any request schema
    id: int
    symbol: str
    summary: str
    memory_type: str
    importance: int = 3
    confidence: float = 0.5
    source_trust: str = "pending"
    source_ref: str | None = None
    note: str | None = None
    review_case_id: int | None = None
    memory_atom_id: int | None = None
    stock_memory_item_id: int | None = None
    promoted_at: str | None = None
    rejected_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryCandidateListOut(BaseModel):
    items: list[MemoryCandidateOut] = []
    total: int = 0


class MemoryCandidateCreateRequest(BaseModel):
    # source_trust intentionally omitted — storage layer hardcodes 'pending'
    symbol: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    memory_type: str = Field(min_length=1)
    importance: int = 3
    confidence: float = 0.5
    review_case_id: int | None = None
    source_ref: str | None = None
    note: str | None = None


class MemoryPromoteRequest(BaseModel):
    # HUMAN-GATED: non-empty confirmed_by required — never auto-callable
    confirmed_by: str = Field(min_length=1)


class MemoryRejectRequest(BaseModel):
    confirmed_by: str = Field(min_length=1)
    note: str | None = None


# ── M40 Universe Guard schemas ────────────────────────────────────────────────

class UniverseSnapshotOut(BaseModel):
    id: int | None = None
    symbols: list[str] = []
    cutoff_date: str | None = None
    market_filter: str = "ALL"
    context: str | None = None
    universe_hash: str | None = None
    created_at: str | None = None


class UniverseSnapshotListOut(BaseModel):
    items: list[UniverseSnapshotOut] = []
    total: int = 0


class UniverseSnapshotRequest(BaseModel):
    symbols: list[str]
    cutoff_date: str
    market_filter: str = "ALL"
    context: str | None = None


# ── M40 Forward Thesis schemas ────────────────────────────────────────────────

class ForwardThesisOut(BaseModel):
    id: int
    statement: str
    symbol: str | None = None
    status: str = "draft"
    horizon_date: str | None = None
    thesis_id: int | None = None
    theme_hypothesis_id: int | None = None
    universe_snapshot_id: int | None = None
    confidence_low: float | None = None
    confidence_high: float | None = None
    invalidation_conditions: list = []
    follow_up_metrics: list = []
    evidence_manifest: list = []
    next_review_date: str | None = None
    review_cadence_days: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ForwardThesisListOut(BaseModel):
    symbol: str | None = None
    items: list[ForwardThesisOut] = []
    total: int = 0


class ForwardThesisCreateRequest(BaseModel):
    statement: str = Field(min_length=1)
    symbol: str | None = None
    horizon_date: str | None = None
    thesis_id: int | None = None
    theme_hypothesis_id: int | None = None
    universe_snapshot_id: int | None = None
    confidence_low: float | None = None
    confidence_high: float | None = None
    invalidation_conditions: list | None = None
    follow_up_metrics: list | None = None
    evidence_manifest: list | None = None
    template: str | None = None
    template_payload: dict | None = None
    next_review_date: str | None = None
    review_cadence_days: int | None = None
    status: str = "draft"


class ForwardThesisStatusRequest(BaseModel):
    new_status: str = Field(min_length=1)
    note: str | None = None


class ForwardThesisConfidenceRequest(BaseModel):
    confidence_low: float
    confidence_high: float
    as_of: str


class ForwardThesisEvidenceRequest(BaseModel):
    manifest: list[dict] = []
    as_of: str


# ── M40 Case View schemas ─────────────────────────────────────────────────────

class CaseViewInner(BaseModel):
    theses: list[dict] = []
    review_cases: list[dict] = []
    forward_theses: list[dict] = []
    theme_hypotheses: list[dict] = []
    generated_at: str | None = None


class CaseViewOut(BaseModel):
    symbol: str
    dossier: ResearchDossierOut
    case_view: CaseViewInner
