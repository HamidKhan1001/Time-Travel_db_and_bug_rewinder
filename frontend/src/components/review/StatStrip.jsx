import Icon from '../ui/Icon.jsx'
import { riskLevel, riskPercent } from '../../utils/format.js'

const RISK_PILL = {
  emerald: 'bg-emerald-100 border-emerald-300 text-emerald-900',
  amber: 'bg-amber-100 border-amber-300 text-amber-900',
  rose: 'bg-rose-100 border-rose-300 text-rose-900',
}
const RISK_DOT = { emerald: 'bg-emerald-600', amber: 'bg-amber-600', rose: 'bg-rose-600' }

function Tile({ label, className, labelClass, children }) {
  return (
    <div className={`flex flex-col p-2.5 rounded-lg border text-center transition ${className}`}>
      <span className={`text-[11px] font-sans font-bold uppercase tracking-wider ${labelClass}`}>{label}</span>
      <div className="mt-0.5 flex items-center justify-center gap-1 min-h-[24px]">{children}</div>
    </div>
  )
}

/** Colourful summary stat strip (Console Review design). */
export default function StatStrip({ plan }) {
  const { stats, risk, confidence } = plan
  const level = riskLevel(risk.score)
  return (
    <div className="w-full bg-white border-b border-slate-200/80 px-4 sm:px-6 py-3.5">
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <Tile label="Rewind Target" className="bg-indigo-50/60 border-indigo-100/90 hover:border-indigo-200" labelClass="text-indigo-700">
          <span className="text-indigo-950 font-extrabold font-mono text-[16px] tracking-tight">{plan.rewindTarget}</span>
        </Tile>
        <Tile label="Changes Trailed" className="bg-slate-50 border-slate-200/80 hover:border-slate-300" labelClass="text-slate-600">
          <span className="text-slate-950 font-extrabold font-mono text-[16px]">{stats.changes} ops</span>
        </Tile>
        <Tile label="Kept Mutations" className="bg-emerald-50/60 border-emerald-200 hover:border-emerald-300" labelClass="text-emerald-800">
          <span className="text-emerald-700 font-extrabold text-[16px] flex items-center gap-1">
            <Icon name="done_all" className="text-[16px]" /> {stats.kept} Kept
          </span>
        </Tile>
        <Tile label="Discarded" className="bg-rose-50/60 border-rose-200 hover:border-rose-300" labelClass="text-rose-800">
          <span className="text-rose-700 font-extrabold text-[16px] flex items-center gap-1">
            <Icon name="remove_done" className="text-[16px]" /> {stats.discarded} Purged
          </span>
        </Tile>
        <Tile label="Conflicts" className="bg-amber-50/60 border-amber-200 hover:border-amber-300" labelClass="text-amber-800">
          <span className="text-amber-900 font-extrabold text-[16px]">
            {stats.conflicts ? `${stats.conflictsResolved} Resolved` : 'None'}
          </span>
        </Tile>
        <Tile label="Risk Meter" className="bg-slate-50 border-slate-200/80 hover:border-slate-300" labelClass="text-slate-600">
          <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[12px] font-extrabold ${RISK_PILL[level.tone]}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${RISK_DOT[level.tone]}`} /> {riskPercent(risk.score)} {level.label}
          </span>
        </Tile>
        <Tile
          label="AI Confidence"
          className="bg-purple-50/50 border-purple-200 hover:border-purple-300 col-span-2 sm:col-span-1"
          labelClass="text-purple-800"
        >
          <Icon name="auto_awesome" className="text-purple-700 text-[16px]" />
          <span className="text-purple-950 font-extrabold text-[16px]">{Math.round(confidence * 100)}%</span>
        </Tile>
      </div>
      <p className="mt-2.5 text-[11px] text-slate-500 flex flex-wrap items-center gap-x-1.5 gap-y-1">
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <Icon name="verified" className="text-[14px] text-emerald-600" />
          Legitimate rows lost: <strong className="font-mono text-emerald-700">{stats.legitimateRowsLost ?? '—'}</strong>
        </span>
        <span className="hidden sm:inline text-slate-300">·</span>
        <span>
          Rewind point checked against crash at <span className="font-mono text-slate-700">{plan.crashAt}</span>
          {plan.guardrailAdjusted && <span className="text-amber-700 font-semibold"> (adjusted by guardrail)</span>}
        </span>
      </p>
    </div>
  )
}
