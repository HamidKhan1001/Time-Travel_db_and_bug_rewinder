import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getAuditEntry } from '../../services/api.js'
import { errorMessage } from '../../services/errors.js'
import Drawer from '../ui/Drawer.jsx'
import { SkeletonRows } from '../ui/Skeleton.jsx'
import { ErrorBanner } from '../ui/StateBlocks.jsx'
import { formatDateTime, formatDuration, riskLevel } from '../../utils/format.js'
import { DeltaCell, RewindRef, RiskBadge, RowsLost, StatusBadge } from './AuditBadges.jsx'

const STATUS_NOTE = {
  applied: 'Approved by a human and applied to the live database atomically.',
  undone: 'Applied, then undone. The live database was returned to its state before the apply.',
  discarded: 'The plan was discarded on the clone. Nothing was written to the live database.',
  failed: 'The run failed before a plan was ready. Nothing was written to the live database.',
}

/**
 * Read-only record of one recovery, opened from a table row.
 * (The Stitch exports have no detail screen; this drawer reuses the same components.)
 */
export default function AuditDetailDrawer({ id, onClose }) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!id) return undefined
    let cancelled = false
    setState({ status: 'loading', data: null, error: null })
    getAuditEntry(id)
      .then((data) => !cancelled && setState({ status: 'ready', data, error: null }))
      .catch((error) => !cancelled && setState({ status: 'error', data: null, error: errorMessage(error) }))
    return () => {
      cancelled = true
    }
  }, [id, attempt])

  const entry = state.data
  const { date, time } = formatDateTime(entry?.startedAt)

  return (
    <Drawer
      open={Boolean(id)}
      onClose={onClose}
      title={`Recovery ${id || ''}`}
      subtitle={entry && <StatusBadge status={entry.status} />}
      footer={
        <p className="text-[11px] text-slate-500">
          Read-only audit record. Full step timeline, merge decisions and patch per recovery need the backend audit API.
        </p>
      }
    >
      {state.status === 'loading' && <SkeletonRows rows={6} className="h-10" />}
      {state.status === 'error' && (
        <ErrorBanner title="This recovery couldn't be loaded" message={state.error} onRetry={() => setAttempt((n) => n + 1)} />
      )}
      {entry && (
        <div className="flex flex-col gap-5">
          <p className="text-[13px] text-slate-600 leading-relaxed">{STATUS_NOTE[entry.status]}</p>
          <section>
            <h3 className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold mb-2">Request prompt</h3>
            <blockquote className="text-[13px] text-slate-800 bg-slate-50 border border-slate-200/80 border-l-4 border-l-brand-400 rounded-lg px-3.5 py-2.5 leading-relaxed">
              {entry.prompt}
            </blockquote>
          </section>
          <section>
            <h3 className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold mb-2">Details</h3>
            <dl className="grid grid-cols-[auto,1fr] gap-x-6 gap-y-2.5 text-[13px] items-center">
              {[
                ['Started', <span key="t" className="font-mono">{date} {time}</span>],
                ['Scenario', entry.scenario],
                ['Rewind point', <RewindRef key="r" value={entry.rewindRef} />],
                ['Kept / Discarded / Conflicts', <DeltaCell key="d" delta={entry.delta} />],
                ['Legitimate rows lost', <RowsLost key="l" value={entry.rowsLost} />],
                [
                  'Risk',
                  <span key="k" className="flex items-center gap-2">
                    <RiskBadge risk={entry.risk} status={entry.status} />
                    {entry.risk !== null && <span className="text-[12px] text-slate-500">{riskLevel(entry.risk).label}</span>}
                  </span>,
                ],
                ['Request to apply', <span key="u" className="font-mono">{formatDuration(entry.durationSec)}</span>],
              ].map(([label, value]) => (
                <Fragment key={label}>
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="text-slate-800">{value}</dd>
                </Fragment>
              ))}
            </dl>
          </section>
          <Link to="/console" className="self-start text-[13px] font-medium text-brand-600 hover:text-brand-700" onClick={onClose}>
            Go to Console →
          </Link>
        </div>
      )}
    </Drawer>
  )
}
