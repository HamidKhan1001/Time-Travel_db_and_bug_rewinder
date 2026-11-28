/** Error type every service function throws, mock or real. */
export class ApiError extends Error {
  constructor(message, { code = 'UNKNOWN', status = 0, details = null, requestId = null, retryAfterSeconds = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
    this.requestId = requestId // the server's X-Request-Id: quote it when reporting a problem
    this.retryAfterSeconds = retryAfterSeconds
  }

  /** True for failures that may succeed if the same request is simply tried again later. */
  get retryable() {
    return ['NETWORK_ERROR', 'TIMEOUT', 'RATE_LIMITED', 'DB_BUSY', 'BUSY', 'SERVER_ERROR'].includes(this.code)
  }
}

/** Turns anything thrown into a short message for the UI. */
export function errorMessage(error) {
  if (!error) return 'Something went wrong.'
  if (typeof error === 'string') return error
  return error.message || 'Something went wrong.'
}
