import type { DataCoverageOut, DecisionRunOut, ResearchStateOut } from '../apiTypes'
import { formatDate, formatPrice, formatScore } from '../financialNumbers'
import { getDataTrustSummary, getPortfolioActionSummary } from './evidenceSummary'
import StatusBadge from './ui/StatusBadge'

interface ScoreBreakdown {
  quant?: number | null
  technical?: number | null
  sentiment?: number | null
}

interface AgentOutputs {
  breakdown?: ScoreBreakdown
  llm_arbitration?: {
    rationale?: string | null
  }
}

interface FinalAction {
  stop_loss?: number | null
  take_profit?: number | null
  position_pct?: number | null
  trader_position_pct?: number | null
  risk_position_pct?: number | null
  allocation_rationale?: string | null
  portfolio_decision?: {
    action?: string | null
    rationale?: string | null
  }
}

interface RiskDecision {
  limit_status?: string | null
}

interface LastReview {
  attribution?: string[]
}

interface EvidenceCardProps {
  evidence?: DecisionRunOut[]
  research?: ResearchStateOut | null
  coverage?: DataCoverageOut | null
}

export default function EvidenceCard({
  evidence = [],
  research,
  coverage,
}: EvidenceCardProps) {
  const latest = evidence[0]
  const risk = (latest?.risk_decision || {}) as RiskDecision
  const agents = (latest?.agent_outputs || {}) as AgentOutputs
  const finalAction = (latest?.final_action || {}) as FinalAction
  const portfolioAction = getPortfolioActionSummary(finalAction)
  const dataTrust = getDataTrustSummary(coverage || {}, latest?.symbol)
  const stockCoverage = dataTrust.stock
  const lastReview = research?.last_review as LastReview | null | undefined

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-200">决策证据链</h2>
        <span className="text-xs text-gray-500">{latest ? formatDate(latest.as_of) : '暂无记录'}</span>
      </div>

      {research?.last_signal_summary && (
        <div className="rounded border border-gray-800 bg-gray-950 p-3">
          <div className="text-xs text-gray-500 mb-1">研究状态</div>
          <div className="text-sm text-gray-200">{research.last_signal_summary}</div>
          {Array.isArray(lastReview?.attribution) && lastReview.attribution.length > 0 && (
            <div className="mt-2 text-xs text-gray-400">
              复盘：{lastReview.attribution.join(' / ')}
            </div>
          )}
        </div>
      )}

      {!latest ? (
        <div className="text-sm text-gray-500">还没有 harness 记录，下一次信号生成后会自动沉淀。</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="rounded border border-gray-800 bg-gray-950 p-3">
            <div className="text-xs text-gray-500">规则版本</div>
            <div className="text-sm text-gray-200 mt-1">{latest.rule_version || '-'}</div>
            <div className="text-xs text-gray-500 mt-2">综合分</div>
            <div className="text-lg font-semibold text-blue-300">{formatScore(latest.composite_score)}</div>
          </div>

          <div className="rounded border border-gray-800 bg-gray-950 p-3">
            <div className="text-xs text-gray-500">三路拆解</div>
            <div className="mt-2 space-y-1 text-sm text-gray-300">
              <div>量化：{formatScore(agents.breakdown?.quant)}</div>
              <div>技术：{formatScore(agents.breakdown?.technical)}</div>
              <div>情感：{formatScore(agents.breakdown?.sentiment)}</div>
            </div>
          </div>

          <div className="rounded border border-gray-800 bg-gray-950 p-3">
            <div className="text-xs text-gray-500">风控与动作</div>
            <div className="mt-2 space-y-1 text-sm text-gray-300">
              <div>状态：{risk.limit_status || 'normal'}</div>
              <div>止损：{formatPrice(finalAction.stop_loss)}</div>
              <div>止盈：{formatPrice(finalAction.take_profit)}</div>
              <div>仓位：{portfolioAction.finalPosition}</div>
              {portfolioAction.traderPosition && (
                <div className="text-xs text-gray-500">交易员：{portfolioAction.traderPosition}</div>
              )}
              {portfolioAction.riskPosition && (
                <div className="text-xs text-gray-500">风控后：{portfolioAction.riskPosition}</div>
              )}
              {portfolioAction.rationale && (
                <div className="text-xs text-gray-500">{portfolioAction.rationale}</div>
              )}
            </div>
          </div>
        </div>
      )}

      {agents.llm_arbitration?.rationale && (
        <div className="rounded border border-gray-800 bg-gray-950 p-3 text-sm text-gray-300">
          <div className="text-xs text-gray-500 mb-1">辩论结论</div>
          {agents.llm_arbitration.rationale}
        </div>
      )}

      {coverage?.summary && (
        <div className="rounded border border-gray-800 bg-gray-950 p-3">
          <div className="flex items-center justify-between gap-3 mb-2">
            <div className="text-xs text-gray-500">数据覆盖</div>
            <StatusBadge status={dataTrust.status === 'pass' ? 'pass' : 'warning'}>
              可信度：{dataTrust.label}
            </StatusBadge>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm text-gray-300">
            <div>股票：{String(coverage.summary.active_stocks ?? '-')}</div>
            <div>2年价格：{String(coverage.summary.two_year_price_covered ?? '-')}</div>
            <div>财报：{String(coverage.summary.financial_covered ?? '-')}</div>
            <div>24h新闻：{String(coverage.summary.news_24h_covered ?? '-')}</div>
          </div>
          <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs text-gray-500">
            <div>最新价格日：{formatDate(dataTrust.latestPriceDate)}</div>
            <div>日线链：{dataTrust.providerChain.join(' → ') || '-'}</div>
            <div>警告：{dataTrust.warningCount ? dataTrust.warningCodes.join(' / ') : 'none'}</div>
          </div>
          {dataTrust.freshnessPolicy && (
            <div className="mt-2 text-xs text-gray-500">新鲜度策略：{dataTrust.freshnessPolicy}</div>
          )}
          {stockCoverage && (
            <div className="mt-2 text-xs text-gray-500">
              当前标的：价格 {stockCoverage.price_rows} 行，最新 {formatDate(stockCoverage.latest_price_date)}，财报 {formatDate(stockCoverage.latest_financial_report)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
