const TONES = {
  rose: 'bg-rose-50 text-rose-700 border-rose-200',
  emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  amber: 'bg-amber-50 text-amber-700 border-amber-200',
  indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200/80',
  violet: 'bg-violet-50 text-violet-700 border-violet-200/80',
  blue: 'bg-blue-50 text-blue-700 border-blue-200/80',
  slate: 'bg-slate-100 text-slate-600 border-slate-200',
}
const DOTS = {
  rose: 'bg-rose-500',
  emerald: 'bg-emerald-500',
  amber: 'bg-amber-500',
  indigo: 'bg-indigo-500',
  violet: 'bg-violet-500',
  blue: 'bg-blue-500',
  slate: 'bg-slate-400',
}

/** Status pill / badge. `shape="tag"` gives the squarer badge used in tables. */
export default function Pill({ tone = 'slate', dot = false, shape = 'pill', mono = false, className = '', children }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${
        shape === 'pill' ? 'rounded-full' : 'rounded'
      } ${mono ? 'font-mono' : ''} ${TONES[tone]} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${DOTS[tone]}`} />}
      {children}
    </span>
  )
}

/** Pulsing status dot ("ping") used for LIVE and verified indicators. */
export function PingDot({ tone = 'rose', size = 'h-2 w-2' }) {
  const colors = {
    rose: ['bg-rose-400', 'bg-rose-500'],
    emerald: ['bg-emerald-400', 'bg-emerald-500'],
    indigo: ['bg-indigo-400', 'bg-indigo-500'],
  }[tone]
  return (
    <span className={`relative flex shrink-0 ${size}`}>
      <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${colors[0]}`} />
      <span className={`relative inline-flex rounded-full ${size} ${colors[1]}`} />
    </span>
  )
}
