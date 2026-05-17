const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, options)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const getWatchlist = () => request('/watchlist')

export const getDashboardSummary = () => request('/dashboard/summary')

export const getRuntimeConfig = () => request('/system/runtime-config')

export const updateRuntimeConfig = (payload) =>
  request('/system/runtime-config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const getSystemStatus = () => request('/system/status')

export const getSystemHealth = () => request('/system/health')

export const triggerKillSwitch = (reason = 'manual') =>
  request(`/system/kill-switch/trigger?reason=${encodeURIComponent(reason)}`, { method: 'POST' })

export const resetKillSwitch = () =>
  request('/system/kill-switch/reset', { method: 'POST' })

export const getModelStatus = () => request('/model/status')

export const trainModel = () =>
  request('/model/train', { method: 'POST' })

export const addStock = (symbol, name, market) =>
  request(`/watchlist?symbol=${encodeURIComponent(symbol)}&name=${encodeURIComponent(name)}&market=${market}`, {
    method: 'POST',
  })

export const removeStock = (symbol) =>
  request(`/watchlist/${symbol}`, { method: 'DELETE' })

export const getLatestSignal = (symbol) =>
  request(`/signals/${symbol}/latest`)

export const getSignals = (symbol, limit = 10) =>
  request(`/signals/${symbol}?limit=${limit}`)

export const getPrices = (symbol, days = 120) =>
  request(`/prices/${symbol}?days=${days}`)

export const getNews = (symbol, hours = 48) =>
  request(`/news/${symbol}?hours=${hours}`)

export const getSignalEval = (symbol, days = 60) =>
  request(`/signals/eval/${symbol}?days=${days}`)

export const getSignalEvidence = (symbol, limit = 5) =>
  request(`/signals/${symbol}/evidence?limit=${limit}`)

export const getLongTermLabel = (symbol) =>
  request(`/long-term/${symbol}`)

export const getResearchState = (symbol) =>
  request(`/research/${symbol}`)

export const getDataCoverage = () =>
  request('/system/data-coverage')

export const reviewLatestSignal = (symbol) =>
  request(`/research/${symbol}/review`, { method: 'POST' })

export const triggerLongTermTeam = () =>
  request(`/long-term/run`, { method: 'POST' })

export const runDeepResearch = ({ topic, symbols = [], as_of = null }) =>
  request('/research/deep/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, symbols, as_of }),
  })
