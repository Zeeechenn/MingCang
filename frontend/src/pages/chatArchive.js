export function nextArchiveIntent(confirmingId, sessionId) {
  if (confirmingId === sessionId) {
    return { action: 'archive', confirmingId: null }
  }
  return { action: 'confirm', confirmingId: sessionId }
}

export function getArchiveState(sessionId, confirmingId) {
  const isConfirming = confirmingId === sessionId
  return {
    isConfirming,
    label: isConfirming ? '确认归档' : '归档',
  }
}
