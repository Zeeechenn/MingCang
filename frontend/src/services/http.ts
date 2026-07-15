export const apiBase = import.meta.env.VITE_API_BASE ?? '/api'
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS) || 15000

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

export function classifyStatus(status: number): ApiErrorKind {
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
  base = apiBase,
  fetchImpl = fetch,
  timeoutMs = DEFAULT_TIMEOUT_MS,
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
