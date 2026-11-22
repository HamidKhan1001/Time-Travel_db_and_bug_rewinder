import test from 'node:test'
import assert from 'node:assert/strict'
import { parseDiff, sessionError, stepsFromSession, toPlan, toSnapshot } from './adapters.js'

const DIFF = `--- a/app/handlers.py
+++ b/app/handlers.py
@@ -13,8 +13,10 @@
     stock = int(payload.get("stock", 0))
-    sql = "UPDATE inventory SET stock = ?"
+    sql = "UPDATE inventory SET stock = ? WHERE sku = ?"
`

const session = (over = {}) => ({
  id: 'INC-ABC123',
  prompt: 'Take the business back to 2 minutes ago',
  phase: 'awaiting_approval',
  events: [],
  parsed: { source: 'regex', confidence: 0.9, target_ts: 1000, incident_ts: 1100, remediate: true },
  timeline: { now: 1200 },
  branch: { events_reversed: 1434, ms: 12 },
  delta: { post_crash: 1, pre_crash: 0, orders: [{ id: 1043, customer_id: 3, created_at: 1150, phase: 'post-crash', items: [['APX-0777', 3]] }] },
  plan: {
    restored_rows: 1419, orders_preserved: 1, zero_before: 1420, dry_run_ok: true, dry_run: [{ ok: true }, { ok: true }],
    conflicts: [{ order_id: 1043, sku: 'APX-0777', shortfall: 1, reason: 'oversold' }],
    risk: { score: 25, label: 'MEDIUM', factors: [] },
  },
  patch: { found: true, patch_ok: true, rows_affected: 1420, incident_sql: 'UPDATE inventory SET stock = ?', diff: DIFF, tests: [{ ok: true, detail: '1 row(s) updated' }] },
  recovery_preview: { rows: [{ table: 'inventory', key: 'APX-0001', before: 0, after: 169 }] },
  ...over,
})

test('parseDiff splits a unified diff into typed lines', () => {
  const d = parseDiff(DIFF)
  assert.equal(d.file, 'app/handlers.py')
  assert.equal(d.hunk, '@@ -13,8 +13,10 @@')
  assert.deepEqual(d.lines.map((l) => l.type), ['context', 'del', 'add'])
  assert.equal(parseDiff(''), null)
})

test('toPlan converts the backend session to the UI plan shape', () => {
  const plan = toPlan(session())
  assert.equal(plan.id, 'INC-ABC123')
  assert.equal(plan.risk.score, 0.25)
  assert.equal(plan.parsedBy, 'rule-based')
  assert.equal(plan.stats.kept, 1)
  assert.equal(plan.stats.discarded, 1420)
  assert.equal(plan.stats.conflicts, 1)
  assert.equal(plan.stats.legitimateRowsLost, 0)
  assert.equal(plan.operations.find((o) => o.id === 'op-1043').decision, 'resolved')
  assert.equal(plan.operations.at(-1).operation, 'SYNC_WIPE')
  assert.deepEqual([plan.conflict.requestedQty, plan.conflict.availableQty], [3, 2])
  assert.equal(plan.patch.verification.passed, true)
  assert.equal(plan.patch.verification.rowsTouchedAfter, 1)
  assert.equal(plan.patch.verification.rowsTouchedBefore, 1420)
  assert.equal(plan.verifiedSuites, 3)
})

test('toPlan without a patch leaves patch null and never claims zero loss when the dry run failed', () => {
  const plan = toPlan(session({ patch: { found: false, explanation: 'none' }, plan: { ...session().plan, dry_run_ok: false } }))
  assert.equal(plan.patch, null)
  assert.equal(plan.dryRunOk, false)
  assert.equal(plan.stats.legitimateRowsLost, null)
})

test('stepsFromSession maps phases to the 7 UI steps', () => {
  const planning = stepsFromSession(session({ phase: 'planning', events: [{ msg: 'merging' }] }))
  assert.deepEqual(planning.map((s) => s.status), ['done', 'done', 'running', 'running', 'running', 'pending', 'pending'])
  assert.equal(planning[2].log, 'merging')
  const done = stepsFromSession(session())
  assert.ok(done.every((s) => s.status === 'done'))
  assert.match(done[0].log, /1,?434/)
})

test('sessionError returns the last error event without the boilerplate prefix', () => {
  const e = sessionError({ events: [{ level: 'error', msg: 'Aborted safely, production untouched: Could not find a rewind point in the request' }] })
  assert.equal(e.code, 'INTENT_UNPARSEABLE')
  assert.match(e.message, /^Could not find a rewind point/)
})

test('toSnapshot flags the crash, hides old orders, and stops reporting an incident once patched', () => {
  const state = {
    inventory: { sample: [{ sku: 'APX-0007', name: 'Alpine Water Bottle', stock: 0 }, { sku: 'APX-0777', name: 'Limited Edition Trail Pack', stock: 0 }] },
    orders: [
      { id: 1040, customer_id: 1, status: 'paid', created_at: 900, items: [{ sku: 'APX-0001', name: 'x', qty: 1 }] },
      { id: 1041, customer_id: 1, customer: 'Ava', status: 'paid', created_at: 1150, items: [{ sku: 'APX-0042', name: 'Jacket', qty: 1 }, { sku: 'APX-0100', name: 'Pack', qty: 2 }] },
    ],
    incident: { ts: 1100, rows_affected: 1420 },
    patched: false,
  }
  const snap = toSnapshot(state, {})
  assert.equal(snap.incident.active, true)
  assert.equal(snap.inventory[0].status, 'zeroed')
  assert.equal(snap.inventory[1].limited, true)
  assert.deepEqual(snap.orders.map((o) => o.id), ['#1041'])
  assert.equal(snap.orders[0].qty, 3)
  assert.equal(snap.changeLog[0].kind === 'ok' || snap.changeLog[0].kind === 'crash', true)
  const fixed = toSnapshot({ ...state, patched: true }, { recovery: { id: 'INC-1' }, prevStocks: { 'APX-0007': 0 } })
  assert.equal(fixed.incident, null)
})
