function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null
  return `${(Number(value) * 100).toFixed(1)}%`
}

export function getPortfolioActionSummary(finalAction = {}) {
  const portfolioDecision = finalAction.portfolio_decision || {}
  return {
    finalPosition: fmtPct(finalAction.position_pct) || '-',
    traderPosition: fmtPct(finalAction.trader_position_pct),
    rationale: finalAction.allocation_rationale || portfolioDecision.rationale || null,
    action: portfolioDecision.action || null,
  }
}
