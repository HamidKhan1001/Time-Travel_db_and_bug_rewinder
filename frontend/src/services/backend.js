/**
 * Real backend client (the Python server in /server.py). Used when VITE_USE_MOCKS=false.
 * Keeps the small amount of client-side state the API does not provide (last action,
 * previous stock levels, the local change-log entries for recoveries).
 */
import { request } from './httpClient.js'
import { ApiError } from './errors.js'
import {
  SCENARIOS,
  SCENARIO_NAME,
  fmtTime,
  sessionError,
  stepsFromSession,
  toPlan,
  toSmokeChecks,
  toSnapshot,
} from './adapters.js'

const POLL_MS = 350
const MAX_WAIT_MS = 120_000

const memory = {
  prevStocks: {},
  lastAction: null,
  recovery: null,
  localLog: [],
}

const resetMemory = () => {
  memory.prevStocks = {}
  memory.lastAction = null
  memory.recovery = null
  memory.localLog = []
}

const nowSeconds = () => Date.now() / 1000

async function snapshot(scenarioId = 'warehouse-wipe') {
  const state = await request('/api/state')
  const data = toSnapshot(state, { ...memory, scenarioId })
  // Remember stock levels so the next snapshot can show what changed.
  for (const row of data.inventory) memory.prevStocks[row.sku] = row.stock
  return data
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new ApiError('Request cancelled.', { code: 'ABORTED' }))
    })
  })
}

export const backend = {
  getScenarios: async () => SCENARIOS,

  getLiveSnapshot: (scenarioId) => snapshot(scenarioId),

  async triggerWarehouseSync(scenarioId) {
    await snapshot(scenarioId) // capture current stock as "previous"
    const result = await request('/api/demo/crash', { method: 'POST', body: {} })
    const rows = result.updated_rows
    memory.lastAction = {
      label: `Warehouse sync · touched ${rows} row${rows === 1 ? '' : 's'}`,
      tone: rows > 1 ? 'danger' : 'success',
      time: fmtTime(nowSeconds()),
    }
    return snapshot(scenarioId)
  },

  async placeOrders(scenarioId) {
    const before = await request('/api/state')
    if ((before.orders || []).some((o) => o.id >= 1041)) {
      throw new ApiError('Orders #1041–#1043 are already placed. Reset the demo to place them again.', {
        code: 'ORDERS_ALREADY_PLACED',
        status: 409,
      })
    }
    const result = await request('/api/demo/orders', { method: 'POST', body: {} })
    const ids = result.orders.map((o) => o.order_id)
    memory.lastAction = { label: `Placed orders #${ids[0]}–#${ids.at(-1)}`, tone: 'info', time: fmtTime(nowSeconds()) }
    return snapshot(scenarioId)
  },

  async resetDemo(scenarioId) {
    const target = SCENARIOS.find((s) => s.id === scenarioId) || SCENARIOS[0]
    if (!target.available) throw new ApiError(`${target.name} is not available yet.`, { code: 'SCENARIO_UNAVAILABLE', status: 400 })
    await request('/api/demo/reset', { method: 'POST', body: {} })
    resetMemory()
    return snapshot(target.id)
  },

  async runTimeTravel({ prompt }, { onProgress, signal } = {}) {
    const text = (prompt || '').trim()
    if (text.length < 12) {
      throw new ApiError(
        "Couldn't understand the request. Name the bad action and roughly when it happened, e.g. 'Take the business back to 2 minutes ago'.",
        { code: 'INTENT_UNPARSEABLE', status: 422 },
      )
    }
    const { id } = await request('/api/rewind', { method: 'POST', body: { prompt: text }, signal })
    const sent = new Map()
    const started = Date.now()
    for (;;) {
      const session = await request(`/api/session/${id}`, { signal })
      for (const step of stepsFromSession(session)) {
        const key = `${step.status}|${step.log}`
        if (step.status !== 'pending' && sent.get(step.stepIndex) !== key) {
          sent.set(step.stepIndex, key)
          onProgress?.(step)
        }
      }
      if (session.phase === 'awaiting_approval') return toPlan(session)
      if (session.phase === 'error') throw new ApiError(sessionError(session).message, { code: sessionError(session).code, status: 422 })
      if (Date.now() - started > MAX_WAIT_MS) throw new ApiError('The recovery agent took too long to respond.', { code: 'TIMEOUT' })
      await sleep(POLL_MS, signal)
    }
  },

  async approveRecovery(planId) {
    let session
    try {
      session = await request(`/api/session/${planId}/approve`, { method: 'POST', body: {} })
    } catch (error) {
      if (error.status === 404) throw new ApiError('This recovery plan no longer exists. Run time-travel again.', { code: 'PLAN_NOT_FOUND', status: 404 })
      throw error
    }
    const appliedAt = fmtTime(nowSeconds())
    memory.recovery = { id: session.id, status: 'live', appliedAt }
    memory.lastAction = { label: `Recovery ${session.id} applied atomically`, tone: 'success', time: appliedAt }
    memory.localLog.push({ ts: nowSeconds(), label: `Recovery ${session.id} applied`, kind: 'recovery' })
    return {
      snapshot: await snapshot(),
      recovery: { id: session.id, appliedAt, smokeChecks: toSmokeChecks(session) },
      auditEntry: await backend.getAuditEntry(session.id).catch(() => null),
    }
  },

  async discardRecovery(planId) {
    try {
      await request(`/api/session/${planId}/discard`, { method: 'POST', body: {} })
    } catch (error) {
      if (error.status === 404) throw new ApiError('This recovery plan no longer exists.', { code: 'PLAN_NOT_FOUND', status: 404 })
      throw error
    }
    return { auditEntry: await backend.getAuditEntry(planId).catch(() => null) }
  },

  async undoRecovery(recoveryId) {
    try {
      await request(`/api/session/${recoveryId}/undo`, { method: 'POST', body: {} })
    } catch (error) {
      if (error.status === 400) throw new ApiError('Only the latest applied recovery can be undone.', { code: 'UNDO_NOT_AVAILABLE', status: 409 })
      throw error
    }
    const undoneAt = fmtTime(nowSeconds())
    memory.recovery = null
    memory.lastAction = { label: `Recovery ${recoveryId} undone`, tone: 'info', time: undoneAt }
    memory.localLog.push({ ts: nowSeconds(), label: `Recovery ${recoveryId} undone`, kind: 'undo' })
    return { snapshot: await snapshot(), auditEntry: await backend.getAuditEntry(recoveryId).catch(() => null) }
  },

  getAuditLog({ search = '', status = '', scenario = '', page = 1, pageSize = 5 } = {}) {
    const q = new URLSearchParams({ search, status, scenario, page: String(page), pageSize: String(pageSize) })
    return request(`/api/audit?${q}`)
  },

  getAuditSummary: () => request('/api/audit/summary'),

  getAuditEntry: (id) => request(`/api/audit/${encodeURIComponent(id)}`),
}

export { SCENARIO_NAME }
