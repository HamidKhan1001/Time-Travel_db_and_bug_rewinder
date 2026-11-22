import { useToast } from '../../context/ToastContext.jsx'
import Icon from './Icon.jsx'

const TONES = {
  success: { icon: 'check_circle', className: 'text-emerald-600' },
  info: { icon: 'info', className: 'text-indigo-600' },
  danger: { icon: 'error', className: 'text-rose-600' },
}

export default function Toaster() {
  const { toasts, dismiss } = useToast()
  return (
    <div
      className="fixed z-[80] top-[4.25rem] left-1/2 -translate-x-1/2 sm:left-auto sm:translate-x-0 sm:right-6 flex flex-col gap-2 w-[calc(100%-2rem)] sm:w-auto sm:max-w-sm"
      aria-live="polite"
      role="status"
    >
      {toasts.map((toast) => {
        const tone = TONES[toast.tone] || TONES.success
        return (
          <div
            key={toast.id}
            className="flex items-start gap-2.5 bg-white border border-slate-200 rounded-lg shadow-card-hover px-3.5 py-3 animate-pop-in"
          >
            <Icon name={tone.icon} className={`text-[18px] ${tone.className}`} />
            <p className="flex-1 text-[13px] text-slate-700 leading-snug">{toast.message}</p>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="text-slate-400 hover:text-slate-700"
              aria-label="Dismiss notification"
            >
              <Icon name="close" className="text-[16px]" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
