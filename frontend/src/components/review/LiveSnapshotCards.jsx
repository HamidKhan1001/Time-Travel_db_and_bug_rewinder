import { useMemo, useState } from 'react'
import { useDemo } from '../../context/DemoContext.jsx'
import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import { PingDot } from '../ui/Pill.jsx'
import { SkeletonRows } from '../ui/Skeleton.jsx'
import { OrderStatusPill } from '../console/OrdersStream.jsx'

function CardTitle({ icon, children, right }) {
  return (
    <div className="flex items-center justify-between gap-2 mb-3">
      <h2 className="font-semibold text-slate-900 text-[14px] flex items-center gap-2">
        <span className="w-6 h-6 rounded bg-slate-100 text-slate-600 flex items-center justify-center">
          <Icon name={icon} className="text-[15px]" />
        </span>
        {children}
      </h2>
      {right}
    </div>
  )
}

/** "Live Database Snapshot" header card with the compact scenario select. */
export function LiveSnapshotHeader({ live }) {
  const { scenarios, scenarioId } = useDemo()
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2.5">
          <PingDot tone={live ? 'emerald' : 'rose'} size="h-2.5 w-2.5" />
          <h2 className="font-semibold text-slate-900 text-[14px]">Live Database Snapshot</h2>
        </div>
        {live ? (
          <span className="px-2.5 py-0.5 rounded bg-emerald-100/80 text-emerald-800 text-[11px] font-extrabold border border-emerald-300 tracking-wider">
            RESTORED
          </span>
        ) : (
          <span className="px-2.5 py-0.5 rounded bg-rose-100/80 text-rose-800 text-[11px] font-extrabold border border-rose-300 tracking-wider">
            WIPED BY SYNC
          </span>
        )}
      </div>
      <div className="mt-3 flex items-center gap-2 bg-slate-50/80 p-2 rounded-lg border border-slate-200/70 font-mono">
        <Icon name="tune" className="text-[16px] text-brand-600" />
        <label htmlFor="review-scenario" className="text-slate-500 text-[12px]">
          Scenario:
        </label>
        <select
          id="review-scenario"
          value={scenarioId}
          disabled
          title="Scenario is locked while a recovery is open. Change it from the Console after finishing."
          className="bg-white text-slate-800 border border-slate-200 px-2.5 py-1 rounded-md font-mono text-[12px] outline-none flex-1 min-w-0 shadow-xs disabled:opacity-100 disabled:cursor-not-allowed"
        >
          {scenarios.data.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
    </Card>
  )
}

/** Compact inventory table: SKU / Item Name / Live Qty / Status. */
export function CompactInventory({ inventory }) {
  const zeroed = inventory?.every((row) => row.stock === 0)
  return (
    <Card className="p-4">
      <CardTitle
        icon="inventory_2"
        right={
          inventory &&
          (zeroed ? (
            <span className="text-[11px] text-rose-700 font-extrabold bg-rose-100/80 px-2.5 py-0.5 rounded border border-rose-300">
              All stock wiped (0 qty)
            </span>
          ) : (
            <span className="text-[11px] text-emerald-700 font-extrabold bg-emerald-100/80 px-2.5 py-0.5 rounded border border-emerald-300">
              Stock restored
            </span>
          ))
        }
      >
        Inventory Table
      </CardTitle>
      {!inventory ? (
        <SkeletonRows rows={3} />
      ) : (
        <div className="overflow-x-auto border border-slate-100 rounded-lg">
          <table className="w-full text-left font-mono text-[12px]">
            <thead>
              <tr className="bg-slate-50/90 text-slate-500 border-b border-slate-200/70 text-[11px] font-semibold uppercase tracking-wider">
                <th className="py-2.5 px-3">SKU</th>
                <th className="py-2.5 px-3">Item Name</th>
                <th className="py-2.5 px-3 text-right">Live Qty</th>
                <th className="py-2.5 px-3 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {inventory.map((row) => (
                <tr key={row.sku} className="hover:bg-slate-50/60 transition-colors">
                  <td className="py-2.5 px-3 text-slate-400 font-medium whitespace-nowrap">{row.sku}</td>
                  <td className="py-2.5 px-3 text-slate-800 font-medium font-sans">{row.name}</td>
                  <td className={`py-2.5 px-3 text-right font-bold ${row.stock === 0 ? 'text-rose-600' : 'text-slate-800'}`}>{row.stock}</td>
                  <td className="py-2.5 px-3 text-right">
                    {row.status === 'zeroed' ? (
                      <span className="px-2 py-0.5 rounded bg-rose-50 text-rose-700 text-[10px] font-bold border border-rose-200/70">Zeroed</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 text-[10px] font-bold border border-emerald-200/70 capitalize">
                        {row.status === 'ok' ? 'OK' : row.status}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/**
 * "Active Orders Feed". Before approval it shows each order's projected outcome
 * from the merge plan; after apply it shows the live order status.
 */
export function ActiveOrdersFeed({ orders, plan, live }) {
  const [filter, setFilter] = useState('all')
  const rows = useMemo(() => {
    if (!orders) return null
    return orders
      .filter((order) => order.afterCrash !== false)
      .map((order) => {
        if (live || !plan) return { ...order, conflict: false }
        const op = plan.operations.find((item) => item.target === `order ${order.id}`)
        return { ...order, conflict: op?.decision === 'resolved', status: op?.decision === 'resolved' ? 'oversold' : 'fulfilled' }
      })
  }, [orders, plan, live])
  const problem = (order) => order.conflict || order.status === 'oversold' || order.status === 'partial'
  const visible = rows?.filter((order) => filter === 'all' || problem(order))
  const problemCount = rows?.filter(problem).length ?? 0

  return (
    <Card className="p-4">
      <CardTitle
        icon="receipt_long"
        right={
          <div className="flex items-center gap-1 bg-slate-100/80 p-0.5 rounded-lg border border-slate-200 text-[11px] font-mono" role="tablist" aria-label="Filter orders">
            {[
              ['all', `All (${rows?.length ?? 0})`],
              ['problem', `${live ? 'Backordered' : 'Oversold'} (${problemCount})`],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={filter === key}
                onClick={() => setFilter(key)}
                className={`px-2 py-0.5 rounded-md transition-colors ${
                  filter === key ? 'bg-white text-slate-800 font-semibold shadow-xs' : 'text-slate-500 font-medium hover:text-slate-800'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        }
      >
        Active Orders Feed
      </CardTitle>
      {!visible ? (
        <SkeletonRows rows={3} className="h-14" />
      ) : visible.length === 0 ? (
        <p className="text-[12px] text-slate-500 text-center py-5">{rows.length ? 'No orders match this filter.' : 'No orders after the rewind point.'}</p>
      ) : (
        <ul className="flex flex-col gap-2 font-mono">
          {visible.map((order) =>
            order.conflict ? (
              <li
                key={order.id}
                className="p-3 rounded-lg bg-rose-50/60 border border-rose-200/90 flex items-center justify-between gap-2 shadow-xs ring-1 ring-rose-200/50"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-rose-700 font-extrabold text-[14px]">{order.id}</span>
                  <div className="min-w-0">
                    <div className="text-slate-900 text-[13px] font-sans font-bold truncate">
                      {order.item} <span className="text-rose-600 font-mono text-[11px] font-semibold">(x{order.qty})</span>
                    </div>
                    <div className="text-rose-700 text-[11px] font-sans font-bold flex items-center gap-1 tracking-tight">
                      <Icon name="error" className="text-[14px]" />
                      OVERSOLD: Stock was 0 at checkout
                    </div>
                  </div>
                </div>
                <span className="px-3 py-1 rounded-md bg-rose-600 text-white text-[11px] font-sans font-extrabold shadow-sm flex items-center gap-1.5 uppercase tracking-wide shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  Conflict
                </span>
              </li>
            ) : (
              <li
                key={order.id}
                className="p-3 rounded-lg bg-slate-50/50 border border-slate-200/70 flex items-center justify-between gap-2 shadow-xs hover:border-slate-300 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-brand-600 font-bold text-[13px]">{order.id}</span>
                  <div className="min-w-0">
                    <div className="text-slate-800 text-[12px] font-sans font-medium truncate">
                      {order.item} <span className="text-slate-400 font-mono text-[11px]">(x{order.qty})</span>
                    </div>
                    <div className="text-slate-400 text-[11px]">
                      User: {order.user} @ {order.placedAt}
                    </div>
                  </div>
                </div>
                <OrderStatusPill order={order} />
              </li>
            ),
          )}
        </ul>
      )}
    </Card>
  )
}
