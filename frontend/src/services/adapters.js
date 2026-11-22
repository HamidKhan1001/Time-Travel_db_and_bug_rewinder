/**
 * Pure functions that translate the Python backend's JSON into the shapes the UI reads
 * (see docs/BACKEND_INTEGRATION.md). No fetch, no React, no globals, so they are easy to test:
 *   node --test src/services/adapters.test.js
 */

export const SCENARIO_NAME = 'Warehouse Wipe (Stock 0)'

export const SCENARIOS = [
  {
    id: 'warehouse-wipe',
    code: 'S01',
    name: SCENARIO_NAME,
    description:
      'A warehouse sync handler runs UPDATE inventory SET stock = ? with no WHERE clause and wipes every SKU while customers keep ordering.',
    available: true,
  },
  {
    id: 'scenario-2',
    code: 'S02',
    name: 'Second scenario (not exposed yet)',
    description: 'A second crash scenario exists in the backend tests but is not reachable through the API yet.',
    available: false,
  },
]

const pad = (n) => String(n).padStart(2, '0')

/** Unix seconds -> 'HH:MM:SS' in local time. */
export function fmtTime(ts) {
  if (ts == null) return ''
  const d = new Date(ts * 1000)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function fmtTimeMs(ts) {
  if (ts == null) return ''
  const d = new Date(ts * 1000)
  return `${fmtTime(ts)}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

const lastWord = (name = '') => name.trim().split(/\s+/).pop() || 'Item'

// ---------------------------------------------------------------------------
// Live snapshot  (GET /api/state)
// ---------------------------------------------------------------------------

/**
 * @param state  response of GET /api/state
 * @param ctx    { prevStocks: {sku: n}, lastAction, recovery, localLog: [{ts,label,kind}], scenarioId }
 */
export function toSnapshot(state, ctx = {}) {
  const { prevStocks = {}, lastAction = null, recovery = null, localLog = [], scenarioId = 'warehouse-wipe' } = ctx
  const incidentRow = state.incident || null
  const patched = Boolean(state.patched)
  // The crash stays in the query log after a fix, so "active" means: crash seen and not yet fixed.
  const incidentActive = Boolean(incidentRow) && !patched

  const inventory = (state.inventory?.sample || []).map((row) => {
    const prev = prevStocks[row.sku]
    let status = 'ok'
    if (row.stock === 0 && incidentActive) status = 'zeroed'
    else if (prev !== undefined && prev !== row.stock) status = recovery ? 'restored' : 'updated'
    return {
      sku: row.sku,
      name: row.name,
      category: lastWord(row.name),
      stock: row.stock,
      previousStock: prev ?? row.stock,
      limited: /limited/i.test(row.name),
      status,
    }
  })

  const crashTs = incidentRow?.ts ?? null
  const orders = (state.orders || [])
    .filter((o) => crashTs != null && o.created_at >= crashTs)
    .sort((a, b) => a.id - b.id)
    .map((o) => {
      const items = o.items || []
      const qty = items.reduce((sum, it) => sum + it.qty, 0)
      const backorder = o.status === 'backorder'
      return {
        id: `#${o.id}`,
        sku: items.length > 1 ? `${items[0].sku} +${items.length - 1} more` : items[0]?.sku || '',
        item: items.map((it) => it.name).join(', '),
        qty,
        user: o.customer || `customer ${o.customer_id}`,
        placedAt: fmtTime(o.created_at),
        status: backorder ? 'partial' : 'fulfilled',
        afterCrash: true,
      }
    })

  const log = []
  if (incidentRow) {
    log.push({ ts: incidentRow.ts, label: `CRASH: Warehouse Sync Executed · touched ${incidentRow.rows_affected} rows`, kind: 'crash' })
  }
  for (const o of state.orders || []) {
    if (crashTs != null && o.created_at >= crashTs) log.push({ ts: o.created_at, label: `Order #${o.id} placed`, kind: 'ok' })
  }
  for (const entry of localLog) log.push(entry)
  const changeLog = log
    .sort((a, b) => b.ts - a.ts)
    .map((entry, index) => ({ id: `cl-${index}-${Math.round(entry.ts)}`, time: fmtTime(entry.ts), label: entry.label, kind: entry.kind }))

  const derivedAction = incidentActive
    ? { label: `Warehouse sync · touched ${incidentRow.rows_affected} rows`, tone: 'danger', time: fmtTime(crashTs) }
    : null

  return {
    scenarioId,
    dbVersion: 'live',
    inventory,
    orders,
    changeLog,
    lastAction: lastAction || derivedAction,
    incident: incidentActive ? { active: true, crashAt: fmtTime(crashTs), rowsTouched: incidentRow.rows_affected } : null,
    patched,
    recovery,
  }
}

// ---------------------------------------------------------------------------
// Recovery plan  (GET /api/session/<id>)
// ---------------------------------------------------------------------------

/** Unified diff text -> { file, hunk, lines: [{type, text}] } */
export function parseDiff(diff) {
  if (!diff) return null
  const out = { file: 'app/handlers.py', hunk: '', lines: [] }
  for (const raw of diff.split('\n')) {
    if (raw.startsWith('+++ ')) out.file = raw.slice(4).replace(/^b\//, '')
    else if (raw.startsWith('--- ')) continue
    else if (raw.startsWith('@@')) {
      if (!out.hunk) out.hunk = raw
    } else if (out.hunk) {
      if (raw === '' ) continue
      const type = raw.startsWith('+') ? 'add' : raw.startsWith('-') ? 'del' : 'context'
      out.lines.push({ type, text: raw })
    }
  }
  return out
}

function firstInt(text) {
  const match = /(\d+)/.exec(text || '')
  return match ? Number(match[1]) : null
}

function orderItemsText(order) {
  return order.items.map(([sku, qty]) => `${sku} ×${qty}`).join(', ')
}

export function toPlan(session) {
  const plan = session.plan || {}
  const delta = session.delta || { orders: [] }
  const parsed = session.parsed || {}
  const patchRaw = session.patch || null
  const preview = session.recovery_preview || {}
  const rows = preview.rows || []
  const conflicts = plan.conflicts || []
  const conflictByOrder = new Map(conflicts.map((c) => [c.order_id, c]))
  const dryOk = plan.dry_run_ok !== false

  const orderOps = (delta.orders || []).map((order) => {
    const conflict = conflictByOrder.get(order.id)
    return {
      id: `op-${order.id}`,
      operation: 'REPLAY_ORDER',
      target: `order #${order.id}`,
      decision: conflict ? 'resolved' : 'kept',
      reason: conflict
        ? conflict.reason || conflict.detail
        : 'Valid transaction placed after the crash; replayed onto the restored data.',
      details: [
        { label: 'Order', value: `#${order.id} · ${orderItemsText(order)} · customer ${order.customer_id}` },
        { label: 'Placed', value: fmtTime(order.created_at) },
        { label: 'Phase', value: order.phase },
      ],
    }
  })

  const wipedRows = plan.zero_before ?? 0
  const wipeOp = {
    id: 'op-sync-wipe',
    operation: 'SYNC_WIPE',
    target: 'db.inventory',
    targetNote: `${wipedRows.toLocaleString?.() ?? wipedRows} rows`,
    decision: 'discarded',
    reason: session.patch?.found
      ? `Unscoped write detected: ${session.patch.incident_sql}. Reversed on the clone and restored from the change log.`
      : 'Unscoped bulk write reversed on the clone and restored from the change log.',
    details: rows
      .filter((r) => r.table === 'inventory')
      .slice(0, 8)
      .map((r) => ({ label: r.key, value: `stock ${r.before} → ${r.after} (restored)` })),
  }

  const first = conflicts[0]
  let conflict = null
  if (first) {
    const order = (delta.orders || []).find((o) => o.id === first.order_id)
    const requested = order?.items.find(([sku]) => sku === first.sku)?.[1] ?? null
    conflict = {
      item: first.sku,
      sku: first.sku,
      order: `#${first.order_id}`,
      requestedQty: requested,
      availableQty: requested != null ? requested - (first.shortfall || 0) : null,
      strategy: first.reason || first.detail,
    }
  }

  const diff = patchRaw?.found ? parseDiff(patchRaw.diff) : null
  const patchTests = patchRaw?.tests || []
  const patch = diff
    ? {
        ...diff,
        verification: {
          passed: Boolean(patchRaw.patch_ok),
          rowsTouchedBefore: patchRaw.rows_affected ?? null,
          rowsTouchedAfter: firstInt(patchTests[0]?.detail),
        },
      }
    : null

  const kept = plan.orders_preserved ?? orderOps.length
  const checks = (plan.dry_run || []).length
  const passedChecks = (plan.dry_run || []).filter((c) => c.ok).length + patchTests.filter((t) => t.ok).length

  const guardrailAdjusted = (session.events || []).some((e) => e.agent === 'Guardrails' && /Snapping/.test(e.msg))

  return {
    id: session.id,
    prompt: session.prompt,
    createdAt: new Date((session.timeline?.now ?? Date.now() / 1000) * 1000).toISOString(),
    cloneBranch: `branch_${session.id}`,
    cloneRef: `rewind@${fmtTime(parsed.target_ts)}`,
    targetCommit: `@${fmtTime(parsed.target_ts)}`,
    rewindTarget: fmtTimeMs(parsed.target_ts),
    crashAt: fmtTimeMs(parsed.incident_ts),
    guardrailAdjusted,
    parsedBy: parsed.source === 'regex' || !parsed.source ? 'rule-based' : 'ai',
    stats: {
      changes: kept + wipedRows,
      kept,
      discarded: wipedRows,
      conflicts: conflicts.length,
      conflictsResolved: conflicts.length,
      // The merge is dry-run on a clone and checked for FK/negative-stock violations before approval.
      legitimateRowsLost: dryOk ? 0 : null,
    },
    risk: { score: (plan.risk?.score ?? 0) / 100, label: plan.risk?.label, factors: plan.risk?.factors || [] },
    confidence: parsed.confidence ?? 1,
    verifiedSuites: passedChecks,
    totalSuites: checks + patchTests.length,
    dryRunOk: dryOk,
    operations: [...orderOps, wipeOp],
    conflict,
    patch,
    patchNote: patch ? null : patchRaw?.explanation || (session.parsed?.remediate === false ? 'No code fix was requested.' : null),
    timings: session.timings || null,
  }
}

// ---------------------------------------------------------------------------
// Progress  (phase of GET /api/session/<id> -> the 7 UI steps)
// ---------------------------------------------------------------------------

export const STEP_COUNT = 7

const RUNNING_STEPS = {
  starting: [0],
  parsing: [0],
  branching: [0],
  extracting_delta: [1],
  planning: [2, 3, 4],
  diagnosing: [5, 6],
}

function stepLog(index, session) {
  const { branch, delta, plan, patch } = session
  switch (index) {
    case 0:
      return branch ? `Reversed ${branch.events_reversed?.toLocaleString?.() ?? branch.events_reversed} logged changes on a clone in ${branch.ms} ms` : ''
    case 1:
      return delta ? `${delta.post_crash} order(s) after the crash, ${delta.pre_crash} before` : ''
    case 2:
      return plan ? `Restore ${plan.restored_rows?.toLocaleString?.() ?? plan.restored_rows} inventory rows` : ''
    case 3:
      return plan ? `${plan.conflicts.length} conflict(s) found and resolved` : ''
    case 4:
      return plan ? `Merge plan ready · dry run ${plan.dry_run_ok ? 'passed' : 'FAILED'}` : ''
    case 5:
      if (!patch) return 'No code fix requested'
      return patch.found ? `Root cause: ${patch.incident_sql}` : 'No offending statement found in the source'
    case 6: {
      const tests = patch?.tests || []
      if (!patch || !tests.length) return 'Skipped'
      return `${tests.filter((t) => t.ok).length}/${tests.length} patch tests passed on a throwaway clone`
    }
    default:
      return ''
  }
}

/**
 * Current state of all 7 steps for a session snapshot.
 * @returns {{stepIndex:number, status:'pending'|'running'|'done', log:string}[]}
 */
export function stepsFromSession(session) {
  const running = RUNNING_STEPS[session.phase]
  const lastEvent = session.events?.at(-1)?.msg || ''
  return Array.from({ length: STEP_COUNT }, (_, index) => {
    if (!running) return { stepIndex: index, status: 'done', log: stepLog(index, session) }
    if (index < running[0]) return { stepIndex: index, status: 'done', log: stepLog(index, session) }
    if (running.includes(index)) return { stepIndex: index, status: 'running', log: lastEvent }
    return { stepIndex: index, status: 'pending', log: '' }
  })
}

/** Why a session ended in `error`, from its event log. */
export function sessionError(session) {
  const event = [...(session.events || [])].reverse().find((e) => e.level === 'error')
  const message = event?.msg?.replace(/^Aborted safely, production untouched: /, '') || 'The recovery agent failed.'
  const code = /rewind point/i.test(message) ? 'INTENT_UNPARSEABLE' : 'RECOVERY_FAILED'
  return { message, code }
}

export function toSmokeChecks(session) {
  return (session.result?.checks || []).map((check) => ({ label: `${check.name} (${check.detail})`, passed: Boolean(check.ok) }))
}
