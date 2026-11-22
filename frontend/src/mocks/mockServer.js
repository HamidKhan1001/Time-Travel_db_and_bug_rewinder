/**
 * In-memory mock of the backend.
 *
 * It keeps its own state (like a server would) so the whole PRD demo flow works
 * without a backend: crash → orders → time-travel → review → approve → re-run → undo.
 * Every function returns a Promise and mirrors one function in src/services/api.js.
 *
 * Testing helpers (add to the URL):
 *   ?mock=slow    slower responses, to see loading states
 *   ?mock=error   every request fails, to see error states
 *   ?mock=empty   the audit log is empty, to see empty states
 */
import { ApiError } from '../services/errors.js'
import {
  CRASH_TIME,
  STEPS_BEFORE_APPROVAL,
  buildRecoveryPlan,
  demoOrders,
  recoverySteps,
  scenarios,
  seedAuditLog,
  seedChangeLog,
  seedInventory,
} from './demoData.js'

const clone = (value) => structuredClone(value)

// ---------------------------------------------------------------------------
// Mock controls
// ---------------------------------------------------------------------------
function mockFlags() {
  if (typeof window === 'undefined') return new Set()
  const value = new URLSearchParams(window.location.search).get('mock') || ''
  return new Set(value.split(',').map((flag) => flag.trim()).filter(Boolean))
}

function delay(ms, signal) {
  const factor = mockFlags().has('slow') ? 4 : 1
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms * factor)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new ApiError('Request cancelled.', { code: 'ABORTED' }))
    })
  })
}

async function respond(ms, fn, signal) {
  await delay(ms, signal)
  if (mockFlags().has('error')) {
    throw new ApiError('The service is unavailable (simulated with ?mock=error).', { code: 'MOCK_ERROR', status: 503 })
  }
  return clone(fn())
}

// ---------------------------------------------------------------------------
// Mock clock: scripted demo times first, then a clock for later events
// ---------------------------------------------------------------------------
let clockSeconds = 2 * 3600 + 16 * 60 + 2 // 02:16:02
function tick(seconds = 7) {
  clockSeconds += seconds
  const h = String(Math.floor(clockSeconds / 3600) % 24).padStart(2, '0')
  const m = String(Math.floor(clockSeconds / 60) % 60).padStart(2, '0')
  const s = String(clockSeconds % 60).padStart(2, '0')
  return `${h}:${m}:${s}`
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let logId = 100
const nextLogId = () => `cl-${++logId}`

function healthyDb(scenarioId = 'warehouse-wipe') {
  return {
    scenarioId,
    dbVersion: 'v1.4.2',
    inventory: seedInventory.map((row) => ({ ...row, previousStock: row.stock, status: 'ok' })),
    orders: [],
    changeLog: clone(seedChangeLog),
    lastAction: null,
    incident: null,
    patched: false,
    recovery: null,
  }
}

let db = healthyDb()
let plans = {}
let preApplySnapshot = null
let audit = clone(seedAuditLog)
let recoveryCounter = 8

function crash() {
  db.inventory = db.inventory.map((row) => ({ ...row, previousStock: row.stock, stock: 0, status: 'zeroed' }))
  db.incident = { active: true, crashAt: CRASH_TIME, rowsTouched: db.inventory.length }
  db.lastAction = { label: `Warehouse sync · touched ${db.inventory.length} rows`, tone: 'danger', time: CRASH_TIME }
  db.changeLog.unshift({ id: nextLogId(), time: CRASH_TIME, label: 'CRASH: Warehouse Sync Executed', kind: 'crash' })
}

function placeDemoOrders() {
  for (const order of demoOrders) {
    const row = db.inventory.find((item) => item.sku === order.sku)
    const enough = row && row.stock >= order.qty
    if (enough) row.stock -= order.qty
    db.orders.push({ ...order, status: enough ? 'fulfilled' : 'oversold', afterCrash: Boolean(db.incident?.active) })
    db.changeLog.unshift({
      id: nextLogId(),
      time: order.placedAt,
      label: `Order ${order.id} placed`,
      kind: enough ? 'ok' : 'fail',
    })
  }
  db.lastAction = { label: `Placed orders ${demoOrders[0].id}–${demoOrders.at(-1).id}`, tone: 'info', time: demoOrders.at(-1).placedAt }
}

// The app opens in the incident state shown in the Console Incident design.
crash()
placeDemoOrders()

function snapshot() {
  return db
}

function addAudit(entry) {
  audit = [entry, ...audit.filter((item) => item.id !== entry.id)]
  return entry
}

// ---------------------------------------------------------------------------
// API mirror
// ---------------------------------------------------------------------------
export const mockServer = {
  getScenarios: () => respond(200, () => scenarios),

  getLiveSnapshot: () => respond(450, snapshot),

  triggerWarehouseSync: () =>
    respond(700, () => {
      if (db.patched) {
        const row = db.inventory.find((item) => item.sku === 'SKU-884')
        row.previousStock = row.stock
        row.stock += 2
        row.status = 'updated'
        const time = tick(31)
        db.lastAction = { label: 'Warehouse sync · touched 1 row', tone: 'success', time }
        db.changeLog.unshift({ id: nextLogId(), time, label: `Warehouse sync · ${row.sku} updated`, kind: 'ok' })
      } else {
        crash()
      }
      return snapshot()
    }),

  placeOrders: () =>
    respond(650, () => {
      if (db.orders.length) {
        throw new ApiError('Orders #1041–#1043 are already placed. Reset the demo to place them again.', {
          code: 'ORDERS_ALREADY_PLACED',
          status: 409,
        })
      }
      placeDemoOrders()
      return snapshot()
    }),

  async runTimeTravel({ prompt }, { onProgress, signal } = {}) {
    await delay(250, signal)
    if (mockFlags().has('error')) {
      throw new ApiError('The recovery agent is unavailable (simulated with ?mock=error).', { code: 'MOCK_ERROR', status: 503 })
    }
    const text = (prompt || '').trim()
    if (text.length < 12) {
      throw new ApiError(
        "Couldn't understand the request. Name the bad action and roughly when it happened, e.g. 'the warehouse sync at 02:14'.",
        { code: 'INTENT_UNPARSEABLE', status: 422 },
      )
    }
    if (!db.incident?.active) {
      throw new ApiError('No bad changes were found in the change log. Trigger the warehouse sync first.', {
        code: 'NOTHING_TO_RECOVER',
        status: 409,
      })
    }

    const logs = [
      ['Forking clone from snapshot #88f2', 'Clone branch cl-9942-alpha ready'],
      ['Reading change log after 02:14:06.900', `${5 + db.orders.filter((o) => o.afterCrash).length} changes found`],
      ['Rebuilding inventory on clone', 'Inventory restored on clone'],
      ['Checking orders against restored stock', db.orders.some((o) => o.afterCrash && o.id === '#1043') ? '1 conflict: #1043 exceeds SKU-881 stock' : 'No conflicts'],
      ['Planning merge of legitimate changes', 'Merge plan ready'],
      ['Diagnosing app/handlers.py', 'Patch proposed'],
      ['Re-running warehouse sync on clone', 'Touched 1 row (before patch: 5)'],
    ]

    for (let index = 0; index < STEPS_BEFORE_APPROVAL; index += 1) {
      onProgress?.({ stepIndex: index, step: recoverySteps[index], status: 'running', log: logs[index][0] })
      await delay(480, signal)
      onProgress?.({ stepIndex: index, step: recoverySteps[index], status: 'done', log: logs[index][1] })
    }

    const id = `R-${String(recoveryCounter).padStart(4, '0')}`
    const plan = buildRecoveryPlan({ id, prompt: text })
    const orderIds = new Set(db.orders.filter((order) => order.afterCrash).map((order) => order.id))
    plan.operations = plan.operations.filter((op) => op.operation !== 'REPLAY_ORDER' || orderIds.has(op.target.replace('order ', '')))
    const kept = plan.operations.filter((op) => op.decision !== 'discarded').length
    const conflicts = orderIds.has('#1043') ? 1 : 0
    plan.stats = { ...plan.stats, changes: kept + 5, kept, conflicts, conflictsResolved: conflicts }
    if (!conflicts) plan.conflict = null
    plan.createdAt = new Date().toISOString()
    plans[id] = plan
    return clone(plan)
  },

  approveRecovery: (planId) =>
    respond(1300, () => {
      const plan = plans[planId]
      if (!plan) throw new ApiError('This recovery plan no longer exists. Run time-travel again.', { code: 'PLAN_NOT_FOUND', status: 404 })
      preApplySnapshot = clone(db)
      recoveryCounter += 1

      // Restore pre-crash stock, then replay the kept orders following the plan.
      db.inventory = db.inventory.map((row) => ({ ...row, stock: row.previousStock, status: 'restored' }))
      db.orders = db.orders.map((order) => {
        if (!order.afterCrash) return order
        const row = db.inventory.find((item) => item.sku === order.sku)
        if (row.stock >= order.qty) {
          row.stock -= order.qty
          return { ...order, status: 'fulfilled' }
        }
        const fulfilled = row.stock
        row.stock = 0
        return { ...order, status: 'partial', fulfilledQty: fulfilled, backorderedQty: order.qty - fulfilled }
      })
      const appliedAt = tick(39)
      db.patched = true
      db.incident = null
      db.lastAction = { label: `Recovery ${plan.id} applied atomically`, tone: 'success', time: appliedAt }
      db.changeLog.unshift({ id: nextLogId(), time: appliedAt, label: `Recovery ${plan.id} applied`, kind: 'recovery' })
      db.recovery = { id: plan.id, status: 'live', appliedAt }

      const entry = addAudit({
        id: plan.id,
        status: 'applied',
        startedAt: plan.createdAt,
        scenario: scenarios.find((s) => s.id === db.scenarioId)?.name,
        prompt: plan.prompt,
        rewindRef: plan.targetCommit,
        delta: { kept: plan.stats.kept, discarded: plan.stats.discarded, conflicts: plan.stats.conflicts },
        rowsLost: plan.stats.legitimateRowsLost,
        risk: plan.risk.score,
        durationSec: Math.round((Date.now() - new Date(plan.createdAt).getTime()) / 100) / 10,
      })
      delete plans[planId]
      return {
        snapshot: db,
        recovery: {
          id: plan.id,
          appliedAt,
          smokeChecks: [
            { label: 'Inventory values restored to pre-crash state', passed: true },
            { label: 'Orders #1041–#1043 present', passed: true },
            { label: 'Patched handler loaded', passed: true },
          ],
        },
        auditEntry: entry,
      }
    }),

  discardRecovery: (planId) =>
    respond(500, () => {
      const plan = plans[planId]
      if (!plan) throw new ApiError('This recovery plan no longer exists.', { code: 'PLAN_NOT_FOUND', status: 404 })
      recoveryCounter += 1
      const entry = addAudit({
        id: plan.id,
        status: 'discarded',
        startedAt: plan.createdAt,
        scenario: scenarios.find((s) => s.id === db.scenarioId)?.name,
        prompt: plan.prompt,
        rewindRef: plan.targetCommit,
        delta: { kept: plan.stats.kept, discarded: plan.stats.discarded, conflicts: plan.stats.conflicts },
        rowsLost: 0,
        risk: plan.risk.score,
        durationSec: null,
      })
      delete plans[planId]
      return { auditEntry: entry }
    }),

  undoRecovery: (recoveryId) =>
    respond(1100, () => {
      if (!preApplySnapshot || db.recovery?.id !== recoveryId) {
        throw new ApiError('Only the latest applied recovery can be undone.', { code: 'UNDO_NOT_AVAILABLE', status: 409 })
      }
      const undoneAt = tick(23)
      const changeLog = db.changeLog
      db = preApplySnapshot
      db.changeLog = [{ id: nextLogId(), time: undoneAt, label: `Recovery ${recoveryId} undone`, kind: 'undo' }, ...changeLog]
      db.lastAction = { label: `Recovery ${recoveryId} undone`, tone: 'info', time: undoneAt }
      db.recovery = null
      preApplySnapshot = null
      const entry = audit.find((item) => item.id === recoveryId)
      if (entry) entry.status = 'undone'
      return { snapshot: db, auditEntry: entry }
    }),

  resetDemo: (scenarioId) =>
    respond(600, () => {
      const target = scenarios.find((s) => s.id === scenarioId) || scenarios[0]
      if (!target.available) throw new ApiError(`${target.name} is not available yet.`, { code: 'SCENARIO_UNAVAILABLE', status: 400 })
      db = healthyDb(target.id)
      plans = {}
      preApplySnapshot = null
      clockSeconds = 2 * 3600 + 16 * 60 + 2
      return snapshot()
    }),

  getAuditLog: ({ search = '', status = '', scenario = '', page = 1, pageSize = 5 } = {}) =>
    respond(500, () => {
      if (mockFlags().has('empty')) return { items: [], total: 0, page: 1, pageSize }
      const query = search.trim().toLowerCase()
      const filtered = audit.filter((entry) => {
        if (status && entry.status !== status) return false
        if (scenario && entry.scenario !== scenario) return false
        if (!query) return true
        return [entry.id, entry.prompt, entry.scenario, entry.rewindRef].some((field) => field?.toLowerCase().includes(query))
      })
      const start = (page - 1) * pageSize
      return { items: filtered.slice(start, start + pageSize), total: filtered.length, page, pageSize }
    }),

  getAuditSummary: () =>
    respond(350, () => {
      if (mockFlags().has('empty')) return { totalRecoveries: 0, today: 0, successRate: null, targetSuccessRate: 99 }
      const todayKey = new Date().toDateString()
      const finished = audit.filter((entry) => entry.status !== 'discarded')
      const succeeded = finished.filter((entry) => entry.status !== 'failed')
      return {
        totalRecoveries: audit.length,
        today: audit.filter((entry) => new Date(entry.startedAt).toDateString() === todayKey).length,
        successRate: finished.length ? Math.round((succeeded.length / finished.length) * 1000) / 10 : null,
        targetSuccessRate: 99,
      }
    }),

  getAuditEntry: (id) =>
    respond(300, () => {
      const entry = audit.find((item) => item.id === id)
      if (!entry) throw new ApiError(`Recovery ${id} was not found.`, { code: 'NOT_FOUND', status: 404 })
      return entry
    }),
}
