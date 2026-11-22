import Card, { CardIcon } from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import { SkeletonRows } from '../ui/Skeleton.jsx'

const TAGS = {
  ok: { label: 'OK', className: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  fail: { label: 'FAIL', className: 'text-rose-700 bg-rose-50 border-rose-200' },
  recovery: { label: 'APPLIED', className: 'text-indigo-700 bg-indigo-50 border-indigo-200' },
  undo: { label: 'UNDONE', className: 'text-slate-600 bg-slate-100 border-slate-200' },
}

/** Row-level change log captured by DB triggers (PRD §6), with the crash highlighted. */
export default function ChangeLogFeed({ entries, maxHeight = 'max-h-52', unavailable = false }) {
  return (
    <Card className="p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CardIcon icon="history" tone="amber" />
          <h2 className="font-bold text-slate-800 text-[13px]">Change Log Feed</h2>
        </div>
        {entries && (
          <span className="text-[11px] text-slate-400 font-mono bg-slate-100 px-2 py-0.5 rounded">{entries.length} mutations</span>
        )}
      </div>
      {unavailable ? (
        <p className="text-[12px] text-slate-400 py-6 text-center">The change log is unavailable until live data loads.</p>
      ) : !entries ? (
        <SkeletonRows rows={4} className="h-8" />
      ) : entries.length === 0 ? (
        <p className="text-[12px] text-slate-500 py-6 text-center">No changes yet. Trigger the warehouse sync to start the demo.</p>
      ) : (
        <ul className={`flex flex-col gap-1.5 ${maxHeight} overflow-y-auto pr-1 font-mono text-[11px]`} tabIndex={0} aria-label="Change log entries">
          {entries.map((entry) =>
            entry.kind === 'crash' ? (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-2 p-2.5 rounded-lg bg-gradient-to-r from-rose-50 via-rose-50/90 to-rose-100/40 border-l-4 border-l-rose-500 border border-rose-200/80 shadow-xs"
              >
                <div className="flex items-center gap-2 text-rose-900 font-bold min-w-0">
                  <Icon name="bolt" className="text-[15px] text-rose-600" />
                  <span className="tracking-tight text-[11px] truncate">{entry.label}</span>
                </div>
                <span className="text-rose-700 text-[10px] font-bold bg-rose-100/70 px-1.5 py-0.5 rounded border border-rose-200 shrink-0">
                  {entry.time}
                </span>
              </li>
            ) : (
              <li
                key={entry.id}
                className="flex items-center justify-between gap-2 p-2 rounded-lg bg-slate-50/70 border border-slate-200/60 hover:bg-slate-100/60 transition-colors"
              >
                <span className="text-slate-600 font-medium truncate">
                  {entry.time} · {entry.label}
                </span>
                <span className={`px-1.5 rounded font-bold text-[9px] border shrink-0 ${TAGS[entry.kind]?.className || TAGS.ok.className}`}>
                  {TAGS[entry.kind]?.label || entry.kind}
                </span>
              </li>
            ),
          )}
        </ul>
      )}
    </Card>
  )
}
