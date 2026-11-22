import Icon from '../ui/Icon.jsx'

/** Compact horizontal progress stepper (steps 1–8) from the Console Review design. */
export default function HorizontalStepper({ steps, live }) {
  // Before approval, the last step ("Promote Live") is the active one.
  const activeIndex = live ? -1 : steps.findIndex((step) => step.status !== 'done')

  return (
    <div className="w-full bg-white border-b border-slate-200/80 px-4 sm:px-6 py-3.5 overflow-x-auto">
      <ol className="flex items-center justify-between min-w-[880px] gap-2" aria-label="Recovery progress">
        {steps.map((step, index) => {
          const done = step.status === 'done' || live
          const active = index === activeIndex
          return (
            <li key={step.id} className="contents">
              <div className="flex items-center gap-2" aria-current={active ? 'step' : undefined} title={step.tool}>
                {done ? (
                  <span className="w-5 h-5 rounded-full bg-emerald-100 border border-emerald-300 text-emerald-700 flex items-center justify-center shadow-xs">
                    <Icon name="check" className="text-[12px]" />
                  </span>
                ) : active ? (
                  <span className="w-5 h-5 rounded-full bg-brand-600 text-white flex items-center justify-center text-[10px] font-bold ring-4 ring-brand-100 shadow-sm animate-pulse">
                    {index + 1}
                  </span>
                ) : (
                  <span className="w-5 h-5 rounded-full bg-slate-100 border border-slate-200 text-slate-500 flex items-center justify-center text-[10px] font-mono font-medium">
                    {index + 1}
                  </span>
                )}
                {active ? (
                  <span className="font-mono text-[11px] font-bold text-brand-700 bg-brand-50 px-2 py-0.5 rounded border border-brand-200 whitespace-nowrap">
                    {step.label} · awaiting approval
                  </span>
                ) : (
                  <span className={`font-mono text-[11px] whitespace-nowrap ${done ? 'font-medium text-slate-700' : 'text-slate-400'}`}>{step.label}</span>
                )}
              </div>
              {index < steps.length - 1 && (
                <div
                  className={`flex-1 h-[2px] ${
                    done && (steps[index + 1].status === 'done' || live)
                      ? 'bg-emerald-300'
                      : done
                        ? 'bg-gradient-to-r from-emerald-300 to-brand-400'
                        : 'bg-slate-200'
                  }`}
                />
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
