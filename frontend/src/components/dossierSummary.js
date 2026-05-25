function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

export function getDossierActionView(dossier = {}, signal = {}) {
  const action = dossier.official_action || {}
  const evidenceConstraints = dossier.evidence?.[0]?.agent_outputs?.research_constraints || []
  const conflicts = dossier.conflicts || []
  const deepResearch = dossier.deep_research || []
  return {
    recommendation: action.recommendation || signal.recommendation || '暂无动作',
    finalPosition: fmtPct(action.position_pct),
    traderPosition: fmtPct(action.trader_position_pct),
    constrainedLabel: action.is_constrained ? '已应用研究约束' : '未触发研究约束',
    constraintCount: action.constraint_count ?? evidenceConstraints.length,
    conflictCount: action.conflict_count ?? conflicts.length,
    conflicts,
    constraints: evidenceConstraints,
    deepResearchCount: deepResearch.length,
    firstDeepResearchSummary: deepResearch[0]?.summary || '',
  }
}
