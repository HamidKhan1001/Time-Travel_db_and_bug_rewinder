import Icon from '../ui/Icon.jsx'
import RichText from '../ui/RichText.jsx'

/** Conflict resolution card (Console Review design). Read-only: the agent resolves the conflict. */
export default function ConflictCard({ conflict }) {
  if (!conflict) return null
  return (
    <section className="bg-gradient-to-br from-white to-amber-50/30 border border-amber-200/90 rounded-xl p-4 sm:p-5 shadow-card hover:shadow-subtle transition-all border-l-4 border-l-amber-500">
      <div className="flex flex-wrap items-start sm:items-center justify-between gap-3 pb-3 border-b border-amber-100">
        <div className="flex items-start sm:items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-200 flex items-center justify-center text-amber-700 shadow-xs shrink-0">
            <Icon name="warning" className="text-[20px]" />
          </div>
          <div>
            <h2 className="font-extrabold text-slate-900 text-[15px]">Conflict Resolution: {conflict.item}</h2>
            <p className="text-slate-600 text-[12px] mt-0.5">
              {conflict.sku} stock exhaustion during concurrent order <strong className="font-mono font-bold text-slate-800">{conflict.order}</strong>
            </p>
          </div>
        </div>
        <span className="px-3 py-1 rounded-full bg-amber-100 text-amber-900 text-[11px] font-extrabold border border-amber-300 shadow-xs uppercase tracking-wide">
          1 Conflict Resolved
        </span>
      </div>
      <div className="bg-white/95 p-3.5 rounded-lg border border-amber-200/70 text-[13px] flex flex-col gap-2.5 text-slate-700 mt-3 shadow-xs">
        <div className="flex flex-wrap justify-between items-center gap-2 border-b border-slate-100 pb-2">
          <span className="text-slate-600">
            Requested Qty: <strong className="text-slate-900 font-mono font-bold text-[14px]">{conflict.requestedQty} units</strong>
          </span>
          <span className="text-slate-600">
            Available Post-Rewind:{' '}
            <strong className="text-emerald-800 font-mono font-bold bg-emerald-100 px-2.5 py-0.5 rounded border border-emerald-300 text-[13px]">
              {conflict.availableQty} units
            </strong>
          </span>
        </div>
        <div className="text-[13px] text-slate-700 pt-0.5 leading-relaxed">
          <span className="text-brand-700 font-extrabold text-[11px] uppercase tracking-wide mr-1.5 bg-brand-50 px-2 py-0.5 rounded border border-brand-200">
            Auto-Resolution Strategy:
          </span>{' '}
          <RichText value={conflict.strategy} />
        </div>
      </div>
    </section>
  )
}
