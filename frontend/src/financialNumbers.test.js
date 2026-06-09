import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatAdjustment,
  formatDate,
  formatMoney,
  formatPositionPercent,
  formatPositionSize,
  formatPrice,
  formatPriceWithAdjustment,
  formatSignedMoney,
  formatSignedNumber,
  formatSignedPercent,
} from './financialNumbers.js'

test('formats prices, money, and position size without losing units', () => {
  assert.equal(formatPrice(12.345), '12.35')
  assert.equal(formatPrice('8'), '8.00')
  assert.equal(formatMoney(1234567.891), '1,234,567.89')
  assert.equal(formatPositionSize(1200.12345), '1,200.1235')
})

test('formats signed PnL and percentages consistently', () => {
  assert.equal(formatSignedMoney(1250), '+1,250')
  assert.equal(formatSignedMoney(-1250.5), '-1,250.5')
  assert.equal(formatSignedNumber(12.345, 1), '+12.3')
  assert.equal(formatSignedNumber(-0.04, 1), '0.0')
  assert.equal(formatSignedPercent(3.456), '+3.46%')
  assert.equal(formatSignedPercent(-1.234), '-1.23%')
  assert.equal(formatSignedPercent(-0.004), '0.00%')
  assert.equal(formatPositionPercent(0.1123), '11.2%')
})

test('normalizes date-like values and preserves empty/null safety', () => {
  assert.equal(formatDate('2026-06-08T22:11+08:00'), '2026-06-08')
  assert.equal(formatDate('2026-06-08 14:22:13.658596'), '2026-06-08')
  assert.equal(formatDate(null), '-')
  assert.equal(formatPrice(null), '-')
  assert.equal(formatSignedMoney(undefined), '-')
})

test('labels qfq/hfq adjustment state explicitly', () => {
  assert.equal(formatAdjustment('qfq'), '前复权(qfq)')
  assert.equal(formatAdjustment('hfq'), '后复权(hfq)')
  assert.equal(formatAdjustment(null), '未标注')
  assert.equal(formatPriceWithAdjustment(10, 'qfq'), '10.00 前复权(qfq)')
})
