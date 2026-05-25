import assert from 'node:assert/strict'
import test from 'node:test'

import { getPortfolioActionSummary } from './evidenceSummary.js'

test('getPortfolioActionSummary shows final and trader position when clipped', () => {
  const summary = getPortfolioActionSummary({
    position_pct: 0.1,
    trader_position_pct: 0.15,
    risk_position_pct: 0.12,
    allocation_rationale: '受组合约束裁剪',
    portfolio_decision: { action: 'reduce' },
  })

  assert.equal(summary.finalPosition, '10.0%')
  assert.equal(summary.traderPosition, '15.0%')
  assert.equal(summary.riskPosition, '12.0%')
  assert.equal(summary.rationale, '受组合约束裁剪')
  assert.equal(summary.action, 'reduce')
})

test('getPortfolioActionSummary keeps legacy final action compatible', () => {
  const summary = getPortfolioActionSummary({ position_pct: 0.05 })

  assert.equal(summary.finalPosition, '5.0%')
  assert.equal(summary.traderPosition, null)
  assert.equal(summary.riskPosition, null)
  assert.equal(summary.rationale, null)
  assert.equal(summary.action, null)
})
