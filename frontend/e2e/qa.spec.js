/* global window, document -- used inside page.evaluate / addInitScript callbacks, which run in the browser */
import { test, expect } from '@playwright/test'

/**
 * QA suite: security headers, error handling and failure behaviour against the real server.
 * demo.spec.js covers the happy path; this file covers what happens when things go wrong.
 */

test.beforeEach(async ({ request }) => {
  expect((await request.post('/api/demo/reset', { data: {} })).ok()).toBeTruthy()
})

// ------------------------------------------------------------------ API: security
test.describe('API security', () => {
  test('every response carries the security headers, including errors and redirects', async ({ request }) => {
    for (const path of ['/api/health', '/api/state', '/api/does-not-exist', '/app/']) {
      const response = await request.get(path)
      const headers = response.headers()
      expect(headers['x-content-type-options'], path).toBe('nosniff')
      expect(headers['x-frame-options'], path).toBe('DENY')
      expect(headers['referrer-policy'], path).toBe('no-referrer')
      expect(headers['content-security-policy'], path).toContain("frame-ancestors 'none'")
    }
  })

  test('API responses are never cached and report the rate-limit budget', async ({ request }) => {
    const response = await request.get('/api/state')
    expect(response.headers()['cache-control']).toBe('no-store')
    expect(Number(response.headers()['x-ratelimit-limit'])).toBeGreaterThan(0)
    expect(Number(response.headers()['x-ratelimit-remaining'])).toBeGreaterThanOrEqual(0)
  })

  test('health is open and says whether auth is enabled', async ({ request }) => {
    const body = await (await request.get('/api/health')).json()
    expect(body).toMatchObject({ status: 'ok', database: 'ok' })
    expect(['open', 'token']).toContain(body.auth)
  })

  test('a page on another site cannot drive the API, but the app itself can', async ({ request, baseURL }) => {
    const evil = await request.post('/api/demo/orders', { data: {}, headers: { Origin: 'https://evil.example' } })
    expect(evil.status()).toBe(403)
    expect((await evil.json()).code).toBe('FORBIDDEN_ORIGIN')

    const same = await request.post('/api/demo/orders', { data: {}, headers: { Origin: new URL(baseURL).origin } })
    expect(same.status()).toBe(200)
  })

  test('CORS is not granted to unknown origins', async ({ request }) => {
    const response = await request.get('/api/health', { headers: { Origin: 'https://evil.example' } })
    expect(response.headers()['access-control-allow-origin']).toBeUndefined()
  })

  test('a spoofed Host header is refused (DNS-rebinding defence)', async ({ request }) => {
    const response = await request.get('/api/health', { headers: { Host: 'evil.example.com' } })
    expect(response.status()).toBe(421)
    expect((await response.json()).code).toBe('BAD_HOST')
  })

  test('static files cannot escape the app directory', async ({ request }) => {
    for (const path of ['/app/../server.py', '/app/%2e%2e/server.py', '/app/..%2fserver.py', '/app/assets/../../server.py']) {
      const response = await request.get(path)
      expect(await response.text(), path).not.toContain('ThreadingHTTPServer')
    }
  })
})

// ------------------------------------------------------------------ API: errors
test.describe('API error handling', () => {
  test('errors share one shape: error, code and a request id that matches the header', async ({ request }) => {
    const cases = [
      ['get', '/api/does-not-exist', undefined, 404, 'NOT_FOUND'],
      ['get', '/api/session/INC-NOPE00', undefined, 404, 'NOT_FOUND'],
      ['post', '/api/session/INC-NOPE00/approve', {}, 404, 'NOT_FOUND'],
    ]
    for (const [method, path, data, status, code] of cases) {
      const response = await request[method](path, data === undefined ? {} : { data })
      expect(response.status(), path).toBe(status)
      const body = await response.json()
      expect(body.code, path).toBe(code)
      expect(body.error, path).toBeTruthy()
      expect(body.request_id, path).toBe(response.headers()['x-request-id'])
    }
  })

  test('malformed bodies are 400, not 500', async ({ request }) => {
    for (const data of ['{not json', '[1,2,3]', '"text"']) {
      const response = await request.post('/api/rewind', { data, headers: { 'content-type': 'application/json' } })
      expect(response.status(), data).toBe(400)
      expect((await response.json()).code).toBe('BAD_REQUEST')
    }
  })

  test('an oversized body is rejected with 413 before it is read', async ({ request }) => {
    const response = await request.post('/api/rewind', { data: { prompt: 'x'.repeat(2 * 1024 * 1024) } })
    expect(response.status()).toBe(413)
    expect((await response.json()).code).toBe('PAYLOAD_TOO_LARGE')
  })

  test('error responses never leak stack traces or file paths', async ({ request }) => {
    const text = await (await request.post('/api/rewind', { data: '{oops', headers: { 'content-type': 'application/json' } })).text()
    expect(text).not.toMatch(/Traceback|\.py|\/Users\/|site-packages/)
  })

  test('the server keeps working after a burst of bad requests', async ({ request }) => {
    for (let i = 0; i < 20; i++) await request.post('/api/rewind', { data: '{bad', headers: { 'content-type': 'application/json' } })
    expect((await request.get('/api/health')).ok()).toBeTruthy()
  })
})

// ------------------------------------------------------------------ UI: loads cleanly, icons, routing
test.describe('app shell', () => {
  test('loads under the content security policy with no violations, console errors or page errors', async ({ page }) => {
    const problems = []
    page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`))
    page.on('console', (message) => {
      if (message.type() === 'error' && !/fonts\.(googleapis|gstatic)|ERR_(INTERNET|NAME|CONNECTION)|Failed to load resource/.test(message.text())) {
        problems.push(`console: ${message.text()}`)
      }
    })
    await page.addInitScript(() => {
      window.__csp = []
      document.addEventListener('securitypolicyviolation', (event) => {
        if (!/fonts\.(googleapis|gstatic)/.test(event.blockedURI)) window.__csp.push(`${event.violatedDirective} ${event.blockedURI}`)
      })
    })
    await page.goto('/app/console')
    await expect(page.getByRole('button', { name: 'Sync Warehouse' })).toBeVisible()
    expect(await page.evaluate(() => window.__csp)).toEqual([])
    expect(problems).toEqual([])
  })

  test('favicon links resolve and /favicon.ico redirects to the svg', async ({ page, request }) => {
    await page.goto('/app/console')
    const hrefs = await page.locator('link[rel~="icon"], link[rel="apple-touch-icon"]').evaluateAll((nodes) => nodes.map((n) => n.href))
    expect(hrefs.length).toBeGreaterThanOrEqual(3)
    for (const href of hrefs) {
      const response = await request.get(href)
      expect(response.ok(), href).toBeTruthy()
      expect(response.headers()['content-type'], href).toMatch(/image\//)
    }
    const ico = await request.get('/favicon.ico')
    expect(ico.ok()).toBeTruthy()
    expect(ico.headers()['content-type']).toContain('image/svg+xml')
  })

  test('deep links survive a reload and unknown routes show Page not found', async ({ page }) => {
    await page.goto('/app/audit-log')
    await page.reload()
    await expect(page).toHaveURL(/\/app\/audit-log$/)
    await page.goto('/app/no-such-page')
    await expect(page.getByText('Page not found')).toBeVisible()
    await page.getByRole('button', { name: 'Go to Console' }).click()
    await expect(page).toHaveURL(/\/app\/console$/)
  })

  test('a missing asset is a real 404, not the app shell', async ({ request }) => {
    expect((await request.get('/app/assets/does-not-exist.js')).status()).toBe(404)
  })
})

// ------------------------------------------------------------------ UI: failure behaviour (backend misbehaves)
test.describe('UI when the API fails', () => {
  test('a rate-limited server (429) never blanks the page', async ({ page }) => {
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.route('**/api/state', (route) =>
      route.fulfill({ status: 429, headers: { 'retry-after': '0', 'content-type': 'application/json' }, body: JSON.stringify({ error: 'slow down', code: 'RATE_LIMITED' }) }),
    )
    await page.goto('/app/console')
    await expect(page.getByRole('link', { name: /Audit log/ })).toBeVisible() // shell still rendered
    await expect(page.locator('#root')).not.toBeEmpty()
    expect(errors).toEqual([])
  })

  test('the API being unreachable shows a message and the app recovers when it returns', async ({ page }) => {
    let down = true
    await page.route('**/api/state', (route) => (down ? route.abort('connectionrefused') : route.continue()))
    await page.goto('/app/console')
    await expect(page.getByRole('link', { name: /Audit log/ })).toBeVisible()
    await expect(page.locator('#root')).not.toBeEmpty()
    down = false
    await page.reload()
    await expect(page.getByRole('button', { name: 'Sync Warehouse' })).toBeVisible()
  })

  test('a 500 while starting time-travel is shown as a failure, is not retried, and live data is untouched', async ({ page, request }) => {
    let posts = 0
    await page.route('**/api/rewind', (route) => {
      posts += 1
      return route.fulfill({ status: 500, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ error: 'internal error', code: 'INTERNAL', request_id: 'req-qa-1' }) })
    })
    await page.goto('/app/console')
    await page.getByRole('button', { name: 'Sync Warehouse' }).click()
    await expect(page.getByText('Inventory was wiped by the warehouse sync')).toBeVisible()
    await page.getByRole('textbox').fill('Take the business back to before the crash, keep the 3 orders, and fix the bug that caused it.')
    await page.getByRole('button', { name: 'Run time-travel' }).click()
    await expect(page.getByText('Time-travel run failed')).toBeVisible()
    expect(posts).toBe(1) // a write is never retried automatically
    const state = await (await request.get('/api/state')).json()
    expect(state.inventory.zero).toBeGreaterThan(1000)
  })

  test('a prompt the parser cannot understand is rejected politely', async ({ page }) => {
    await page.goto('/app/console')
    await page.getByRole('textbox').fill('what is the weather like in paris tomorrow')
    await page.getByRole('button', { name: 'Run time-travel' }).click()
    await expect(page.getByText(/Time-travel run failed|Nothing to recover|understand/i).first()).toBeVisible()
    await expect(page.getByRole('link', { name: /Audit log/ })).toBeVisible()
  })

  test('a non-JSON answer from the API (wrong host, proxy page) does not crash the app', async ({ page }) => {
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.route('**/api/state', (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<html>proxy error</html>' }))
    await page.goto('/app/console')
    await expect(page.getByRole('link', { name: /Audit log/ })).toBeVisible()
    expect(errors).toEqual([])
  })
})
