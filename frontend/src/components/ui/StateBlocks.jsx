import Button from './Button.jsx'
import Icon from './Icon.jsx'

/** Centered empty state (Stitch "No recovery running" style). */
export function EmptyState({ icon = 'inbox', title, body, action, className = '' }) {
  return (
    <div className={`flex flex-col items-center text-center gap-3 py-10 px-6 ${className}`}>
      <div className="p-3 rounded-2xl bg-gradient-to-tr from-slate-100 to-indigo-50/50 border border-slate-200/60 shadow-xs">
        <Icon name={icon} className="text-[26px] text-indigo-400" />
      </div>
      <div className="flex flex-col gap-1">
        <h3 className="font-bold text-slate-800 text-[15px] tracking-tight">{title}</h3>
        {body && <p className="text-[12px] text-slate-500 max-w-sm leading-relaxed">{body}</p>}
      </div>
      {action}
    </div>
  )
}

/** Inline error banner with an optional retry button. */
export function ErrorBanner({ title = 'Something went wrong', message, onRetry, retryLabel = 'Retry', className = '' }) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-lg border border-rose-200 border-l-4 border-l-rose-500 bg-rose-50/70 px-4 py-3 ${className}`}
    >
      <Icon name="error" className="text-[18px] text-rose-600 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-semibold text-rose-900">{title}</p>
        {message && <p className="text-[12px] text-rose-800/90 mt-0.5 leading-relaxed">{message}</p>}
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" icon="refresh" onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  )
}
