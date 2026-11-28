import { test, beforeEach, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { request } from './httpClient.js'
import { ApiError } from './errors.js'

const realFetch = globalThis.fetch
let calls

/** fetch stub: each entry is a Response, a function(init) -> Response|Promise, or an Error to throw. */
function stubFetch(...steps) {
  calls = []
  let i = 0
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    const step = steps[Math.min(i++, steps.length - 1)]
    if (step instanceof Error) throw step
    return typeof step === 'function' ? step(init) : step
  }
}
const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })
const fast = { retryBaseMs: 0, retryMaxWaitMs: 0 }

beforeEach(() => {
  globalThis.localStorage = { getItem: () => null }
})
afterEach(() => {
  globalThis.fetch = realFetch
  delete globalThis.localStorage
})

async function failure(promise) {
  try {
    await promise
  } catch (error) {
    assert.ok(error instanceof ApiError, `expected ApiError, got ${error}`)
    return error
  }
  assert.fail('expected the request to fail')
}

test('returns parsed JSON on success and sends Accept + auth header when a token is stored', async () => {
  globalThis.localStorage = { getItem: () => 's3cret' }
  stubFetch(json({ ok: true }))
  assert.deepEqual(await request('/api/state'), { ok: true })
  assert.equal(calls[0].init.headers.Authorization, 'Bearer s3cret')
  assert.equal(calls[0].init.headers.Accept, 'application/json')
})

test('server error code and message win; 4xx are not retried', async () => {
  stubFetch(json({ error: 'session not found', code: 'NOT_FOUND', request_id: 'abc' }, 404))
  const error = await failure(request('/api/session/x', fast))
  assert.equal(error.code, 'NOT_FOUND')
  assert.equal(error.status, 404)
  assert.equal(error.message, 'session not found')
  assert.equal(calls.length, 1)
})

test('401 tells the user how to supply a token, whatever the server wrote', async () => {
  stubFetch(json({ error: 'missing or invalid bearer token', code: 'UNAUTHORIZED' }, 401))
  const error = await failure(request('/api/state', fast))
  assert.equal(error.code, 'UNAUTHORIZED')
  assert.match(error.message, /access token/)
  assert.equal(calls.length, 1)
})

test('GET retries a 429 honouring Retry-After and then succeeds', async () => {
  stubFetch(json({ error: 'slow down', code: 'RATE_LIMITED' }, 429, { 'retry-after': '0' }), json({ ok: 1 }))
  assert.deepEqual(await request('/api/state', fast), { ok: 1 })
  assert.equal(calls.length, 2)
})

test('GET gives up after the configured retries and reports RATE_LIMITED with the wait', async () => {
  stubFetch(json({ error: 'slow down', code: 'RATE_LIMITED' }, 429, { 'retry-after': '7' }))
  const error = await failure(request('/api/state', { ...fast, retries: 2 }))
  assert.equal(calls.length, 3)
  assert.equal(error.code, 'RATE_LIMITED')
  assert.equal(error.retryAfterSeconds, 7)
  assert.match(error.message, /7s/)
  assert.equal(error.retryable, true)
})

test('writes are never retried, even on 503 or a network error', async () => {
  stubFetch(json({ error: 'busy', code: 'DB_BUSY' }, 503))
  const busy = await failure(request('/api/session/x/approve', { method: 'POST', body: {}, ...fast, retries: 5 }))
  assert.equal(busy.code, 'DB_BUSY')
  assert.equal(calls.length, 1)

  stubFetch(new TypeError('failed to fetch'))
  const offline = await failure(request('/api/rewind', { method: 'POST', body: { prompt: 'x' }, ...fast }))
  assert.equal(offline.code, 'NETWORK_ERROR')
  assert.equal(calls.length, 1)
})

test('network errors on GET are retried, then surface as NETWORK_ERROR', async () => {
  stubFetch(new TypeError('failed to fetch'))
  const error = await failure(request('/api/state', { ...fast, retries: 2 }))
  assert.equal(calls.length, 3)
  assert.equal(error.code, 'NETWORK_ERROR')
  assert.match(error.message, /Could not reach the server/)
})

test('5xx without a body becomes SERVER_ERROR and quotes the request id for support', async () => {
  stubFetch(new Response('boom', { status: 500, headers: { 'x-request-id': 'req-42', 'content-type': 'text/plain' } }))
  const error = await failure(request('/api/state', { ...fast, retries: 0 }))
  assert.equal(error.code, 'SERVER_ERROR')
  assert.equal(error.requestId, 'req-42')
  assert.match(error.message, /ref req-42/)
})

test('a 200 that is not JSON (wrong host, SPA fallback) is INVALID_RESPONSE, not a silent null', async () => {
  stubFetch(new Response('<!doctype html>', { status: 200, headers: { 'content-type': 'text/html' } }))
  const error = await failure(request('/api/state', fast))
  assert.equal(error.code, 'INVALID_RESPONSE')
})

test('a hung request times out as TIMEOUT', async () => {
  stubFetch((init) => new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(Object.assign(new Error('x'), { name: 'AbortError' })))))
  const error = await failure(request('/api/state', { timeoutMs: 20, retries: 0 }))
  assert.equal(error.code, 'TIMEOUT')
})

test('aborting from the caller is ABORTED and is not retried', async () => {
  stubFetch((init) => new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(Object.assign(new Error('x'), { name: 'AbortError' })))))
  const controller = new AbortController()
  const pending = failure(request('/api/state', { signal: controller.signal, timeoutMs: 5000, retries: 3, ...fast }))
  setTimeout(() => controller.abort(), 10)
  const error = await pending
  assert.equal(error.code, 'ABORTED')
  assert.equal(calls.length, 1)
})

test('an already-aborted signal never hits the network', async () => {
  stubFetch(json({}))
  const controller = new AbortController()
  controller.abort()
  const error = await failure(request('/api/state', { signal: controller.signal, ...fast }))
  assert.equal(error.code, 'ABORTED')
})
