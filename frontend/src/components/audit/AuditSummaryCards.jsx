import Icon from '../ui/Icon.jsx'
import Skeleton from '../ui/Skeleton.jsx'
import { formatNumber } from '../../utils/format.js'

function MetricCard({ label, icon, iconClass, accent, children }) {
  return (
    <div className="flex-1 md:flex-initial px-4 py-3 bg-white border border-surface-border rounded-xl shadow-card flex flex-col justify-center min-w-[150px] relative overflow-hidden group hover:border-slate-300 transition-colors">
      <div className={`absolute -right-4 -bottom-4 w-14 h-14 rounded-full opacity-60 pointer-events-none group-hover:scale-125 transition-transform duration-300 ${accent}`} />
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold">{label}</span>
        <Icon name={icon} className={`text-[16px] ${iconClass}`} />
      </div>
      {children}
    </div>
  )
}

/** "Total recoveries" and "Success rate" metric cards (Audit log design). */
export default function AuditSummaryCards({ summary }) {
  return (
    <div className="flex items-stretch gap-3 self-stretch md:self-auto">
      <MetricCard label="Total Recoveries" icon="history_toggle_off" iconClass="text-slate-400" accent="bg-brand-50">
        {summary.status === 'loading' ? (
          <Skeleton className="h-8 w-24" />
        ) : summary.status === 'error' ? (
          <span className="text-[12px] text-slate-400">Unavailable</span>
        ) : (
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-slate-900 tracking-tight">{formatNumber(summary.data.totalRecoveries)}</span>
            <span className="text-[11px] font-mono text-emerald-600 font-semibold">+{summary.data.today} today</span>
          </div>
        )}
      </MetricCard>
      <MetricCard label="Success Rate" icon="task_alt" iconClass="text-emerald-500" accent="bg-emerald-50">
        {summary.status === 'loading' ? (
          <Skeleton className="h-8 w-24" />
        ) : summary.status === 'error' || summary.data.successRate === null ? (
          <span className="text-2xl font-bold font-mono text-slate-300">—</span>
        ) : (
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-2xl font-bold font-mono text-emerald-600 tracking-tight">{summary.data.successRate}%</span>
            <span className="text-[10px] font-mono bg-emerald-100/70 text-emerald-800 px-1.5 py-0.5 rounded font-semibold">
              TARGET {summary.data.targetSuccessRate.toFixed(1)}%
            </span>
          </div>
        )}
      </MetricCard>
    </div>
  )
}
