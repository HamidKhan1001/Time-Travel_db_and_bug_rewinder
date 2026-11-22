import Button from '../ui/Button.jsx'
import Icon from '../ui/Icon.jsx'
import { PingDot } from '../ui/Pill.jsx'

/** Sticky action bar at the bottom of the Review screen. */
export default function ApprovalBar({ live, plan, applied, onApprove, onDiscard, onUndo, onBack, pending }) {
  return (
    <div className="fixed bottom-0 left-0 w-full bg-white/90 backdrop-blur-xl border-t border-slate-200/90 px-4 sm:px-6 py-3 sm:py-3.5 z-40 shadow-2xl">
      <div className="max-w-[1600px] mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-[13px] text-slate-600">
          {live ? (
            <>
              <Icon name="check_circle" className="text-[18px] text-emerald-600" />
              <span>
                Recovery <strong className="text-slate-900 font-mono">{applied?.id}</strong> is live. You can undo it at any time.
              </span>
            </>
          ) : plan.patch.verification?.passed ? (
            <>
              <PingDot tone="emerald" size="h-2.5 w-2.5" />
              <span>
                Clone simulation verified across <strong className="text-slate-900 font-mono">{plan.verifiedSuites} test suites</strong>. Ready to
                promote.
              </span>
            </>
          ) : (
            <>
              <Icon name="error" className="text-[18px] text-rose-600" />
              <span>The patch did not pass verification on the clone. Approving is disabled.</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2.5 sm:gap-3">
          {live ? (
            <>
              <Button variant="secondary" icon="arrow_back" onClick={onBack} className="flex-1 sm:flex-none">
                Back to console
              </Button>
              <Button variant="danger-soft" icon="undo" onClick={onUndo} disabled={pending.undo} className="flex-1 sm:flex-none">
                Undo recovery
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={onDiscard} disabled={pending.discard || pending.approve} className="flex-1 sm:flex-none">
                Discard plan
              </Button>
              <button
                type="button"
                onClick={onApprove}
                disabled={!plan.patch.verification?.passed || pending.approve || pending.discard}
                title={!plan.patch.verification?.passed ? "The patch didn't pass verification on the clone" : undefined}
                className="flex-[2] sm:flex-none px-6 py-2.5 rounded-lg bg-gradient-to-r from-brand-600 via-indigo-600 to-brand-700 hover:from-brand-500 hover:to-brand-600 text-white text-[14px] font-extrabold transition-all flex items-center justify-center gap-2 shadow-md shadow-brand-500/25 hover:shadow-lg hover:shadow-brand-500/30 active:scale-[0.98] tracking-wide disabled:opacity-60 disabled:cursor-not-allowed"
              >
                <Icon name="bolt" className="text-[18px]" />
                Approve &amp; go live
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
