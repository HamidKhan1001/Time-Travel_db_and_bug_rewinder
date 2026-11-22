import { formatNumber } from '../../utils/format.js'

/** Table footer: "Showing 1–5 of N" with Previous / Next (Audit log design). */
export default function Pagination({ page, pageSize, total, onPage, disabled }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total ? (page - 1) * pageSize + 1 : 0
  const to = Math.min(page * pageSize, total)
  const button =
    'px-3 py-1.5 bg-white border border-surface-border rounded-lg text-xs font-mono font-medium shadow-2xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed enabled:hover:bg-slate-50 enabled:text-slate-700 enabled:hover:text-slate-900 disabled:text-slate-400'
  return (
    <nav
      aria-label="Audit log pages"
      className="flex flex-col sm:flex-row items-center justify-between py-3.5 px-5 bg-slate-50/80 border-t border-surface-border gap-3"
    >
      <div className="flex items-center gap-2 text-xs text-slate-500 font-mono">
        <span className="inline-block w-2 h-2 rounded-full bg-slate-300" />
        Showing{' '}
        <span className="font-semibold text-slate-700">
          {from}–{to}
        </span>{' '}
        of <span className="font-semibold text-slate-700">{formatNumber(total)}</span> recoveries
      </div>
      <div className="flex items-center gap-2">
        <button type="button" className={button} onClick={() => onPage(page - 1)} disabled={disabled || page <= 1}>
          Previous
        </button>
        <div className="flex items-center px-3 py-1.5 bg-white border border-surface-border rounded-lg text-xs font-mono font-semibold text-slate-700 shadow-2xs" aria-current="page">
          <span className="text-brand-600">{page}</span>
          <span className="text-slate-300 mx-1.5">/</span>
          <span className="text-slate-500">{pages}</span>
        </div>
        <button type="button" className={button} onClick={() => onPage(page + 1)} disabled={disabled || page >= pages}>
          Next
        </button>
      </div>
    </nav>
  )
}
