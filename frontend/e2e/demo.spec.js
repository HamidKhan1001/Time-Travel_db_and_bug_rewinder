import { test, expect } from '@playwright/test'

const PROMPT = 'Take the business back to before the crash, keep the 3 orders, and fix the bug that caused it.'

test.beforeEach(async ({ request }) => {
  const reset = await request.post('/api/demo/reset', { data: {} })
  expect(reset.ok()).toBeTruthy()
})

/** Console: crash the warehouse, place the orders, run time-travel and land on the Review screen. */
async function runToReview(page) {
  await page.goto('/app/console')
  await page.getByRole('button', { name: 'Sync Warehouse' }).click()
  await expect(page.getByText('Inventory was wiped by the warehouse sync')).toBeVisible()
  await page.getByRole('button', { name: 'Place 3 Orders' }).click()
  await expect(page.getByText('#1043').first()).toBeVisible()
  await page.getByRole('textbox').fill(PROMPT)
  await page.getByRole('button', { name: 'Run time-travel' }).click()
  await expect(page.getByRole('button', { name: /Approve & go live/ })).toBeEnabled({ timeout: 60_000 })
}

test('full demo: crash, rewind, approve, patched re-run, audit log', async ({ page }) => {
  await runToReview(page)

  // The merge plan shows the oversold order and the verified patch before anything is applied.
  await expect(page.getByText(/Conflict Resolution/)).toBeVisible()
  await expect(page.getByText(/Patch Diff: app\/handlers\.py/)).toBeVisible()

  await page.getByRole('button', { name: /Approve & go live/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Apply to live' }).click()
  await expect(page.getByText(/is live\. You can undo it at any time/)).toBeVisible()

  await page.getByRole('button', { name: 'Back to console' }).click()
  await expect(page.getByText('Inventory was wiped')).toHaveCount(0)
  await page.getByRole('button', { name: 'Re-run Sync' }).click()
  await expect(page.getByText('Warehouse sync · touched 1 row').first()).toBeVisible()

  await page.getByRole('link', { name: /Audit log/ }).click()
  const row = page.getByRole('row').filter({ hasText: 'keep the 3 orders' }).first()
  await expect(row).toBeVisible()
  await expect(row).toContainText('Applied')
})

test('undo restores the crashed state and the audit log keeps the whole story', async ({ page, request }) => {
  await runToReview(page)
  await page.getByRole('button', { name: /Approve & go live/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Apply to live' }).click()
  await expect(page.getByText(/is live\./)).toBeVisible()

  await page.getByRole('button', { name: 'Undo recovery' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Undo recovery' }).click()
  await expect(page.getByText('Inventory was wiped by the warehouse sync')).toBeVisible()

  const audit = await (await request.get('/api/audit?status=undone')).json()
  expect(audit.total).toBe(1)
  const events = await (await request.get(`/api/session/${audit.items[0].id}/audit`)).json()
  expect(events.events.map((e) => e.event_type)).toEqual(expect.arrayContaining(['recovery_completed', 'undo_initiated', 'undo_completed']))
})

test('discarding a plan never touches live data', async ({ page, request }) => {
  await runToReview(page)
  await page.getByRole('button', { name: 'Discard plan' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Discard plan' }).click()
  await expect(page.getByText('Inventory was wiped by the warehouse sync')).toBeVisible()
  const state = await (await request.get('/api/state')).json()
  expect(state.inventory.zero).toBeGreaterThan(1000) // still wiped: nothing was applied
  expect((await (await request.get('/api/audit?status=discarded')).json()).total).toBe(1)
})
