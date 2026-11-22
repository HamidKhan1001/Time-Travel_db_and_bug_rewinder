/**
 * Runtime configuration, read from Vite env variables (see .env.example).
 * Only VITE_* variables reach the browser. Never put secrets here.
 */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false'
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
