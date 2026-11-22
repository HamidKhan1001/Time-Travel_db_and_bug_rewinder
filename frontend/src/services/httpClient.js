import { API_BASE_URL } from './config.js'
import { ApiError } from './errors.js'

/**
 * Small fetch wrapper for when the backend is connected.
 * Usage: request('/your/path', { method: 'POST', body: {...} })
 * Paths are intentionally not defined here — agree them with the backend team.
 */
export async function request(path, { method = 'GET', body, signal, headers } = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      signal,
      headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw new ApiError('Request cancelled.', { code: 'ABORTED' })
    throw new ApiError('Could not reach the server. Check that the backend is running.', { code: 'NETWORK_ERROR' })
  }

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const payload = isJson ? await response.json().catch(() => null) : null
  if (!response.ok) {
    throw new ApiError(payload?.message || `Request failed with status ${response.status}.`, {
      code: payload?.code || 'HTTP_ERROR',
      status: response.status,
      details: payload,
    })
  }
  return payload
}
