import assert from 'node:assert/strict'
import test from 'node:test'

import { getCopilotActionLabel, getCopilotCardView } from './copilotSummary.js'

test('getCopilotCardView formats official and shadow positions', () => {
  const view = getCopilotCardView({
    stance: '支持',
    shadow_position_pct: 0.05,
    summary_opinion: '可影子试错',
    official: {
      recommendation: '可关注',
      composite_score: 22,
      technical_score: 18,
      sentiment_score: 30,
      position_pct: 0,
      stop_loss: 10,
      take_profit: 14,
    },
  })

  assert.equal(view.officialPosition, '0.0%')
  assert.equal(view.shadowPosition, '5.0%')
  assert.equal(view.conflictLabel, null)
  assert.equal(view.stanceTone, 'support')
})

test('getCopilotCardView marks risk conflicts as reverse-risk shadow advice', () => {
  const view = getCopilotCardView({
    stance: '谨慎',
    shadow_position_pct: 0.03,
    risk_conflict: true,
    official: {
      recommendation: '观望',
      composite_score: 31,
      position_pct: 0,
    },
  })

  assert.equal(view.conflictLabel, '逆风控影子建议')
  assert.equal(view.conflictTone, 'danger')
})

test('getCopilotActionLabel covers loading, refresh, and retry states', () => {
  assert.equal(getCopilotActionLabel({ loading: true, hasCopilot: false }), '生成中')
  assert.equal(getCopilotActionLabel({ loading: false, hasCopilot: false }), '生成副驾驶')
  assert.equal(getCopilotActionLabel({ loading: false, hasCopilot: true }), '刷新副驾驶')
  assert.equal(getCopilotActionLabel({ loading: false, hasCopilot: true, error: '503' }), '重试副驾驶')
})
