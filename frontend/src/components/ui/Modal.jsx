import { createPortal } from 'react-dom'
import Button from './Button.jsx'
import Icon from './Icon.jsx'
import { useOverlay } from './useOverlay.js'

const ICON_TONES = {
  rose: 'bg-rose-50 border-rose-200 text-rose-600',
  indigo: 'bg-indigo-50 border-indigo-200 text-indigo-600',
  slate: 'bg-slate-100 border-slate-200 text-slate-600',
  amber: 'bg-amber-50 border-amber-200 text-amber-700',
}

/**
 * Confirmation dialog. While `loading` it cannot be dismissed.
 * On mobile it opens as a bottom sheet.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  icon = 'help',
  tone = 'indigo',
  badge,
  confirmLabel = 'Confirm',
  confirmVariant = 'primary',
  confirmIcon,
  loading = false,
  loadingText,
  error,
  children,
}) {
  const panelRef = useOverlay({ open, onClose, locked: loading })
  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center sm:p-4">
      <div
        className="absolute inset-0 bg-slate-900/50 backdrop-blur-[2px] animate-fade-in"
        onClick={loading ? undefined : onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className="relative w-full sm:max-w-[520px] bg-white rounded-t-2xl sm:rounded-xl border border-slate-200 shadow-2xl animate-pop-in"
      >
        <div className="p-5 sm:p-6 flex flex-col gap-4">
          <div className="flex items-start gap-3.5">
            <div className={`w-10 h-10 rounded-full border flex items-center justify-center shrink-0 ${ICON_TONES[tone]}`}>
              <Icon name={icon} className="text-[20px]" />
            </div>
            <div className="flex-1 min-w-0 pt-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="dialog-title" className="text-[16px] font-bold text-slate-900 tracking-tight">
                  {title}
                </h2>
                {badge}
              </div>
              {description && <p className="text-[13px] text-slate-500 leading-relaxed mt-1">{description}</p>}
            </div>
          </div>
          {children}
          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-[12px] text-rose-800">
              <Icon name="error" className="text-[16px] text-rose-600" />
              <span>{error}</span>
            </div>
          )}
        </div>
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2.5 px-5 sm:px-6 py-4 bg-slate-50/80 border-t border-slate-100 rounded-b-xl">
          <Button variant="secondary" onClick={onClose} disabled={loading} data-autofocus className="w-full sm:w-auto">
            Cancel
          </Button>
          <Button
            variant={confirmVariant}
            icon={confirmIcon}
            onClick={onConfirm}
            loading={loading}
            loadingText={loadingText}
            className="w-full sm:w-auto"
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
