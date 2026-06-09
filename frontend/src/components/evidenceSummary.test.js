import assert from 'node:assert/strict'
import test from 'node:test'

import { getDataTrustSummary, getPortfolioActionSummary } from './evidenceSummary.js'

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

test('getDataTrustSummary exposes warnings, freshness, and provider chain', () => {
  const summary = getDataTrustSummary({
    summary: { active_stocks: 1, latest_price_date: '2026-06-03' },
    checks: { price_coverage_ok: true, financial_coverage_ok: false },
    warnings: [{ code: 'financial_coverage_gap' }],
    freshness_contract: {
      daily_price: { intraday_policy: 'read_L1_L2_only' },
    },
    provider_fallback_chains: {
      chains_by_market: {
        CN: {
          daily: [{ name: 'akshare_sina_cn' }, { name: 'eastmoney_cn' }],
        },
      },
    },
    stocks: [
      {
        symbol: '300308',
        market: 'CN',
        latest_price_date: '2026-06-02',
        price_rows: 520,
      },
    ],
  }, '300308')

  assert.equal(summary.status, 'warning')
  assert.equal(summary.label, '需复核')
  assert.equal(summary.warningCount, 1)
  assert.deepEqual(summary.warningCodes, ['financial_coverage_gap'])
  assert.equal(summary.latestPriceDate, '2026-06-02')
  assert.deepEqual(summary.providerChain, ['akshare_sina_cn', 'eastmoney_cn'])
  assert.equal(summary.freshnessPolicy, 'read_L1_L2_only')
})

test('getDataTrustSummary passes clean coverage without a selected stock', () => {
  const summary = getDataTrustSummary({
    summary: { latest_price_date: '2026-06-03' },
    checks: { price_coverage_ok: true },
    warnings: [],
  })

  assert.equal(summary.status, 'pass')
  assert.equal(summary.label, '通过')
  assert.equal(summary.warningCount, 0)
  assert.equal(summary.latestPriceDate, '2026-06-03')
})
