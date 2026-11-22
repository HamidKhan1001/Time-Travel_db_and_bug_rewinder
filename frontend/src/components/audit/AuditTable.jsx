import Icon from '../ui/Icon.jsx'
import Skeleton from '../ui/Skeleton.jsx'
import { formatDateTime, formatDuration } from '../../utils/format.js'
import { DeltaCell, RewindRef, RiskBadge, RowsLost, StatusBadge } from './AuditBadges.jsx'

const COLUMNS = ['ID', 'Status', 'Timestamp', 'Scenario', 'Request Prompt', 'Rewind Point', 'Delta (K/D/C)', 'Lost', 'Risk', 'Duration']

/** Audit log table (desktop) and record cards (mobile). */
export default function AuditTable({ items, loading, onOpen, highlightId }) {
  if (loading) {
    return (
      <div className="p-4 flex flex-col gap-3" role="status" aria-label="Loading recoveries">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-11 w-full" />
        ))}
      </div>
    )
  }

  return (
    <>
      <div className="hidden md:block overflow-x-auto w-full">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50/90 border-b border-surface-border text-[11px] font-mono uppercase tracking-wider text-slate-500 select-none">
              {COLUMNS.map((column) => (
                <th key={column} scope="col" className="py-3 px-4 font-semibold whitespace-nowrap">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-xs font-mono">
            {items.map((entry) => {
              const { date, time } = formatDateTime(entry.startedAt)
              return (
                <tr
                  key={entry.id}
                  tabIndex={0}
                  onClick={() => onOpen(entry.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onOpen(entry.id)
                    }
                  }}
                  aria-label={`Open recovery ${entry.id}`}
                  className={`hover:bg-slate-50/80 focus:bg-slate-50 focus:outline-none transition-colors cursor-pointer group ${
                    entry.id === highlightId ? 'bg-brand-50/50' : ''
                  }`}
                >
                  <td className="py-3.5 px-4 font-semibold text-brand-600 group-hover:text-brand-700 whitespace-nowrap">
                    <span className="flex items-center gap-1.5">
                      <Icon name="commit" className="text-[14px] text-slate-300 group-hover:text-brand-500 transition-colors" />
                      {entry.id}
                    </span>
                  </td>
                  <td className="py-3.5 px-4">
                    <StatusBadge status={entry.status} />
                  </td>
                  <td className="py-3.5 px-4 text-slate-400 font-normal whitespace-nowrap">
                    {date} <span className="text-slate-600 font-medium">{time}</span>
                  </td>
                  <td className="py-3.5 px-4 font-sans font-medium text-slate-800 min-w-[120px]">{entry.scenario}</td>
                  <td className="py-3.5 px-4 max-w-[280px] font-sans text-slate-500 truncate group-hover:text-slate-800 transition-colors" title={entry.prompt}>
                    {entry.prompt}
                  </td>
                  <td className="py-3.5 px-4">
                    <RewindRef value={entry.rewindRef} />
                  </td>
                  <td className="py-3.5 px-4">
                    <DeltaCell delta={entry.delta} />
                  </td>
                  <td className="py-3.5 px-4">
                    <RowsLost value={entry.rowsLost} />
                  </td>
                  <td className="py-3.5 px-4">
                    <RiskBadge risk={entry.risk} status={entry.status} />
                  </td>
                  <td className="py-3.5 px-4 text-slate-500 font-medium whitespace-nowrap">{formatDuration(entry.durationSec)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <ul className="md:hidden divide-y divide-slate-100">
        {items.map((entry) => {
          const { date, time } = formatDateTime(entry.startedAt)
          return (
            <li key={entry.id}>
              <button
                type="button"
                onClick={() => onOpen(entry.id)}
                className={`w-full text-left px-4 py-3.5 flex items-start gap-3 hover:bg-slate-50/80 ${entry.id === highlightId ? 'bg-brand-50/50' : ''}`}
              >
                <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <StatusBadge status={entry.status} />
                      <span className="font-mono text-[12px] font-semibold text-brand-600">{entry.id}</span>
                    </div>
                    <span className="font-mono text-[11px] text-slate-400">
                      {date.slice(5)} {time.slice(0, 5)}
                    </span>
                  </div>
                  <p className="text-[12px] text-slate-600 line-clamp-2">{entry.prompt}</p>
                  <div className="flex items-center gap-2 font-mono text-[11px] text-slate-500 flex-wrap">
                    <DeltaCell delta={entry.delta} />
                    <span className="text-slate-300">·</span>
                    <span>Lost {entry.rowsLost ?? '—'}</span>
                    <span className="text-slate-300">·</span>
                    <RiskBadge risk={entry.risk} status={entry.status} />
                  </div>
                </div>
                <Icon name="chevron_right" className="text-[18px] text-slate-300 mt-1" />
              </button>
            </li>
          )
        })}
      </ul>
    </>
  )
}
