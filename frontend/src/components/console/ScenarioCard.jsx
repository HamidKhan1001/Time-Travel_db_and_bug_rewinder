import { useEffect, useRef, useState } from 'react'
import { useDemo } from '../../context/DemoContext.jsx'
import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import { ConfirmDialog } from '../ui/Modal.jsx'
import Skeleton from '../ui/Skeleton.jsx'

/** "Active Scenario" card with the scenario dropdown (Console Incident design). */
export default function ScenarioCard() {
  const { scenarios, scenarioId, snapshot, recovery, pending, resetDemo, loadScenarios } = useDemo()
  const [open, setOpen] = useState(false)
  const [switchTo, setSwitchTo] = useState(null)
  const menuRef = useRef(null)
  const current = scenarios.data.find((item) => item.id === scenarioId)
  const incident = snapshot.data?.incident?.active
  const locked = ['running', 'review'].includes(recovery.status)

  useEffect(() => {
    if (!open) return undefined
    const close = (event) => {
      if (!menuRef.current?.contains(event.target)) setOpen(false)
    }
    const onKey = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const choose = (item) => {
    setOpen(false)
    if (item.id !== scenarioId) setSwitchTo(item)
  }

  return (
    <Card className="p-4 flex flex-col justify-between gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Active Scenario</span>
        {!snapshot.data ? null : incident ? (
          <span className="px-2 py-0.5 bg-rose-50 border border-rose-200 text-rose-700 text-[10px] font-bold flex items-center gap-1.5 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-600 glow-pulse-red" />
            INCIDENT {current?.code}
          </span>
        ) : (
          <span className="px-2 py-0.5 bg-emerald-50 border border-emerald-200 text-emerald-700 text-[10px] font-bold flex items-center gap-1.5 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            HEALTHY
          </span>
        )}
      </div>

      {scenarios.status === 'loading' ? (
        <Skeleton className="h-[50px] w-full rounded-lg" />
      ) : scenarios.status === 'error' ? (
        <div className="flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-lg border border-rose-200 bg-rose-50/60 text-[12px] text-rose-800">
          <span>Couldn&apos;t load scenarios.</span>
          <button type="button" onClick={loadScenarios} className="font-semibold text-rose-700 hover:text-rose-900 underline-offset-2 hover:underline">
            Retry
          </button>
        </div>
      ) : (
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            disabled={locked}
            title={locked ? 'Finish or discard the current recovery first' : undefined}
            aria-haspopup="listbox"
            aria-expanded={open}
            className="w-full flex items-center justify-between bg-slate-50/80 hover:bg-slate-100/70 px-3.5 py-2.5 rounded-lg border border-slate-200/80 transition-colors group disabled:opacity-60 disabled:cursor-not-allowed text-left"
          >
            <span className="flex items-center gap-2.5 min-w-0">
              <span className="w-7 h-7 rounded-md bg-rose-100/80 text-rose-600 flex items-center justify-center border border-rose-200/60 shrink-0">
                <Icon name="warning" className="text-[17px]" />
              </span>
              <span className="font-semibold text-slate-800 text-[13px] tracking-tight truncate group-hover:text-slate-900">
                {current?.name || 'Choose a scenario'}
              </span>
            </span>
            <Icon name="expand_more" className={`text-slate-400 group-hover:text-slate-600 text-[18px] transition-transform ${open ? 'rotate-180' : ''}`} />
          </button>
          {open && (
            <ul
              role="listbox"
              aria-label="Scenarios"
              className="absolute z-30 mt-1.5 w-full bg-white border border-slate-300/80 rounded-lg shadow-card-hover py-1 animate-pop-in"
            >
              {scenarios.data.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={item.id === scenarioId}
                    disabled={!item.available}
                    onClick={() => choose(item)}
                    className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-[13px] hover:bg-slate-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                  >
                    <span className={`flex items-center gap-2 ${item.available ? 'text-slate-800' : 'text-slate-400'}`}>
                      <span className="font-mono text-[11px] text-slate-400">{item.code}</span>
                      <span className={item.id === scenarioId ? 'font-semibold text-brand-700' : ''}>{item.name}</span>
                    </span>
                    {item.id === scenarioId && <Icon name="check" className="text-[16px] text-brand-600" />}
                    {!item.available && (
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 bg-slate-100 rounded px-1.5 py-0.5">
                        Coming soon
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="text-[12px] text-slate-500 leading-relaxed">{current?.description}</p>

      <ConfirmDialog
        open={Boolean(switchTo)}
        onClose={() => setSwitchTo(null)}
        onConfirm={async () => {
          const ok = await resetDemo(switchTo.id)
          if (ok) setSwitchTo(null)
        }}
        icon="swap_horiz"
        tone="slate"
        title="Switch scenario?"
        description={`The demo data will be reset to "${switchTo?.name}".`}
        confirmLabel="Switch"
        loading={pending.reset}
        loadingText="Switching…"
      />
    </Card>
  )
}
