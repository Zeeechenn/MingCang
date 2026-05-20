import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiError, createRequestClient } from './api.js'

test('request retries transient GET failures', async () => {
  const responses = [
    { ok: false, status: 503, text: async () => 'busy' },
    { ok: true, status: 200, json: async () => ({ ok: true }) },
  ]
  let calls = 0
  const client = createRequestClient({
    fetchImpl: async () => responses[calls++],
    sleep: async () => {},
    timeoutMs: 1000,
    retries: 1,
  })

  const result = await client.request('/system/health')

  assert.deepEqual(result, { ok: true })
  assert.equal(calls, 2)
})

test('request classifies non-ok responses', async () => {
  const client = createRequestClient({
    fetchImpl: async () => ({ ok: false, status: 404, text: async () => 'missing' }),
    sleep: async () => {},
    retries: 0,
  })

  await assert.rejects(
    () => client.request('/missing'),
    (err) => err instanceof ApiError && err.status === 404 && err.kind === 'client',
  )
})
