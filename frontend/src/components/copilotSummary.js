export function fmtPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

export function fmtScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}`
}

export function getStanceTone(stance) {
  if (stance === '支持') return 'support'
  if (stance === '反对') return 'oppose'
  if (stance === '谨慎') return 'caution'
  return 'neutral'
}

export function getCopilotCardView(copilot = {}) {
  const official = copilot.official || {}
  return {
    stance: copilot.stance || '中性',
    stanceTone: getStanceTone(copilot.stance),
    summary: copilot.summary_opinion || '暂无副驾驶结论',
    officialRecommendation: official.recommendation || '-',
    officialScore: fmtScore(official.composite_score),
    officialTechnical: fmtScore(official.technical_score ?? official.breakdown?.technical),
    officialSentiment: fmtScore(official.sentiment_score ?? official.breakdown?.sentiment),
    officialPosition: fmtPct(official.position_pct),
    officialStopLoss: official.stop_loss ? Number(official.stop_loss).toFixed(2) : '-',
    officialTakeProfit: official.take_profit ? Number(official.take_profit).toFixed(2) : '-',
    shadowPosition: fmtPct(copilot.shadow_position_pct),
    positionNote: copilot.position_note || '',
    risks: copilot.risks || [],
    validationQuestions: copilot.validation_questions || [],
    eventRead: copilot.event_read || '',
    technicalRead: copilot.technical_read || '',
    conflictLabel: copilot.risk_conflict ? '逆风控影子建议' : null,
    conflictTone: copilot.risk_conflict ? 'danger' : null,
  }
}

export function getCopilotActionLabel({ loading = false, hasCopilot = false, error = '' } = {}) {
  if (loading) return '生成中'
  if (error) return '重试副驾驶'
  return hasCopilot ? '刷新副驾驶' : '生成副驾驶'
}
