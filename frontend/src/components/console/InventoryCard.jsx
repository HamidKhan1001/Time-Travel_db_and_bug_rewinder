import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import { SkeletonRows } from '../ui/Skeleton.jsx'
import { ErrorBanner } from '../ui/StateBlocks.jsx'
import { formatDelta } from '../../utils/format.js'

function StockCell({ row }) {
  if (row.status === 'zeroed') {
    return (
      <span className="inline-flex items-center gap-0.5 bg-rose-50 border border-rose-200/80 px-2 py-0.5 rounded text-[11px] font-bold text-rose-600">
        <Icon name="arrow_downward" className="text-[12px]" /> {row.stock}
      </span>
    )
  }
  if (row.status === 'restored' || row.status === 'updated') {
    return (
      <span className="inline-flex items-center gap-0.5 bg-emerald-50 border border-emerald-200/80 px-2 py-0.5 rounded text-[11px] font-bold text-emerald-700">
        <Icon name={row.status === 'restored' ? 'restore' : 'arrow_upward'} className="text-[12px]" /> {row.stock}
      </span>
    )
  }
  return <span className="font-semibold text-slate-700">{row.stock}</span>
}

function deltaClass(value) {
  if (!value) return 'text-slate-300'
  return value < 0 ? 'text-rose-600' : 'text-emerald-600'
}

/** Inventory table with the incident banner (Console Incident design). */
export default function InventoryCard({ snapshot, onRetry }) {
  const data = snapshot.data
  const incident = data?.incident
  const allZero = data?.inventory?.every((row) => row.stock === 0)

  return (
    <Card hover={false} className="overflow-hidden flex flex-col">
      {incident?.active && (
        <div className="bg-gradient-to-r from-rose-50 via-rose-50/70 to-amber-50/30 px-4 sm:px-5 py-3 flex items-center gap-3 border-b border-rose-200/70">
          <div className="w-7 h-7 rounded-full bg-rose-100 border border-rose-200 flex items-center justify-center text-rose-600 shrink-0 shadow-xs">
            <Icon name="error" className="text-[18px]" />
          </div>
          <div className="text-[13px] font-semibold text-rose-900 flex-1">
            Inventory was wiped by the warehouse sync at{' '}
            <span className="font-mono font-bold text-rose-950 bg-rose-100/60 px-1.5 py-0.5 rounded border border-rose-200/50">
              {incident.crashAt}
            </span>
          </div>
          <span className="hidden sm:inline-block px-2 py-0.5 rounded-full bg-rose-200/70 text-rose-800 text-[10px] font-bold tracking-wider font-mono uppercase">
            Uncommitted Drift
          </span>
        </div>
      )}

      <div className="px-4 sm:px-5 py-3 bg-slate-50/70 flex items-center justify-between gap-2 border-b border-slate-200/80">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded bg-indigo-50 text-indigo-600 flex items-center justify-center">
            <Icon name="inventory_2" className="text-[15px]" />
          </div>
          <h2 className="font-bold text-slate-800 text-[13px] whitespace-nowrap">Inventory Table</h2>
          {data && <span className="hidden sm:inline text-slate-400 text-[12px] font-mono">({data.inventory.length} SKUs)</span>}
        </div>
        {data &&
          (allZero ? (
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping" />
              <span className="text-[11px] text-rose-700 font-mono font-bold bg-rose-50 border border-rose-200/70 px-2 py-0.5 rounded">
                CRITICAL_ZERO
              </span>
            </div>
          ) : (
            <span className="text-[11px] text-emerald-700 font-mono font-bold bg-emerald-50 border border-emerald-200/70 px-2 py-0.5 rounded">
              {data.recovery ? 'RESTORED' : 'HEALTHY'}
            </span>
          ))}
      </div>

      {snapshot.status === 'error' && !data ? (
        <div className="p-4">
          <ErrorBanner title="Couldn't load live data" message={snapshot.error} onRetry={onRetry} />
        </div>
      ) : !data ? (
        <div className="p-4">
          <SkeletonRows rows={5} />
        </div>
      ) : (
        <>
          {/* Desktop / tablet table */}
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-left font-mono text-[12px]">
              <thead>
                <tr className="bg-slate-50/90 text-slate-400 text-[10px] font-bold uppercase tracking-wider border-b border-slate-200/80">
                  <th className="py-2.5 px-5 font-semibold">SKU ID</th>
                  <th className="py-2.5 px-5 font-semibold">Product Name</th>
                  <th className="py-2.5 px-5 font-semibold">Category</th>
                  <th className="py-2.5 px-5 font-semibold text-right">Stock Level</th>
                  <th className="py-2.5 px-5 font-semibold text-right">Delta</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.inventory.map((row, index) => {
                  const delta = row.stock - row.previousStock
                  return (
                    <tr
                      key={`${row.sku}-${row.stock}-${row.status}`}
                      className={`${index % 2 ? 'bg-slate-50/30' : 'bg-white'} hover:bg-slate-50/80 transition-colors group ${
                        row.status !== 'ok' && row.status !== 'zeroed' ? 'animate-flash' : ''
                      }`}
                    >
                      <td className="py-3 px-5 text-indigo-600 font-semibold group-hover:text-indigo-700">{row.sku}</td>
                      <td className="py-3 px-5 text-slate-800 font-sans font-medium text-[13px]">
                        {row.name}
                        {row.limited && (
                          <span className="ml-2 align-middle px-1.5 py-0.5 rounded bg-violet-50 border border-violet-200/70 text-violet-700 text-[10px] font-sans font-semibold">
                            Limited
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-5">
                        <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 text-[11px] font-sans">{row.category}</span>
                      </td>
                      <td className="py-3 px-5 text-right">
                        <StockCell row={row} />
                      </td>
                      <td className={`py-3 px-5 text-right font-bold ${deltaClass(delta)}`}>{formatDelta(delta)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <ul className="sm:hidden divide-y divide-slate-100">
            {data.inventory.map((row) => {
              const delta = row.stock - row.previousStock
              return (
                <li key={row.sku} className="px-4 py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-slate-800 truncate">
                      {row.name}
                      {row.limited && <span className="ml-1.5 text-[10px] font-semibold text-violet-700">Limited</span>}
                    </p>
                    <p className="text-[11px] font-mono text-slate-400">
                      <span className="text-indigo-600 font-semibold">{row.sku}</span> · {row.category}
                    </p>
                  </div>
                  <div className="text-right font-mono text-[12px] shrink-0">
                    <StockCell row={row} />
                    <p className={`text-[11px] font-bold mt-0.5 ${deltaClass(delta)}`}>{formatDelta(delta)}</p>
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Card>
  )
}
