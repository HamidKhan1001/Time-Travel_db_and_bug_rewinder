/**
 * API integration layer — the ONLY place the UI talks to the backend.
 *
 * Components and pages never call fetch() or import mock data directly.
 * They call these functions (through src/context/DemoContext.jsx).
 *
 * Mock mode (default):   VITE_USE_MOCKS unset or true -> src/mocks/mockServer.js
 * Real backend:          VITE_USE_MOCKS=false (npm run dev:live) -> src/services/backend.js,
 *                        which calls the Python server and adapts its JSON (src/services/adapters.js).
 */
import { USE_MOCKS } from './config.js'
import { mockServer } from '../mocks/mockServer.js'
import { backend } from './backend.js'

const impl = USE_MOCKS ? mockServer : backend

// --- Scenarios --------------------------------------------------------------

/** List incident scenarios for the scenario selector. → Scenario[] */
export const getScenarios = () => impl.getScenarios()

// --- Live database ------------------------------------------------------------

/** Current live database state (inventory, orders, change log). → LiveSnapshot */
export const getLiveSnapshot = (scenarioId) => impl.getLiveSnapshot(scenarioId)

/** PRD §5 step 1/6: run the warehouse sync (the crash action). → LiveSnapshot */
export const triggerWarehouseSync = (scenarioId) => impl.triggerWarehouseSync(scenarioId)

/** PRD §5 step 2: place the 3 demo orders. → LiveSnapshot */
export const placeOrders = (scenarioId) => impl.placeOrders(scenarioId)

/** Restore the seed data for a scenario (PRD §12 "Reset button"). → LiveSnapshot */
export const resetDemo = (scenarioId) => impl.resetDemo(scenarioId)

// --- Recovery -----------------------------------------------------------------

/**
 * PRD §5 step 3: run time-travel on a clone.
 * Streams progress through onProgress({ stepIndex, status: 'running'|'done', log })
 * and resolves with the RecoveryPlan.
 */
export const runTimeTravel = (input, options) => impl.runTimeTravel(input, options)

/** PRD §5 step 5: approve and apply the plan atomically. → { snapshot, recovery, auditEntry } */
export const approveRecovery = (planId) => impl.approveRecovery(planId)

/** Throw away a plan without touching live data. → { auditEntry } */
export const discardRecovery = (planId) => impl.discardRecovery(planId)

/** PRD §5 step 7: undo an applied recovery. → { snapshot, auditEntry } */
export const undoRecovery = (recoveryId) => impl.undoRecovery(recoveryId)

// --- Audit log ------------------------------------------------------------------

/** PRD §6 "Audit log of every recovery". → { items: AuditEntry[], total, page, pageSize } */
export const getAuditLog = (query) => impl.getAuditLog(query)

/** Header metrics on the Audit log page. → { totalRecoveries, today, successRate, targetSuccessRate } */
export const getAuditSummary = () => impl.getAuditSummary()

/** One recovery record for the detail drawer. → AuditEntry */
export const getAuditEntry = (id) => impl.getAuditEntry(id)
