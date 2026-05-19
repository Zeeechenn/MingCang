import assert from 'node:assert/strict'
import test from 'node:test'

import { getArchiveState, nextArchiveIntent } from './chatArchive.js'

test('nextArchiveIntent asks for confirmation before archiving', () => {
  assert.deepEqual(nextArchiveIntent(null, 'session-1'), {
    action: 'confirm',
    confirmingId: 'session-1',
  })

  assert.deepEqual(nextArchiveIntent('session-1', 'session-1'), {
    action: 'archive',
    confirmingId: null,
  })
})

test('getArchiveState labels sessions by confirmation state', () => {
  assert.deepEqual(getArchiveState('session-1', 'session-1'), {
    isConfirming: true,
    label: '确认归档',
  })
  assert.deepEqual(getArchiveState('session-2', 'session-1'), {
    isConfirming: false,
    label: '归档',
  })
})
