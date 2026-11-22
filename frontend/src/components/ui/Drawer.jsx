import { createPortal } from 'react-dom'
import Icon from './Icon.jsx'
import { useOverlay } from './useOverlay.js'

/** Right-side slide-over panel (full width on mobile). */
export default function Drawer({ open, onClose, title, subtitle, children, footer }) {
  const panelRef = useOverlay({ open, onClose })
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-[65] flex justify-end">
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px] animate-fade-in" onClick={onClose} aria-hidden="true" />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        className="relative h-full w-full sm:max-w-[520px] bg-white border-l border-slate-200 shadow-2xl flex flex-col animate-slide-in-right"
      >
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-100">
          <div className="min-w-0">
            <h2 id="drawer-title" className="text-[16px] font-bold text-slate-900 tracking-tight">
              {title}
            </h2>
            {subtitle && <div className="mt-1">{subtitle}</div>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
            aria-label="Close"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
        {footer && <footer className="px-5 py-4 border-t border-slate-100 bg-slate-50/80">{footer}</footer>}
      </aside>
    </div>,
    document.body,
  )
}
