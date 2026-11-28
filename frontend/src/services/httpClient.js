import {
  API_BASE_URL,
  API_MAX_RETRIES,
  API_RETRY_BASE_MS,
  API_RETRY_MAX_WAIT_MS,
  API_TIMEOUT_MS,
  TOKEN_STORAGE_KEY,
} from './config.js'
import { ApiError } from './errors.js'

/**
 * Small fetch wrapper for the real backend. Every failure becomes an ApiError with a stable `code`:
 *   ABORTED, TIMEOUT, NETWORK_ERROR          the request never produced a response
 *   UNAUTHORIZED, FORBIDDEN_ORIGIN, BAD_HOST, NOT_FOUND, BAD_REQUEST, PAYLOAD_TOO_LARGE, RATE_LIMITED
 *   DB_BUSY / BUSY, SERVER_ERROR             the server said no (or is struggling)
 *   INVALID_RESPONSE                         a 2xx that was not JSON (a proxy or the wrong host answered)
 * The server's own `code` wins when it sends one. Safe reads (GET) are retried a couple of times with backoff;
 * writes never are, so a recovery can not be started or approved twice by accident.
 *
 * Usage: request('/your/path', { method: 'POST', body: {...} })
 */

const RETRYABLE_STATUS = new Set([429, 502, 503, 504])

const STATUS_CODES = {
  400: ['BAD_REQUEST', 'The request was not accepted.'],
  401: ['UNAUTHORIZED', `This server needs an access token. Run localStorage.setItem('${TOKEN_STORAGE_KEY}', '<token>') and reload.`],
  403: ['FORBIDDEN_ORIGIN', 'This page is not allowed to call the server.'],
  404: ['NOT_FOUND', 'That item was not found.'],
  413: ['PAYLOAD_TOO_LARGE', 'The request was too large.'],
  421: ['BAD_HOST', 'The server refused this address.'],
  429: ['RATE_LIMITED', 'Too many requests. Please wait a moment.'],
}

/** If the server runs with TT_API_TOKEN, set it once in the browser: localStorage.setItem('tt_api_token', '<token>'). */
function authHeader() {
  try {
    const token = globalThis.localStorage?.getItem(TOKEN_STORAGE_KEY)
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new ApiError('Request cancelled.', { code: 'ABORTED' }))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new ApiError('Request cancelled.', { code: 'ABORTED' }))
      },
      { once: true },
    )
  })

/** Milliseconds to wait before attempt `attempt` (0-based): Retry-After when given, else exponential backoff + jitter. */
function backoffMs(attempt, retryAfterSeconds, { baseMs, maxWaitMs }) {
  if (retryAfterSeconds != null) return Math.min(retryAfterSeconds * 1000, maxWaitMs)
  return Math.min(baseMs * 2 ** attempt + Math.random() * baseMs, maxWaitMs)
}

/** One HTTP attempt. Resolves to the parsed JSON, or throws an ApiError. */
async function attempt(url, { method, body, signal, headers, timeoutMs }) {
  if (signal?.aborted) throw new ApiError('Request cancelled.', { code: 'ABORTED' }) // never touch the network
  const controller = new AbortController()
  let timedOut = false
  const timer = timeoutMs > 0 ? setTimeout(() => ((timedOut = true), controller.abort()), timeoutMs) : null
  const onCallerAbort = () => controller.abort()
  signal?.addEventListener('abort', onCallerAbort, { once: true })

  try {
    let response
    try {
      response = await fetch(url, {
        method,
        signal: controller.signal,
        headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}), ...authHeader(), ...headers },
        body: body ? JSON.stringify(body) : undefined,
      })
    } catch (error) {
      if (error?.name === 'AbortError') {
        if (timedOut) throw new ApiError('The server took too long to respond. Try again.', { code: 'TIMEOUT' })
        throw new ApiError('Request cancelled.', { code: 'ABORTED' })
      }
      throw new ApiError('Could not reach the server. Check your connection and that the backend is running.', { code: 'NETWORK_ERROR' })
    }

    const requestId = response.headers.get('x-request-id')
    const retryHeader = Number.parseInt(response.headers.get('retry-after') ?? '', 10)
    const retryAfterSeconds = Number.isFinite(retryHeader) && retryHeader >= 0 ? retryHeader : null
    const isJson = response.headers.get('content-type')?.includes('application/json')
    const payload = isJson ? await response.json().catch(() => null) : null

    if (!response.ok) {
      const [fallbackCode, fallbackMessage] = STATUS_CODES[response.status] ?? (response.status >= 500 ? ['SERVER_ERROR', 'The server hit a problem.'] : ['HTTP_ERROR', `Request failed with status ${response.status}.`])
      const code = payload?.code || fallbackCode
      let message = payload?.message || payload?.error || fallbackMessage
      if (response.status === 401) message = fallbackMessage // always tell the user what to do, not just "invalid token"
      if (code === 'RATE_LIMITED' && retryAfterSeconds != null) message = `Too many requests. Try again in ${retryAfterSeconds}s.`
      const ref = payload?.request_id || requestId
      if (response.status >= 500 && ref) message = `${message} (ref ${ref})`
      throw new ApiError(message, { code, status: response.status, details: payload, requestId: ref, retryAfterSeconds })
    }
    if (payload === null) {
      throw new ApiError('The server sent an unexpected response. Is the API address correct?', {
        code: 'INVALID_RESPONSE',
        status: response.status,
        requestId,
      })
    }
    return payload
  } finally {
    if (timer) clearTimeout(timer)
    signal?.removeEventListener('abort', onCallerAbort)
  }
}

/**
 * @param {string} path
 * @param {{method?: string, body?: object, signal?: AbortSignal, headers?: object, timeoutMs?: number,
 *          retries?: number, retryBaseMs?: number, retryMaxWaitMs?: number}} [options]
 */
export async function request(path, options = {}) {
  const { method = 'GET', body, signal, headers } = options
  const timeoutMs = options.timeoutMs ?? API_TIMEOUT_MS
  const retries = method === 'GET' ? (options.retries ?? API_MAX_RETRIES) : 0
  const policy = { baseMs: options.retryBaseMs ?? API_RETRY_BASE_MS, maxWaitMs: options.retryMaxWaitMs ?? API_RETRY_MAX_WAIT_MS }
  const url = `${API_BASE_URL}${path}`

  for (let n = 0; ; n++) {
    try {
      return await attempt(url, { method, body, signal, headers, timeoutMs })
    } catch (error) {
      const transient = error instanceof ApiError && (['NETWORK_ERROR', 'TIMEOUT'].includes(error.code) || RETRYABLE_STATUS.has(error.status))
      if (!transient || n >= retries) throw error
      await sleep(backoffMs(n, error.retryAfterSeconds, policy), signal)
    }
  }
}
