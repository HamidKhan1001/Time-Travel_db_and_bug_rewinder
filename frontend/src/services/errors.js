/** Error type every service function throws, mock or real. */
export class ApiError extends Error {
  constructor(message, { code = 'UNKNOWN', status = 0, details = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

/** Turns anything thrown into a short message for the UI. */
export function errorMessage(error) {
  if (!error) return 'Something went wrong.'
  if (typeof error === 'string') return error
  return error.message || 'Something went wrong.'
}
