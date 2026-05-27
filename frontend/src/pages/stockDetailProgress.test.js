import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SECONDARY_SECTIONS,
  createSecondaryLoadingStatus,
  hasSecondaryLoading,
  markStockDetailSection,
} from './stockDetailProgress.js'

test('createSecondaryLoadingStatus starts every secondary section independently loading', () => {
  const status = createSecondaryLoadingStatus()

  assert.deepEqual(Object.keys(status), SECONDARY_SECTIONS)
  assert.equal(hasSecondaryLoading(status), true)
  assert.equal(status.news.loading, true)
  assert.equal(status.news.error, '')
})

test('markStockDetailSection updates one section without touching the rest', () => {
  const status = createSecondaryLoadingStatus()
  const next = markStockDetailSection(status, 'news', { loading: false, error: 'timeout' })

  assert.equal(next.news.loading, false)
  assert.equal(next.news.error, 'timeout')
  assert.equal(next.evidence.loading, true)
  assert.equal(status.news.loading, true)
})

test('hasSecondaryLoading returns false only after every secondary section settles', () => {
  let status = createSecondaryLoadingStatus()
  for (const name of SECONDARY_SECTIONS) {
    status = markStockDetailSection(status, name, { loading: false })
  }

  assert.equal(hasSecondaryLoading(status), false)
})
