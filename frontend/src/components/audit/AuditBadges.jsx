import { AUDIT_STATUS, riskLevel } from '../../utils/format.js'

const STATUS_CLASS = {
  emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200/80',
  indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200/80',
  slate: 'bg-slate-100 text-slate-600 border-slate-200',
  rose: 'bg-rose-50 text-rose-700 border-rose-200/80',
}
const DOT = { emerald: 'bg-emerald-500', indigo: 'bg-indigo-500', slate: 'bg-slate-400', rose: 'bg-rose-500', amber: 'bg-amber-500' }

export function StatusBadge({ status }) {
  const config = AUDIT_STATUS[status] || { label: status, tone: 'slate' }
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold font-sans border shadow-2xs ${STATUS_CLASS[config.tone]}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${DOT[config.tone]}`} />
      {config.label}
    </span>
  )
}

const RISK_CLASS = {
  emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  amber: 'bg-amber-50 text-amber-700 border-amber-200',
  rose: 'bg-rose-50 text-rose-700 border-rose-200',
  slate: 'bg-slate-100 text-slate-700 border-slate-200',
}

/** Risk 0–1 shown as a decimal like the Audit log design (e.g. 0.12). Grey for plans that never went live. */
export function RiskBadge({ risk, status }) {
  if (risk === null || risk === undefined) return <span className="text-slate-300">—</span>
  const tone = status === 'discarded' ? 'slate' : riskLevel(risk).tone
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-bold border ${RISK_CLASS[tone]}`} title={`Risk ${riskLevel(risk).label}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${DOT[tone]}`} />
      {risk.toFixed(2)}
    </span>
  )
}

export function DeltaCell({ delta }) {
  if (!delta) return <span className="text-slate-300">—</span>
  const part = (value, tone) => <span className={value ? `${tone} font-semibold` : 'text-slate-400'}>{value}</span>
  return (
    <div className="flex items-center gap-1 text-[11px]" title={`${delta.kept} kept / ${delta.discarded} discarded / ${delta.conflicts} conflicts`}>
      {part(delta.kept, 'text-emerald-600')}
      <span className="text-slate-300">/</span>
      {part(delta.discarded, 'text-rose-600')}
      <span className="text-slate-300">/</span>
      {part(delta.conflicts, 'text-amber-600')}
    </div>
  )
}

export function RowsLost({ value }) {
  if (value === null || value === undefined) return <span className="text-slate-300">—</span>
  return (
    <span
      className={`inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 rounded-full font-semibold text-[11px] border ${
        value === 0 ? 'bg-emerald-50 text-emerald-700 border-emerald-200/60' : 'bg-rose-50 text-rose-700 border-rose-200/60'
      }`}
    >
      {value}
    </span>
  )
}

export function RewindRef({ value }) {
  if (!value) return <span className="text-slate-300">—</span>
  return <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-mono text-[11px] border border-slate-200/60 font-medium">{value}</span>
}
