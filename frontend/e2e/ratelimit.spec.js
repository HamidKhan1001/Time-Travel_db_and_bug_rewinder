import { test, expect } from '@playwright/test'

// Runs against the second web server in playwright.config.js: reads burst=5 (1/s refill), writes burst=2.
test.use({ baseURL: 'http://127.0.0.1:8124' })

test.describe.configure({ mode: 'serial' }) // the buckets are shared state, so keep these in order

/** Let the bucket refill so each test starts with a full burst. */
const refill = (page) => page.waitForTimeout(5500)

test('reads beyond the burst get 429 with Retry-After, and recover after the wait', async ({ request }) => {
  const statuses = []
  let limited
  for (let i = 0; i < 8; i++) {
    const response = await request.get('/api/state')
    statuses.push(response.status())
    if (response.status() === 429) limited ??= response
  }
  expect(statuses.slice(0, 5)).toEqual([200, 200, 200, 200, 200])
  expect(statuses).toContain(429)

  const body = await limited.json()
  expect(body.code).toBe('RATE_LIMITED')
  expect(body.request_id).toBe(limited.headers()['x-request-id'])
  const wait = Number(limited.headers()['retry-after'])
  expect(wait).toBeGreaterThanOrEqual(1)
  expect(limited.headers()['x-ratelimit-remaining']).toBe('0')

  await new Promise((resolve) => setTimeout(resolve, (wait + 1) * 1000))
  expect((await request.get('/api/state')).status()).toBe(200)
})

test('health checks are never rate limited', async ({ request }) => {
  for (let i = 0; i < 30; i++) expect((await request.get('/api/health')).status()).toBe(200)
})

test('writes have their own, stricter bucket and do not consume read tokens', async ({ page, request }) => {
  await refill(page)
  const writes = []
  for (let i = 0; i < 4; i++) writes.push((await request.post('/api/demo/orders', { data: {} })).status())
  expect(writes.slice(0, 2)).toEqual([200, 200])
  expect(writes.slice(2)).toEqual([429, 429])
  expect((await request.get('/api/state')).status()).toBe(200)
})

test('the app rides out rate limiting: the client waits per Retry-After and the page still loads', async ({ page }) => {
  await refill(page)
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  let limitedResponses = 0
  page.on('response', (response) => {
    if (response.url().includes('/api/') && response.status() === 429) limitedResponses += 1
  })
  // Burn the read bucket first so the app's own first requests are throttled.
  await page.request.get('/api/state')
  await page.request.get('/api/state')
  await page.request.get('/api/state')
  await page.request.get('/api/state')
  await page.goto('/app/console')
  await expect(page.getByRole('button', { name: 'Sync Warehouse' })).toBeVisible({ timeout: 20_000 })
  expect(errors).toEqual([])
  expect(limitedResponses).toBeGreaterThanOrEqual(1) // the app really was throttled, and it still got through
})
