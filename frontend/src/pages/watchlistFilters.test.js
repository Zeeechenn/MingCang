import assert from 'node:assert/strict'
import test from 'node:test'

import { filterWatchlistItems } from './watchlistFilters.js'

const items = [
  { symbol: '300308', name: '中际旭创', industry: '光模块', market: 'CN', latest_signal: { recommendation: '可小仓试错' } },
  { symbol: '603986', name: '兆易创新', industry: '半导体', market: 'CN', latest_signal: { recommendation: '观望' } },
  { symbol: '700', name: '腾讯控股', industry: '互联网', market: 'HK' },
  { symbol: 'AAPL', name: 'Apple', industry: 'Consumer', market: 'US' },
]

test('filterWatchlistItems searches symbol name industry and market', () => {
  assert.deepEqual(filterWatchlistItems(items, { query: '兆易' }).map((x) => x.symbol), ['603986'])
  assert.deepEqual(filterWatchlistItems(items, { query: '光模块' }).map((x) => x.symbol), ['300308'])
  assert.deepEqual(filterWatchlistItems(items, { market: 'HK' }).map((x) => x.symbol), ['700'])
  assert.deepEqual(filterWatchlistItems(items, { market: 'US' }).map((x) => x.symbol), ['AAPL'])
})

test('filterWatchlistItems filters by latest recommendation', () => {
  assert.deepEqual(filterWatchlistItems(items, { recommendation: '可小仓试错' }).map((x) => x.symbol), ['300308'])
})
