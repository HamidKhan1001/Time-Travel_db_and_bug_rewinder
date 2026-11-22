/** White card with hairline border and soft shadow (Stitch "Cards & Data Panels"). */
export default function Card({ as: Tag = 'div', hover = true, className = '', children, ...props }) {
  return (
    <Tag
      className={`bg-white border border-slate-200/80 rounded-xl card-shadow ${hover ? 'card-shadow-hover' : ''} ${className}`}
      {...props}
    >
      {children}
    </Tag>
  )
}

/** Small square icon tile used in card titles. */
export function CardIcon({ icon, tone = 'slate', className = '' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-600',
    indigo: 'bg-indigo-50 text-indigo-600',
    blue: 'bg-blue-50 text-blue-600',
    amber: 'bg-amber-50 text-amber-600',
    rose: 'bg-rose-100/80 text-rose-600 border border-rose-200/60',
  }
  return (
    <span className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 ${tones[tone]} ${className}`}>
      <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
        {icon}
      </span>
    </span>
  )
}
