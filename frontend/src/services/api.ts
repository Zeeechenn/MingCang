// Canonical API surface. HTTP transport lives in its own sibling service.
import { ApiError, apiBase, classifyStatus, request } from './http'

export { ApiError, createRequestClient, request } from './http'
export type { ApiErrorKind } from './http'

export const getWatchlist = () => request('/watchlist')

export const getDashboardSummary = () => request('/dashboard/summary')

export const getM63Reports = (mode = '') =>
  request(`/m63/reports${mode ? `?mode=${encodeURIComponent(mode)}` : ''}`)

export const getLatestM63Report = (mode) =>
  request(`/m63/reports/${encodeURIComponent(mode)}/latest`)

export const getM63Queue = () => request('/m63/queue')

export const getLatestM59Discretion = () => request('/m59/discretion/latest')

export const getPositions = (status = 'open') => request(`/positions?status=${status}`)

export const createPosition = (payload) =>
  request('/positions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const updatePosition = (id, payload) =>
  request(`/positions/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const closePosition = (id, payload = {}) =>
  request(`/positions/${id}/close`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const deleteClosedPosition = (id) =>
  request(`/positions/${id}/closed`, { method: 'DELETE' })

export const searchStocks = (q, market = 'CN') =>
  request(`/stocks/search?q=${encodeURIComponent(q)}&market=${market}`)

export const getReviews = (kind = '') =>
  request(`/reviews${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`)

export const getReview = (id) => request(`/reviews/${id}`)

export const getLatestReviews = () => request('/reviews/latest')

export const ensureDailyReview = () =>
  request('/reviews/daily/ensure', { method: 'POST' })

export const ensureLongTermReview = () =>
  request('/reviews/long-term/ensure', { method: 'POST' })

export const chatWithAI = (payload) =>
  request('/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export interface ChatStreamHandlers {
  onPrepare?: (data: any) => void
  onRunning?: (data: any) => void
  onEvidence?: (data: any) => void
  onToken?: (text: string) => void
  onMeta?: (data: any) => void
  onError?: (data: any) => void
  onDone?: (data: any) => void
}

function parseSseBlock(block: string) {
  const lines = block.split(/\r?\n/)
  let event = 'message'
  const data: string[] = []
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  return { event, data: data.join('\n') }
}

export async function chatWithAIStream(payload: any, handlers: ChatStreamHandlers = {}) {
  const res = await fetch(apiBase + '/ai/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new ApiError(`${res.status}: ${text}`, { status: res.status, kind: classifyStatus(res.status), path: '/ai/chat/stream' })
  }
  if (!res.body?.getReader) {
    const fallback = await chatWithAI(payload)
    handlers.onToken?.(fallback.answer || '')
    handlers.onDone?.(fallback)
    return fallback
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalPayload = null
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\n\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      if (!block.trim()) continue
      const parsed = parseSseBlock(block)
      const data = parsed.data ? JSON.parse(parsed.data) : {}
      if (parsed.event === 'prepare') handlers.onPrepare?.(data)
      if (parsed.event === 'running') handlers.onRunning?.(data)
      if (parsed.event === 'evidence') handlers.onEvidence?.(data)
      if (parsed.event === 'token') handlers.onToken?.(data.text || '')
      if (parsed.event === 'meta') handlers.onMeta?.(data)
      if (parsed.event === 'error') handlers.onError?.(data)
      if (parsed.event === 'done') {
        finalPayload = data
        handlers.onDone?.(data)
      }
    }
  }
  return finalPayload
}

export const confirmAIAction = (id) =>
  request(`/ai/actions/${id}/confirm`, { method: 'POST' })

export const getChatSessions = () => request('/ai/sessions')

export const createChatSession = (payload = {}) =>
  request('/ai/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const getChatMessages = (id) => request(`/ai/sessions/${id}/messages`)

export const archiveChatSession = (id) =>
  request(`/ai/sessions/${id}/archive`, { method: 'POST' })

export const getRuntimeConfig = () => request('/system/runtime-config')

export const updateRuntimeConfig = (payload) =>
  request('/system/runtime-config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const getSystemStatus = () => request('/system/status')

export const getSystemHealth = () => request('/system/health')

export const getJobRuns = (limit = 20, jobName = '') =>
  request(`/system/job-runs?limit=${limit}${jobName ? `&job_name=${encodeURIComponent(jobName)}` : ''}`)

export const getLLMUsage = (days = 7) => request(`/system/llm-usage?days=${days}`)

export const getMemoryEvolutionCandidates = (status = 'pending', limit = 50, offset = 0) =>
  request(`/memory/evolution/candidates?status=${encodeURIComponent(status)}&limit=${limit}&offset=${offset}`)

export const getMemoryEvolutionCandidate = (id) =>
  request(`/memory/evolution/candidates/${id}`)

export const promoteMemoryEvolutionCandidate = (id, confirmedBy = 'local_human') =>
  request(`/memory/evolution/candidates/${id}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed_by: confirmedBy }),
  })

export const rejectMemoryEvolutionCandidate = (id, reason, confirmedBy = 'local_human') =>
  request(`/memory/evolution/candidates/${id}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed_by: confirmedBy, note: reason }),
  })

export const archiveMemoryEvolutionCandidate = (id, reason, confirmedBy = 'local_human') =>
  request(`/memory/evolution/candidates/${id}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed_by: confirmedBy, reason }),
  })

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

export const removeStock = (symbol, market) =>
  request(`/watchlist/${symbol}${market ? `?market=${market}` : ''}`, { method: 'DELETE' })

export const getLatestSignal = (symbol, market) =>
  request(`/signals/${symbol}/latest${market ? `?market=${market}` : ''}`)

export const getSignals = (symbol, limit = 10, market) =>
  request(`/signals/${symbol}?limit=${limit}${market ? `&market=${market}` : ''}`)

export const getPrices = (symbol, days = 120, market) =>
  request(`/prices/${symbol}?days=${days}${market ? `&market=${market}` : ''}`)

export const getNews = (symbol, hours = 48, market) =>
  request(`/news/${symbol}?hours=${hours}${market ? `&market=${market}` : ''}`)

export const getSignalEval = (symbol, days = 60, market) =>
  request(`/signals/eval/${symbol}?days=${days}${market ? `&market=${market}` : ''}`)

export const getSignalEvidence = (symbol, limit = 5, market) =>
  request(`/signals/${symbol}/evidence?limit=${limit}${market ? `&market=${market}` : ''}`)

export const getFinancialMetrics = (symbol, market) =>
  request(`/research/${symbol}/financials${market ? `?market=${market}` : ''}`)

export const getLongTermLabel = (symbol, market) =>
  request(`/long-term/${symbol}${market ? `?market=${market}` : ''}`)

export const getResearchState = (symbol) =>
  request(`/research/${symbol}`)

export const getResearchDossier = (symbol) =>
  request(`/research/${symbol}/dossier`)

export const refreshResearchCopilot = (symbol) =>
  request(`/research/${symbol}/copilot`, { method: 'POST' })

export const getDataCoverage = () =>
  request('/system/data-coverage')

export const reviewLatestSignal = (symbol) =>
  request(`/research/${symbol}/review`, { method: 'POST' })

export const triggerLongTermTeam = () =>
  request(`/long-term/run`, { method: 'POST' })

export interface DeepResearchPayload {
  topic: string
  symbols?: string[]
  as_of?: string | null
}

export const runDeepResearch = ({ topic, symbols = [], as_of = null }: DeepResearchPayload) =>
  request('/research/deep/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, symbols, as_of }),
  })

export const startInitialize = () =>
  request('/system/initialize', { method: 'POST' })

export const getInitializeStatus = () =>
  request('/system/initialize/status')

export const getMemoryOverview = () => request('/memory/overview')

export const getMemoryList = ({ scope = '', category = '', q = '', limit = 100 } = {}) => {
  const params = new URLSearchParams()
  if (scope) params.set('scope', scope)
  if (category) params.set('category', category)
  if (q) params.set('q', q)
  params.set('limit', String(limit))
  return request(`/memory/list?${params.toString()}`)
}

export const getMemoryAudit = (q, limit = 50) =>
  request(`/memory/audit?q=${encodeURIComponent(q)}&limit=${limit}`)

export const getMemoryLayered = () => request('/memory/layered')

export const deleteMemory = (id) =>
  request(`/memory/${id}`, { method: 'DELETE' })

export const pinMemory = (id) =>
  request(`/memory/${id}/pin`, { method: 'POST' })

export const patchMemory = (id, payload) =>
  request(`/memory/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const getStockMemoryItems = ({ symbol = '', type = '', status = '', q = '', limit = 100 } = {}) => {
  const params = new URLSearchParams()
  if (symbol) params.set('symbol', symbol)
  if (type) params.set('type', type)
  if (status) params.set('status', status)
  if (q) params.set('q', q)
  params.set('limit', String(limit))
  return request(`/memory/stock-items?${params.toString()}`)
}

export const archiveStockMemory = (id) =>
  request(`/memory/stock-items/${id}/archive`, { method: 'POST' })

export const deleteStockMemory = (id) =>
  request(`/memory/stock-items/${id}`, { method: 'DELETE' })

export const patchStockMemory = (id, payload) =>
  request(`/memory/stock-items/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

// ── ATLAS 研究账本(后端 atlas_enabled 休眠门控;关闭时返回 503,由 live.js 落回演示) ──

export const getMemoryCandidates = () => request('/research/memory-candidates')

export const promoteMemoryCandidate = (id, confirmedBy = 'web_user') =>
  request(`/research/memory-candidates/${id}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed_by: confirmedBy }),
  })

export const rejectMemoryCandidate = (id, confirmedBy = 'web_user', note = null) =>
  request(`/research/memory-candidates/${id}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirmed_by: confirmedBy, note }),
  })

export const getForwardTheses = (symbol) => request(`/research/${symbol}/forward-theses`)

export const getTheses = (symbol) => request(`/research/${symbol}/theses`)

export const getCaseView = (symbol) => request(`/research/${symbol}/case-view`)

export const getReviewCases = (symbol) => request(`/research/${symbol}/review-cases`)
