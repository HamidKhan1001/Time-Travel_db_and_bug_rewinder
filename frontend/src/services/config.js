/**
 * Runtime configuration, read from Vite env variables (see .env.example).
 * Only VITE_* variables reach the browser. Never put secrets here.
 * `import.meta.env` is undefined under plain Node (unit tests), so every read has a fallback.
 */
const env = import.meta.env ?? {}

/** A non-negative integer from an env string, or the default when missing/invalid. */
const whole = (value, fallback) => {
  const n = Number.parseInt(value, 10)
  return Number.isFinite(n) && n >= 0 ? n : fallback
}

export const USE_MOCKS = env.VITE_USE_MOCKS !== 'false'
export const API_BASE_URL = (env.VITE_API_BASE_URL || '').replace(/\/$/, '')

/** Give up on a single request after this long. */
export const API_TIMEOUT_MS = whole(env.VITE_API_TIMEOUT_MS, 30_000)
/** Extra attempts for safe reads (GET) after a network error, timeout, 429 or 502/503/504. Writes are never retried. */
export const API_MAX_RETRIES = whole(env.VITE_API_MAX_RETRIES, 2)
export const API_RETRY_BASE_MS = whole(env.VITE_API_RETRY_BASE_MS, 400)
/** Longest wait honoured from a Retry-After header before retrying a read. */
export const API_RETRY_MAX_WAIT_MS = whole(env.VITE_API_RETRY_MAX_WAIT_MS, 10_000)

/** How often the console polls a running recovery, and how long it waits before giving up. */
export const POLL_INTERVAL_MS = whole(env.VITE_POLL_INTERVAL_MS, 350)
export const RECOVERY_MAX_WAIT_MS = whole(env.VITE_RECOVERY_MAX_WAIT_MS, 120_000)

/** localStorage key holding the bearer token when the server runs with TT_API_TOKEN. */
export const TOKEN_STORAGE_KEY = env.VITE_TOKEN_STORAGE_KEY || 'tt_api_token'
