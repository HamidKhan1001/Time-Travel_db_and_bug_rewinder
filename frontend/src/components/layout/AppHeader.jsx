import { useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useDemo } from '../../context/DemoContext.jsx'
import Icon from '../ui/Icon.jsx'
import { PingDot } from '../ui/Pill.jsx'
import { ConfirmDialog } from '../ui/Modal.jsx'

const tabClass = ({ isActive }) =>
  `px-2.5 sm:px-3 py-1.5 rounded-lg text-[13px] font-medium transition-all flex items-center gap-1.5 border whitespace-nowrap ${
    isActive
      ? 'bg-brand-50 text-brand-700 border-brand-200/60 shadow-xs font-semibold'
      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/70 border-transparent'
  }`

/** Top navigation shared by every screen (merged from the three Stitch headers). */
export default function AppHeader() {
  const { auditCount, recovery, pending, resetDemo } = useDemo()
  const navigate = useNavigate()
  const [confirmReset, setConfirmReset] = useState(false)
  const cloneActive = ['running', 'review'].includes(recovery.status)

  const onReset = async () => {
    const ok = await resetDemo()
    if (ok) {
      setConfirmReset(false)
      navigate('/console')
    }
  }

  return (
    <header className="fixed top-0 w-full z-50 bg-white/85 backdrop-blur-md border-b border-slate-200/80">
      <div className="h-14 w-full px-3 sm:px-5 lg:px-6 flex items-center justify-between gap-3 max-w-[1600px] mx-auto">
        <div className="flex items-center gap-3 sm:gap-6 min-w-0">
          <Link to="/console" className="flex items-center gap-2.5 group shrink-0" aria-label="Time-Travel DB & Bug Rewinder — Console">
            <div className="w-7 h-7 bg-gradient-to-tr from-brand-600 to-indigo-500 rounded-lg flex items-center justify-center shadow-md shadow-brand-500/25 group-hover:scale-105 transition-transform">
              <Icon name="history" className="text-white text-[16px]" />
            </div>
            <span className="hidden sm:flex items-center gap-1.5 text-[14px] font-bold tracking-tight text-slate-900">
              Time-Travel DB
              <span className="hidden lg:inline text-slate-400 font-normal text-[13px]">&amp; Bug Rewinder</span>
            </span>
          </Link>
          <nav className="flex items-center gap-1" aria-label="Main">
            <NavLink to="/console" className={tabClass}>
              {({ isActive }) => (
                <>
                  {isActive && <span className="w-1.5 h-1.5 rounded-full bg-brand-600" />}
                  Console
                </>
              )}
            </NavLink>
            <NavLink to="/audit-log" className={tabClass}>
              {({ isActive }) => (
                <>
                  Audit log
                  {auditCount !== null && (
                    <span
                      className={`px-1.5 text-[10px] font-bold font-mono rounded-full border ${
                        isActive ? 'bg-brand-600 text-white border-brand-600' : 'bg-slate-100 text-slate-600 border-slate-200'
                      }`}
                    >
                      {auditCount}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-50 border border-rose-200/80 text-[11px] font-mono font-bold text-rose-700 tracking-wide"
            title="The left side of the Console shows the live (production) database"
          >
            <PingDot tone="rose" size="h-1.5 w-1.5" />
            <span>LIVE DB</span>
          </div>
          <div
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200/80 text-[11px] font-semibold text-emerald-800"
            title="The SQL guard blocks DROP, TRUNCATE, ALTER and unscoped UPDATE/DELETE. The AI cannot override it."
          >
            <Icon name="shield" className="text-[13px] text-emerald-600" />
            <span>Guard on</span>
          </div>
          {cloneActive && (
            <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-violet-50 border border-violet-200/80 text-[11px] font-semibold text-violet-700">
              <Icon name="fork_right" className="text-[13px] text-violet-600" />
              <span>{recovery.plan?.cloneRef || 'main-clone@88f2'}</span>
            </div>
          )}
          <div className="hidden sm:block h-4 w-px bg-slate-200 mx-0.5" />
          <button
            type="button"
            onClick={() => setConfirmReset(true)}
            className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 hover:text-slate-900 text-[12px] font-medium transition-all shadow-xs active:scale-[0.98]"
            aria-label="Reset demo"
          >
            <Icon name="rotate_left" className="text-[15px] text-slate-500" />
            <span className="hidden sm:inline">Reset demo</span>
          </button>
          <div
            className="hidden sm:flex w-8 h-8 rounded-full ring-2 ring-brand-100 bg-gradient-to-tr from-brand-600 to-indigo-500 items-center justify-center text-white shadow-xs"
            title="Demo operator (sign-in is out of scope for this build)"
          >
            <Icon name="person" className="text-[18px]" />
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        onConfirm={onReset}
        icon="rotate_left"
        tone="slate"
        title="Reset the demo?"
        description="Restores the seed data for the current scenario. Any running recovery or unapproved plan is cancelled. The audit log is kept."
        confirmLabel="Reset demo"
        confirmIcon="rotate_left"
        loading={pending.reset}
        loadingText="Resetting…"
      />
    </header>
  )
}
