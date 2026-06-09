export type Market = 'CN' | 'HK' | 'US'

export interface LLMArbitration {
  bull_points: string[]
  bear_points: string[]
  action_bias: string
  rationale: string
}

export interface SignalOut {
  id: number
  symbol: string
  date: string
  composite_score: number
  recommendation: string
  confidence: string
  stop_loss: number | null
  take_profit: number | null
  limit_status: string | null
  quant_score: number | null
  technical_score: number | null
  sentiment_score: number | null
  llm_arbitration: LLMArbitration | null
}

export interface PositionOut {
  id: number
  symbol: string
  name: string
  market: string
  quantity: number
  avg_cost: number
  opened_at: string
  stop_loss: number | null
  take_profit: number | null
  closed_at: string | null
  close_price: number | null
  realized_pnl: number | null
  realized_pnl_pct: number | null
  note: string | null
  status: string
  latest_price: number | null
  latest_price_date: string | null
  market_value: number | null
  cost_value: number | null
  pnl: number | null
  pnl_pct: number | null
}

export interface ReviewRunOut {
  id: number
  kind: string
  as_of: string
  summary: string | null
  path: string | null
  status: string
  payload: Record<string, unknown>
  created_at: string | null
  content?: string
}

export interface DataCoverageStockOut {
  symbol: string
  name: string | null
  market: string | null
  industry: string | null
  price_rows: number
  first_price_date: string | null
  latest_price_date: string | null
  latest_financial_report: string | null
  news_24h_count: number
}

export interface DataCoverageWarning {
  code?: string
  message?: string
  [key: string]: unknown
}

export interface DataCoverageOut {
  generated_at: string | null
  summary: Record<string, unknown>
  checks: Record<string, boolean>
  warnings: DataCoverageWarning[]
  provider_health: Record<string, unknown>
  freshness_contract: Record<string, unknown>
  intraday_zero_network_policy: Record<string, unknown>
  provider_fallback_chains: Record<string, unknown>
  market_capability_catalog: Record<string, unknown>
  cache_policy: Record<string, unknown>
  stocks: DataCoverageStockOut[]
}

export interface DecisionRunOut {
  run_id: string
  run_type: string
  symbol: string | null
  as_of: string | null
  profile: string | null
  rule_version: string | null
  recommendation: string | null
  composite_score: number | null
  input_snapshot: Record<string, unknown>
  agent_outputs: Record<string, unknown>
  trace: Record<string, unknown>[]
  risk_decision: Record<string, unknown>
  final_action: Record<string, unknown>
  eval_result: Record<string, unknown> | null
  notes: string | null
  created_at: string | null
}

export interface ResearchStateOut {
  symbol: string
  thesis: string
  risks: string[]
  open_questions: string[]
  copilot: Record<string, unknown> | null
  last_signal_summary: string
  last_review: Record<string, unknown> | null
  updated_at: string | null
}
