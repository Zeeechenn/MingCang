function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null
  return `${(Number(value) * 100).toFixed(1)}%`
}

export function getPortfolioActionSummary(finalAction = {}) {
  const portfolioDecision = finalAction.portfolio_decision || {}
  return {
    finalPosition: fmtPct(finalAction.position_pct) || '-',
    traderPosition: fmtPct(finalAction.trader_position_pct),
    riskPosition: fmtPct(finalAction.risk_position_pct),
    rationale: finalAction.allocation_rationale || portfolioDecision.rationale || null,
    action: portfolioDecision.action || null,
  }
}

function dataTrustStatus(coverage = {}) {
  const warnings = Array.isArray(coverage.warnings) ? coverage.warnings : []
  const checks = coverage.checks || {}
  const hasFailedCheck = Object.values(checks).some((value) => value === false)
  if (warnings.length > 0 || hasFailedCheck) return 'warning'
  return 'pass'
}

function dailyProviderNames(coverage = {}, market = 'CN') {
  const chains = coverage.provider_fallback_chains?.chains_by_market
    || coverage.summary?.provider_fallback_chains?.chains_by_market
    || {}
  const daily = chains?.[market]?.daily || []
  return daily
    .map((provider) => provider?.name)
    .filter(Boolean)
}

export function getDataTrustSummary(coverage = {}, symbol = null) {
  const stocks = Array.isArray(coverage.stocks) ? coverage.stocks : []
  const stock = symbol ? stocks.find((row) => row.symbol === symbol) || null : null
  const warnings = Array.isArray(coverage.warnings) ? coverage.warnings : []
  const status = dataTrustStatus(coverage)
  const market = stock?.market || 'CN'
  const dailyFreshness = coverage.freshness_contract?.daily_price
    || coverage.summary?.freshness_contract?.daily_price
    || {}

  return {
    status,
    label: status === 'pass' ? '通过' : '需复核',
    toneClass: status === 'pass' ? 'text-emerald-300' : 'text-amber-300',
    warningCount: warnings.length,
    warningCodes: warnings.map((item) => item.code).filter(Boolean),
    latestPriceDate: stock?.latest_price_date || coverage.summary?.latest_price_date || null,
    providerChain: dailyProviderNames(coverage, market),
    freshnessPolicy: dailyFreshness.intraday_policy || dailyFreshness.policy || null,
    stock,
  }
}
