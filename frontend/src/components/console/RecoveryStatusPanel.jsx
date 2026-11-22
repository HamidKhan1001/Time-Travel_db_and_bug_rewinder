import { useNavigate } from 'react-router-dom'
import { useDemo } from '../../context/DemoContext.jsx'
import { useElapsed } from '../../hooks/useElapsed.js'
import Button from '../ui/Button.jsx'
import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import Spinner from '../ui/Spinner.jsx'

function StepIcon({ status, index }) {
  if (status === 'done') {
    return (
      <span className="w-5 h-5 rounded-full bg-emerald-100 border border-emerald-300 text-emerald-700 flex items-center justify-center shrink-0">
        <Icon name="check" className="text-[12px]" />
      </span>
    )
  }
  if (status === 'running') {
    return (
      <span className="w-5 h-5 rounded-full bg-brand-50 border border-brand-200 text-brand-600 flex items-center justify-center shrink-0">
        <Spinner className="w-3 h-3" />
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="w-5 h-5 rounded-full bg-rose-100 border border-rose-300 text-rose-700 flex items-center justify-center shrink-0">
        <Icon name="close" className="text-[12px]" />
      </span>
    )
  }
  return (
    <span className="w-5 h-5 rounded-full bg-slate-100 border border-slate-200 text-slate-400 flex items-center justify-center text-[10px] font-mono shrink-0">
      {index + 1}
    </span>
  )
}

/** Vertical streaming progress list (PRD §6 "Streaming progress in the UI"). */
export function StepList({ steps }) {
  return (
    <ol className="flex flex-col">
      {steps.map((step, index) => (
        <li key={step.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <StepIcon status={step.status} index={index} />
            {index < steps.length - 1 && (
              <span className={`w-px flex-1 my-1 ${step.status === 'done' ? 'bg-emerald-300' : 'bg-slate-200'}`} />
            )}
          </div>
          <div className="pb-3 min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span
                className={`text-[12px] font-mono ${
                  step.status === 'running' ? 'font-bold text-brand-700' : step.status === 'pending' ? 'text-slate-400' : 'text-slate-700 font-medium'
                }`}
              >
                {step.label}
              </span>
              <span className={`text-[10px] font-mono ${step.tool === 'apply_recovery' ? 'text-rose-500' : 'text-slate-400'}`}>
                {step.tool}
              </span>
            </div>
            {step.log && <p className="text-[11px] text-slate-500 font-mono mt-0.5 truncate">{step.log}</p>}
            {index === steps.length - 1 && step.status === 'pending' && (
              <p className="text-[11px] text-slate-400 mt-0.5">Waits for your approval. Nothing touches live before that.</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}

/** Right column below the composer: empty state, live progress, failure or next step. */
export default function RecoveryStatusPanel() {
  const { recovery, cancelRun, dismissRecoveryError } = useDemo()
  const navigate = useNavigate()
  const elapsed = useElapsed(recovery.startedAt, recovery.status === 'running')

  if (recovery.status === 'running') {
    return (
      <Card className="p-5 flex flex-col gap-4" aria-live="polite">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-violet-50 border border-violet-200/70 text-violet-600 flex items-center justify-center">
              <Icon name="fork_right" className="text-[16px]" />
            </span>
            <div>
              <h2 className="font-bold text-slate-800 text-[14px]">Recovery progress</h2>
              <p className="text-[11px] text-slate-500">Running on clone cl-9942-alpha</p>
            </div>
          </div>
          <span className="font-mono text-[11px] text-slate-500 bg-slate-100 border border-slate-200/70 rounded px-2 py-0.5 flex items-center gap-1">
            <Icon name="timer" className="text-[13px]" /> {elapsed}
          </span>
        </div>
        <StepList steps={recovery.steps} />
        <Button variant="ghost" size="sm" icon="close" onClick={cancelRun} className="self-start">
          Cancel run
        </Button>
      </Card>
    )
  }

  if (recovery.status === 'failed') {
    return (
      <Card className="p-5 flex flex-col gap-4 !border-rose-200" role="alert">
        <div className="flex items-start gap-3 rounded-lg border border-rose-200 border-l-4 border-l-rose-500 bg-rose-50/70 px-4 py-3">
          <Icon name="error" className="text-[18px] text-rose-600 mt-0.5" />
          <div>
            <p className="text-[13px] font-semibold text-rose-900">
              {recovery.error?.code === 'NOTHING_TO_RECOVER' ? 'Nothing to recover' : 'Time-travel run failed'}
            </p>
            <p className="text-[12px] text-rose-800/90 mt-0.5 leading-relaxed">{recovery.error?.message}</p>
            <p className="text-[11px] text-rose-700/80 mt-1.5">The live database was not changed.</p>
          </div>
        </div>
        {recovery.steps.some((step) => step.status !== 'pending') && <StepList steps={recovery.steps} />}
        <Button variant="secondary" size="sm" icon="close" onClick={dismissRecoveryError} className="self-start">
          Dismiss
        </Button>
      </Card>
    )
  }

  if (recovery.status === 'review' || recovery.status === 'live') {
    const live = recovery.status === 'live'
    return (
      <Card className={`p-5 flex flex-col gap-3 ${live ? '!border-emerald-200' : '!border-violet-200'}`}>
        <div className="flex items-center gap-2">
          <Icon name={live ? 'check_circle' : 'fact_check'} className={`text-[20px] ${live ? 'text-emerald-600' : 'text-violet-600'}`} />
          <h2 className="font-bold text-slate-800 text-[14px]">
            {live ? `Recovery ${recovery.applied?.id} is live` : `Plan ${recovery.plan?.id} is waiting for approval`}
          </h2>
        </div>
        <p className="text-[12px] text-slate-500 leading-relaxed">
          {live
            ? 'Applied atomically and smoke-checked. Run the warehouse sync again to check the fix: it should touch only 1 row.'
            : `${recovery.plan?.stats.kept} kept · ${recovery.plan?.stats.discarded} discarded · ${recovery.plan?.stats.conflicts} conflict resolved. Nothing has been written to the live database yet.`}
        </p>
        <Button variant="secondary" size="sm" icon="arrow_forward" className="self-start" onClick={() => navigate('/console/review')}>
          {live ? 'View recovery' : 'Review plan'}
        </Button>
      </Card>
    )
  }

  // Idle: empty state from the Console Incident design
  return (
    <Card hover={false} className="p-7 flex flex-col items-center text-center gap-4 flex-1 justify-center !border-dashed !border-slate-200/90">
      <div className="p-3.5 rounded-2xl bg-gradient-to-tr from-slate-100 to-indigo-50/50 flex items-center justify-center border border-slate-200/60 shadow-xs">
        <Icon name="hourglass_empty" className="text-[26px] text-indigo-400" />
      </div>
      <div className="flex flex-col gap-1.5">
        <h2 className="font-bold text-slate-800 text-[15px] tracking-tight">No recovery running</h2>
        <p className="text-[12px] text-slate-500 max-w-xs leading-relaxed">
          Trigger the recovery composer above to begin automated transaction rewind and database state repair.
        </p>
      </div>
      <div className="w-full grid grid-cols-3 gap-2 mt-3 pt-5 border-t border-slate-100">
        {['Analyze', 'Rewind', 'Verify'].map((label, index) => (
          <div key={label} className="flex flex-col items-center gap-1.5">
            <div
              className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold border ${
                index === 0 ? 'bg-indigo-50 border-indigo-200 text-indigo-600 shadow-xs' : 'bg-slate-100 border-slate-200/70 text-slate-400'
              }`}
            >
              {index + 1}
            </div>
            <span className={`text-[11px] ${index === 0 ? 'text-slate-700 font-semibold' : 'text-slate-400 font-medium'}`}>{label}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}
