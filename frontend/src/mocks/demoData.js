/**
 * Demo data for the warehouse-sync incident (PRD §5 demo flow).
 *
 * This is mock data only. It mirrors the content of the Google Stitch designs,
 * unified into one consistent story so the three screens agree with each other.
 * The backend will replace all of it.
 */

export const scenarios = [
  {
    id: 'warehouse-wipe',
    code: 'S02',
    name: 'Warehouse Wipe (Stock 0)',
    description:
      'Simulates a faulty inventory sync execution wiping stock levels while concurrent orders are placed.',
    available: true,
  },
  {
    id: 'scenario-2',
    code: 'S03',
    name: 'Second scenario (TBD)',
    description: 'Second incident scenario from the PRD. Not defined yet, so it is not available in mock mode.',
    available: false,
  },
]

/** Healthy inventory before the crash. */
export const seedInventory = [
  { sku: 'SKU-881', name: 'Limited Drop Hoodie', category: 'Apparel', stock: 3, limited: true },
  { sku: 'SKU-882', name: 'Techwear Cargo Pant', category: 'Apparel', stock: 40, limited: false },
  { sku: 'SKU-883', name: 'Modular Chest Rig', category: 'Gear', stock: 25, limited: false },
  { sku: 'SKU-884', name: 'Trail Shell Jacket', category: 'Apparel', stock: 18, limited: false },
  { sku: 'SKU-885', name: 'Utility Sling Bag', category: 'Gear', stock: 60, limited: false },
]

/** Change log entries that exist before the demo starts (newest first). */
export const seedChangeLog = [
  { id: 'cl-4', time: '02:10:00', label: 'Restock batch #402', kind: 'ok' },
  { id: 'cl-3', time: '01:45:22', label: 'Price adjustment', kind: 'ok' },
  { id: 'cl-2', time: '01:15:00', label: 'Session init', kind: 'ok' },
  { id: 'cl-1', time: '00:00:00', label: 'Genesis block', kind: 'ok' },
]

export const CRASH_TIME = '02:14:07'

/** The three orders from PRD §5 step 2. #1043 oversells the limited hoodie. */
export const demoOrders = [
  { id: '#1041', sku: 'SKU-881', item: 'Limited Drop Hoodie', qty: 1, user: 'alex_dev', placedAt: '02:14:09' },
  { id: '#1042', sku: 'SKU-882', item: 'Techwear Cargo Pant', qty: 2, user: 'sarah_q', placedAt: '02:14:10' },
  { id: '#1043', sku: 'SKU-881', item: 'Limited Drop Hoodie', qty: 3, user: 'mike_r', placedAt: '02:14:12' },
]

export { recoverySteps, STEPS_BEFORE_APPROVAL } from '../constants/recoverySteps.js'

/**
 * Builds the recovery plan the agent returns after running on the clone.
 * Reasons are arrays of segments so the UI can emphasise words like the design;
 * a backend can also send a plain string.
 */
export function buildRecoveryPlan({ id, prompt }) {
  return {
    id,
    prompt,
    cloneBranch: 'cl-9942-alpha',
    cloneRef: 'main-clone@88f2',
    targetCommit: '#88f2',
    rewindTarget: '02:14:06.900',
    crashAt: '02:14:07.120',
    guardrailAdjusted: false,
    parsedBy: 'ai',
    stats: { changes: 8, kept: 3, discarded: 5, conflicts: 1, conflictsResolved: 1, legitimateRowsLost: 0 },
    risk: { score: 0.22 },
    confidence: 0.91,
    verifiedSuites: 8,
    operations: [
      {
        id: 'op-1041',
        operation: 'REPLAY_ORDER',
        target: 'order #1041',
        decision: 'kept',
        reason: [
          { text: 'Valid transaction', tone: 'strong' },
          { text: ' executed successfully with ' },
          { text: 'sufficient stock', tone: 'success' },
          { text: '.' },
        ],
        details: [{ label: 'Order', value: '#1041 · Limited Drop Hoodie ×1 · alex_dev' }, { label: 'Placed', value: '02:14:09' }],
      },
      {
        id: 'op-1042',
        operation: 'REPLAY_ORDER',
        target: 'order #1042',
        decision: 'kept',
        reason: [
          { text: 'Valid transaction', tone: 'strong' },
          { text: ' executed successfully with ' },
          { text: 'sufficient stock', tone: 'success' },
          { text: '.' },
        ],
        details: [{ label: 'Order', value: '#1042 · Techwear Cargo Pant ×2 · sarah_q' }, { label: 'Placed', value: '02:14:10' }],
      },
      {
        id: 'op-1043',
        operation: 'REPLAY_ORDER',
        target: 'order #1043',
        decision: 'resolved',
        reason: [
          { text: 'Oversold items adjusted', tone: 'warning' },
          { text: '; ' },
          { text: 'partial fulfillment', tone: 'strong' },
          { text: ' queued for customer.' },
        ],
        details: [{ label: 'Order', value: '#1043 · Limited Drop Hoodie ×3 · mike_r' }, { label: 'Placed', value: '02:14:12' }],
      },
      {
        id: 'op-sync-wipe',
        operation: 'SYNC_WIPE',
        target: 'db.inventory',
        targetNote: '5 rows',
        decision: 'discarded',
        reason: [
          { text: 'Identified as ' },
          { text: 'corrupt sync command', tone: 'danger' },
          { text: '; ' },
          { text: 'completely purged', tone: 'strong' },
          { text: ' from timeline.' },
        ],
        details: seedInventory.map((row) => ({
          label: row.sku,
          value: `UPDATE stock ${row.stock} → 0 · restored to ${row.stock}`,
        })),
      },
    ],
    conflict: {
      item: 'Limited Drop Hoodie',
      sku: 'SKU-881',
      order: '#1043',
      requestedQty: 3,
      availableQty: 2,
      strategy: [
        { text: 'Split order', tone: 'strong' },
        { text: ' into ' },
        { text: '2 fulfilled units', tone: 'success' },
        { text: ' and ' },
        { text: '1 backordered unit', tone: 'warning' },
        { text: ' with automated customer notification dispatch.' },
      ],
    },
    patch: {
      file: 'app/handlers.py',
      hunk: '@@ -42,7 +42,7 @@',
      lines: [
        { type: 'context', text: ' def handle_checkout(session, cart):' },
        { type: 'del', text: '-    inventory.zero_stock_all()' },
        { type: 'add', text: '+    inventory.atomic_decrement_safe(cart.items)' },
        { type: 'context', text: '     if cart.has_oversold():' },
        { type: 'add', text: '+        trigger_backorder_queue(cart.user_id)' },
        { type: 'context', text: '         log.warn("Oversold condition isolated & mitigated")' },
      ],
      verification: { passed: true, rowsTouchedBefore: 5, rowsTouchedAfter: 1 },
    },
  }
}

/** Past recoveries for the Audit log (newest first). Dates are relative to the mock "today". */
export const seedAuditLog = [
  ['R-0007', 'applied', '2026-11-22T14:22:01', 'Warehouse Wipe (Stock 0)', 'The warehouse sync at 14:20 zeroed stock for 5 SKUs. Rewind and keep the new orders.', '#c89f21a', [14, 2, 0], 0.12, 41.2],
  ['R-0006', 'undone', '2026-11-22T13:10:45', 'Warehouse Wipe (Stock 0)', 'Undo the sync from a minute ago, keep the orders placed after it and fix the handler.', '#4af901b', [8, 12, 1], 0.71, 52.8],
  ['R-0005', 'discarded', '2026-11-22T11:05:12', 'Warehouse Wipe (Stock 0)', 'Rewind inventory to before the restock job and replay checkout events.', '#992ea4c', [0, 45, 3], 0.04, null],
  ['R-0004', 'applied', '2026-11-21T22:40:19', 'Warehouse Wipe (Stock 0)', 'Stock went to zero after the nightly sync. Restore counts and keep orders #988–#991.', '#120bc77', [32, 0, 0], 0.01, 28.4],
  ['R-0003', 'applied', '2026-11-21T18:15:30', 'Warehouse Wipe (Stock 0)', 'Sync wiped the limited items. Rewind to 18:13 and resolve the oversold order.', '#883fa10', [5, 1, 0], 0.34, 37.9],
  ['R-0002', 'failed', '2026-11-21T16:02:44', 'Warehouse Wipe (Stock 0)', 'Fix inventory', null, null, null, null],
  ['R-0001', 'applied', '2026-11-21T09:31:07', 'Warehouse Wipe (Stock 0)', 'First rehearsal: rewind the warehouse sync and keep the three demo orders.', '#5d10e2b', [3, 5, 1], 0.22, 44.6],
  ['R-0000', 'discarded', '2026-11-20T23:48:51', 'Warehouse Wipe (Stock 0)', 'Rewind everything to 23:40.', '#0a71c3f', [0, 9, 0], 0.18, null],
].map(([id, status, startedAt, scenario, prompt, rewindRef, delta, risk, durationSec]) => ({
  id,
  status,
  startedAt,
  scenario,
  prompt,
  rewindRef,
  delta: delta ? { kept: delta[0], discarded: delta[1], conflicts: delta[2] } : null,
  rowsLost: delta ? 0 : null,
  risk,
  durationSec,
}))
