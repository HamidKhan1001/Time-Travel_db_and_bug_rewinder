/**
 * API integration layer — the ONLY place the UI talks to the backend.
 *
 * Components and pages never call fetch() or import mock data directly.
 * They call these functions (through src/context/DemoContext.jsx).
 *
 * Today every function returns mock data from src/mocks/mockServer.js.
 * To connect the backend:
 *   1. Set VITE_USE_MOCKS=false and VITE_API_BASE_URL in .env.local
 *   2. Replace each `notConnected(...)` call below with a real request, e.g.
 *        return request('<path agreed with backend>', { method: 'POST', body: { ... } })
 *   3. Keep the return shapes documented in docs/BACKEND_INTEGRATION.md,
 *      or adapt them here so the components do not need to change.
 *
 * No endpoint paths are defined yet on purpose: they have not been agreed with
 * the backend team (PRD §10, hour 0–1 "Agree on API shapes").
 */
import { USE_MOCKS } from './config.js'
import { ApiError } from './errors.js'
import { mockServer } from '../mocks/mockServer.js'
// import { request } from './httpClient.js'  // use when the backend is connected

function notConnected(name) {
  return Promise.reject(
    new ApiError(`${name}() is not connected to the backend yet. See docs/BACKEND_INTEGRATION.md.`, {
      code: 'NOT_CONNECTED',
    }),
  )
}

// --- Scenarios --------------------------------------------------------------

/** List incident scenarios for the scenario selector. → Scenario[] */
export function getScenarios() {
  if (USE_MOCKS) return mockServer.getScenarios()
  return notConnected('getScenarios')
}

// --- Live database ------------------------------------------------------------

/** Current live database state (inventory, orders, change log). → LiveSnapshot */
export function getLiveSnapshot(scenarioId) {
  if (USE_MOCKS) return mockServer.getLiveSnapshot(scenarioId)
  return notConnected('getLiveSnapshot')
}

/** PRD §5 step 1/6: run the warehouse sync (the crash action). → LiveSnapshot */
export function triggerWarehouseSync(scenarioId) {
  if (USE_MOCKS) return mockServer.triggerWarehouseSync(scenarioId)
  return notConnected('triggerWarehouseSync')
}

/** PRD §5 step 2: place the 3 demo orders. → LiveSnapshot */
export function placeOrders(scenarioId) {
  if (USE_MOCKS) return mockServer.placeOrders(scenarioId)
  return notConnected('placeOrders')
}

/** Restore the seed data for a scenario (PRD §12 "Reset button"). → LiveSnapshot */
export function resetDemo(scenarioId) {
  if (USE_MOCKS) return mockServer.resetDemo(scenarioId)
  return notConnected('resetDemo')
}

// --- Recovery -----------------------------------------------------------------

/**
 * PRD §5 step 3: run time-travel on a clone.
 * Streams progress through onProgress({ stepIndex, step, status: 'running'|'done', log })
 * (PRD §6 "Streaming progress in the UI") and resolves with the RecoveryPlan.
 * The backend may use SSE or WebSockets; adapt it to the onProgress callback here.
 */
export function runTimeTravel({ scenarioId, prompt }, { onProgress, signal } = {}) {
  if (USE_MOCKS) return mockServer.runTimeTravel({ scenarioId, prompt }, { onProgress, signal })
  return notConnected('runTimeTravel')
}

/** PRD §5 step 5: approve and apply the plan atomically. → { snapshot, recovery, auditEntry } */
export function approveRecovery(planId) {
  if (USE_MOCKS) return mockServer.approveRecovery(planId)
  return notConnected('approveRecovery')
}

/** Throw away a plan without touching live data. → { auditEntry } */
export function discardRecovery(planId) {
  if (USE_MOCKS) return mockServer.discardRecovery(planId)
  return notConnected('discardRecovery')
}

/** PRD §5 step 7: undo an applied recovery. → { snapshot, auditEntry } */
export function undoRecovery(recoveryId) {
  if (USE_MOCKS) return mockServer.undoRecovery(recoveryId)
  return notConnected('undoRecovery')
}

// --- Audit log ------------------------------------------------------------------

/** PRD §6 "Audit log of every recovery". → { items: AuditEntry[], total, page, pageSize } */
export function getAuditLog({ search, status, scenario, page, pageSize } = {}) {
  if (USE_MOCKS) return mockServer.getAuditLog({ search, status, scenario, page, pageSize })
  return notConnected('getAuditLog')
}

/** Header metrics on the Audit log page. → { totalRecoveries, today, successRate, targetSuccessRate } */
export function getAuditSummary() {
  if (USE_MOCKS) return mockServer.getAuditSummary()
  return notConnected('getAuditSummary')
}

/** One recovery record for the detail drawer. → AuditEntry */
export function getAuditEntry(id) {
  if (USE_MOCKS) return mockServer.getAuditEntry(id)
  return notConnected('getAuditEntry')
}
