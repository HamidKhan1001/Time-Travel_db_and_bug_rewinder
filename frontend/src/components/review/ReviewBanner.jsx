import Icon from '../ui/Icon.jsx'

/** Full-width banner under the header: clone notice (review) or live notice (after apply). */
export default function ReviewBanner({ live, plan, applied }) {
  if (live) {
    return (
      <div className="w-full bg-gradient-to-r from-emerald-50/90 via-emerald-50/60 to-white border-b border-emerald-100 px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-200/70 flex items-center justify-center text-emerald-600 shadow-xs">
            <Icon name="check_circle" className="text-[18px]" />
          </div>
          <span className="text-[13px] font-medium text-slate-800">
            Recovery is live · applied atomically at{' '}
            <span className="font-mono font-semibold text-emerald-800">{applied?.appliedAt}</span> · smoke checks passed
          </span>
        </div>
        <div className="flex items-center gap-2 text-[12px] bg-white/95 px-3.5 py-1.5 rounded-full border border-emerald-100 text-slate-600 shadow-xs">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          <span>
            Every apply can be undone. <strong className="text-slate-800 font-medium">Undo is below.</strong>
          </span>
        </div>
      </div>
    )
  }
  return (
    <div className="w-full bg-gradient-to-r from-indigo-50/80 via-purple-50/60 to-brand-50/40 border-b border-indigo-100/90 px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-7 h-7 rounded-lg bg-indigo-500/10 border border-indigo-200/60 flex items-center justify-center text-indigo-600 shadow-xs shrink-0">
          <Icon name="science" className="text-[18px]" />
        </div>
        <span className="text-[13px] font-medium text-slate-800">
          Time-travel recovery simulation on isolated clone branch
          <span className="inline-flex items-center px-2 py-0.5 ml-1.5 rounded bg-indigo-100/70 text-indigo-700 font-mono text-[12px] font-semibold border border-indigo-200">
            #{plan?.cloneBranch}
          </span>
        </span>
      </div>
      <div className="flex items-center gap-2 text-[12px] bg-white/95 px-3.5 py-1.5 rounded-full border border-indigo-100/80 text-slate-600 shadow-xs">
        <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
        <span>
          Everything below ran on a clone. <strong className="text-slate-800 font-medium">Nothing written to live.</strong>
        </span>
      </div>
    </div>
  )
}
