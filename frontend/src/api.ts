const BASE = '/api'

export type ApiErrorKind = 'transient' | 'server' | 'client' | 'timeout' | 'network' | 'unknown'

interface ApiErrorInfo {
  status?: number | null
  kind?: ApiErrorKind
  path?: string
  retriable?: boolean
}

export class ApiError extends Error {
  status: number | null
  kind: ApiErrorKind
  path: string
  retriable: boolean

  constructor(message: string, { status = null, kind = 'unknown', path = '', retriable = false }: ApiErrorInfo = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.kind = kind
    this.path = path
    this.retriable = retriable
  }
}

function classifyStatus(status: number): ApiErrorKind {
  if (status === 408 || status === 429) return 'transient'
  if (status >= 500) return 'server'
  if (status >= 400) return 'client'
  return 'unknown'
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

interface RequestClientOptions {
  base?: string
  fetchImpl?: typeof fetch
  timeoutMs?: number
  retries?: number
  sleep?: (ms: number) => Promise<void>
}

export function createRequestClient({
  base = BASE,
  fetchImpl = fetch,
  timeoutMs = 15000,
  retries = 1,
  sleep = defaultSleep,
}: RequestClientOptions = {}) {
  async function request(path: string, options: RequestInit = {}): Promise<any> {
    const method = (typeof options.method === 'string' ? options.method : 'GET').toUpperCase()
    const retryableMethod = method === 'GET'
    const maxAttempts = retryableMethod ? retries + 1 : 1
    let lastError: ApiError | undefined

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
      const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null
      try {
        const res = await fetchImpl(base + path, { ...options, signal: controller?.signal })
        if (timer) clearTimeout(timer)
        if (!res.ok) {
          const text = await res.text()
          const kind = classifyStatus(res.status)
          throw new ApiError(`${res.status}: ${text}`, {
            status: res.status,
            kind,
            path,
            retriable: retryableMethod && (kind === 'server' || kind === 'transient'),
          })
        }
        return res.json()
      } catch (err) {
        if (timer) clearTimeout(timer)
        if (err instanceof Error && err.name === 'AbortError') {
          lastError = new ApiError(`请求超时：${path}`, { kind: 'timeout', path, retriable: retryableMethod })
        } else if (err instanceof ApiError) {
          lastError = err
        } else {
          lastError = new ApiError((err instanceof Error && err.message) || '网络请求失败', { kind: 'network', path, retriable: retryableMethod })
        }
        if (!lastError.retriable || attempt >= maxAttempts) throw lastError
        await sleep(250 * attempt)
      }
    }
    throw lastError
  }

  return { request }
}

const defaultClient = createRequestClient()
export const request = defaultClient.request

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
  const res = await fetch(BASE + '/ai/chat/stream', {
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

export const getLLMUsage = (days = 7) => request(`/system/llm-usage?days=${days}`)

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

export const runDeepResearch = ({ topic, symbols = [], as_of = null }) =>
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
