import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../services/api.js'
import { errorMessage } from '../services/errors.js'
import { recoverySteps } from '../constants/recoverySteps.js'
import { useToast } from './ToastContext.jsx'

/**
 * App state shared by the Console, Review and Audit log screens.
 * All data comes from src/services/api.js — this file holds no data itself.
 *
 * recovery.status:
 *   idle      no recovery in progress
 *   running   agent is working on the clone (streaming progress)
 *   review    plan ready, waiting for human approval (Console Review screen)
 *   live      plan applied to the live database, can be undone
 *   failed    the run failed (error shown in the composer)
 */
const DemoContext = createContext(null)

const freshSteps = () => recoverySteps.map((step) => ({ ...step, status: 'pending', log: '' }))
const idleRecovery = () => ({ status: 'idle', plan: null, steps: freshSteps(), error: null, applied: null, startedAt: null })

export function DemoProvider({ children }) {
  const { notify } = useToast()
  const [scenarios, setScenarios] = useState({ data: [], status: 'loading', error: null })
  const [scenarioId, setScenarioId] = useState('warehouse-wipe')
  const [snapshot, setSnapshot] = useState({ data: null, status: 'loading', error: null })
  const [recovery, setRecovery] = useState(idleRecovery)
  const [pending, setPending] = useState({})
  const [auditCount, setAuditCount] = useState(null)
  const abortRef = useRef(null)

  const withPending = useCallback(async (key, fn) => {
    setPending((value) => ({ ...value, [key]: true }))
    try {
      return await fn()
    } finally {
      setPending((value) => ({ ...value, [key]: false }))
    }
  }, [])

  const refreshAuditCount = useCallback(async () => {
    try {
      const summary = await api.getAuditSummary()
      setAuditCount(summary.totalRecoveries)
    } catch {
      setAuditCount(null)
    }
  }, [])

  const loadSnapshot = useCallback(async () => {
    setSnapshot((value) => ({ ...value, status: 'loading', error: null }))
    try {
      const data = await api.getLiveSnapshot(scenarioId)
      setSnapshot({ data, status: 'ready', error: null })
    } catch (error) {
      setSnapshot((value) => ({ ...value, status: 'error', error: errorMessage(error) }))
    }
  }, [scenarioId])

  const loadScenarios = useCallback(async () => {
    setScenarios((value) => ({ ...value, status: 'loading', error: null }))
    try {
      setScenarios({ data: await api.getScenarios(), status: 'ready', error: null })
    } catch (error) {
      setScenarios((value) => ({ ...value, status: 'error', error: errorMessage(error) }))
    }
  }, [])

  useEffect(() => {
    loadScenarios()
    loadSnapshot()
    refreshAuditCount()
    // Run once on start; later updates come from actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // --- Live database actions ---------------------------------------------------
  const triggerWarehouseSync = useCallback(
    () =>
      withPending('sync', async () => {
        try {
          const data = await api.triggerWarehouseSync(scenarioId)
          setSnapshot({ data, status: 'ready', error: null })
          notify(data.lastAction?.label || 'Warehouse sync finished', { tone: data.patched ? 'success' : 'danger' })
        } catch (error) {
          notify(errorMessage(error), { tone: 'danger' })
        }
      }),
    [notify, scenarioId, withPending],
  )

  const placeOrders = useCallback(
    () =>
      withPending('orders', async () => {
        try {
          const data = await api.placeOrders(scenarioId)
          setSnapshot({ data, status: 'ready', error: null })
          notify('Orders #1041–#1043 placed', { tone: 'info' })
        } catch (error) {
          notify(errorMessage(error), { tone: 'danger' })
        }
      }),
    [notify, scenarioId, withPending],
  )

  const resetDemo = useCallback(
    (targetScenarioId = scenarioId) =>
      withPending('reset', async () => {
        abortRef.current?.abort()
        try {
          const data = await api.resetDemo(targetScenarioId)
          setScenarioId(targetScenarioId)
          setSnapshot({ data, status: 'ready', error: null })
          setRecovery(idleRecovery())
          notify('Demo reset')
          return true
        } catch (error) {
          notify(errorMessage(error), { tone: 'danger' })
          return false
        }
      }),
    [notify, scenarioId, withPending],
  )

  // --- Recovery actions ----------------------------------------------------------
  const runTimeTravel = useCallback(
    async (prompt) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setRecovery({ ...idleRecovery(), status: 'running', startedAt: Date.now() })
      try {
        const plan = await api.runTimeTravel(
          { scenarioId, prompt },
          {
            signal: controller.signal,
            onProgress: ({ stepIndex, status, log }) =>
              setRecovery((value) => ({
                ...value,
                steps: value.steps.map((step, index) => (index === stepIndex ? { ...step, status, log } : step)),
              })),
          },
        )
        setRecovery((value) => ({ ...value, status: 'review', plan }))
        return plan
      } catch (error) {
        if (error.code === 'ABORTED') return null
        setRecovery((value) => ({
          ...value,
          status: 'failed',
          error: { message: errorMessage(error), code: error.code },
          steps: value.steps.map((step) => (step.status === 'running' ? { ...step, status: 'failed' } : step)),
        }))
        return null
      }
    },
    [scenarioId],
  )

  const cancelRun = useCallback(() => {
    abortRef.current?.abort()
    setRecovery(idleRecovery())
  }, [])

  const dismissRecoveryError = useCallback(() => setRecovery(idleRecovery()), [])

  const approveRecovery = useCallback(
    () =>
      withPending('approve', async () => {
        try {
          const result = await api.approveRecovery(recovery.plan.id)
          setSnapshot({ data: result.snapshot, status: 'ready', error: null })
          setRecovery((value) => ({
            ...value,
            status: 'live',
            applied: result.recovery,
            steps: value.steps.map((step) => ({ ...step, status: 'done' })),
          }))
          refreshAuditCount()
          notify('Recovery applied to the live database')
          return { ok: true }
        } catch (error) {
          return { ok: false, error: errorMessage(error) }
        }
      }),
    [notify, recovery.plan, refreshAuditCount, withPending],
  )

  const discardRecovery = useCallback(
    () =>
      withPending('discard', async () => {
        try {
          await api.discardRecovery(recovery.plan.id)
          setRecovery(idleRecovery())
          refreshAuditCount()
          notify('Plan discarded. Nothing was written to the live database.', { tone: 'info' })
          return { ok: true }
        } catch (error) {
          return { ok: false, error: errorMessage(error) }
        }
      }),
    [notify, recovery.plan, refreshAuditCount, withPending],
  )

  const undoRecovery = useCallback(
    () =>
      withPending('undo', async () => {
        try {
          const result = await api.undoRecovery(recovery.applied.id)
          setSnapshot({ data: result.snapshot, status: 'ready', error: null })
          setRecovery(idleRecovery())
          refreshAuditCount()
          notify('Recovery undone', { tone: 'info' })
          return { ok: true }
        } catch (error) {
          return { ok: false, error: errorMessage(error) }
        }
      }),
    [notify, recovery.applied, refreshAuditCount, withPending],
  )

  const value = useMemo(
    () => ({
      scenarios,
      scenarioId,
      snapshot,
      recovery,
      pending,
      auditCount,
      loadSnapshot,
      loadScenarios,
      triggerWarehouseSync,
      placeOrders,
      resetDemo,
      runTimeTravel,
      cancelRun,
      dismissRecoveryError,
      approveRecovery,
      discardRecovery,
      undoRecovery,
      refreshAuditCount,
    }),
    [
      scenarios,
      scenarioId,
      snapshot,
      recovery,
      pending,
      auditCount,
      loadSnapshot,
      loadScenarios,
      triggerWarehouseSync,
      placeOrders,
      resetDemo,
      runTimeTravel,
      cancelRun,
      dismissRecoveryError,
      approveRecovery,
      discardRecovery,
      undoRecovery,
      refreshAuditCount,
    ],
  )

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>
}

export function useDemo() {
  const context = useContext(DemoContext)
  if (!context) throw new Error('useDemo must be used inside <DemoProvider>')
  return context
}
