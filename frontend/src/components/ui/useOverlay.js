import { useEffect, useRef } from 'react'

/**
 * Shared behaviour for dialogs and drawers: Esc closes, focus moves inside,
 * Tab stays inside, focus returns to the trigger, page scroll is locked.
 */
export function useOverlay({ open, onClose, locked = false }) {
  const panelRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const previous = document.activeElement
    const panel = panelRef.current
    const focusables = () =>
      panel ? [...panel.querySelectorAll('button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')] : []
    const initial = panel?.querySelector('[data-autofocus]') || focusables()[0]
    initial?.focus()

    const onKey = (event) => {
      if (event.key === 'Escape' && !locked) {
        event.stopPropagation()
        onClose?.()
      }
      if (event.key === 'Tab') {
        const items = focusables()
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus?.()
    }
  }, [open, onClose, locked])

  return panelRef
}
