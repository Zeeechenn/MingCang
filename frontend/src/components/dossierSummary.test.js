import assert from 'node:assert/strict'
import test from 'node:test'

import { getDossierActionView } from './dossierSummary.js'

test('getDossierActionView summarizes constrained dossier action', () => {
  const view = getDossierActionView({
    official_action: {
      recommendation: '观望',
      position_pct: 0,
      trader_position_pct: 0.05,
      is_constrained: true,
      constraint_count: 2,
      conflict_count: 1,
    },
    conflicts: [{ type: 'short_long_conflict', severity: 'high', summary: '长期规避' }],
    deep_research: [{ summary: '300308 研究索引：订单兑现' }],
  }, { recommendation: '可小仓试错' })

  assert.equal(view.recommendation, '观望')
  assert.equal(view.finalPosition, '0.0%')
  assert.equal(view.traderPosition, '5.0%')
  assert.equal(view.constrainedLabel, '已应用研究约束')
  assert.equal(view.conflictCount, 1)
  assert.equal(view.deepResearchCount, 1)
})

test('getDossierActionView falls back to signal without dossier action', () => {
  const view = getDossierActionView({}, { recommendation: '可关注' })

  assert.equal(view.recommendation, '可关注')
  assert.equal(view.finalPosition, '-')
  assert.equal(view.constrainedLabel, '未触发研究约束')
})
