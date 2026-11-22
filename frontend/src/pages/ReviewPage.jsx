import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDemo } from '../context/DemoContext.jsx'
import { usePageTitle } from '../hooks/usePageTitle.js'
import { riskLevel, riskPercent } from '../utils/format.js'
import ReviewBanner from '../components/review/ReviewBanner.jsx'
import HorizontalStepper from '../components/review/HorizontalStepper.jsx'
import StatStrip from '../components/review/StatStrip.jsx'
import { ActiveOrdersFeed, CompactInventory, LiveSnapshotHeader } from '../components/review/LiveSnapshotCards.jsx'
import ChangeLogFeed from '../components/console/ChangeLogFeed.jsx'
import MergePlanCard from '../components/review/MergePlanCard.jsx'
import ConflictCard from '../components/review/ConflictCard.jsx'
import PatchDiffCard from '../components/review/PatchDiffCard.jsx'
import SmokeChecksCard from '../components/review/SmokeChecksCard.jsx'
import ApprovalBar from '../components/review/ApprovalBar.jsx'
import { StepList } from '../components/console/RecoveryStatusPanel.jsx'
import Button from '../components/ui/Button.jsx'
import Card from '../components/ui/Card.jsx'
import { ConfirmDialog } from '../components/ui/Modal.jsx'
import { EmptyState } from '../components/ui/StateBlocks.jsx'

function SummaryRow({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-slate-500">{label}</span>
      <span className="font-mono text-slate-800 text-right">{children}</span>
    </div>
  )
}

/** Console — Review & approve screen (Stitch export: console-review). */
export default function ReviewPage() {
  const { recovery, snapshot, pending, approveRecovery, discardRecovery, undoRecovery } = useDemo()
  const navigate = useNavigate()
  const [dialog, setDialog] = useState(null) // 'approve' | 'discard' | 'undo'
  const [dialogError, setDialogError] = useState(null)
  usePageTitle('Review recovery')

  const live = recovery.status === 'live'
  const plan = recovery.plan

  const open = (name) => {
    setDialogError(null)
    setDialog(name)
  }
  const close = () => setDialog(null)
  const run = async (action, after) => {
    const result = await action()
    if (result.ok) {
      setDialog(null)
      after?.()
    } else {
      setDialogError(result.error)
    }
  }

  if (recovery.status === 'running') {
    return (
      <div className="max-w-xl mx-auto p-4 md:p-6">
        <Card className="p-5 flex flex-col gap-4">
          <h1 className="font-bold text-slate-900 text-[16px]">Recovery is still running on the clone</h1>
          <StepList steps={recovery.steps} />
          <Button variant="secondary" icon="arrow_back" onClick={() => navigate('/console')} className="self-start">
            Back to console
          </Button>
        </Card>
      </div>
    )
  }

  if (!plan || !['review', 'live'].includes(recovery.status)) {
    return (
      <div className="max-w-xl mx-auto p-4 md:p-6">
        <Card hover={false} className="mt-6">
          <EmptyState
            icon="fact_check"
            title="No recovery plan to review"
            body="Run time-travel from the Console. When the agent finishes on the clone, its plan opens here for your approval."
            action={
              <Button variant="primary" icon="arrow_back" onClick={() => navigate('/console')}>
                Go to Console
              </Button>
            }
          />
        </Card>
      </div>
    )
  }

  const level = riskLevel(plan.risk.score)

  return (
    <div className="flex flex-col w-full pb-36 sm:pb-24">
      <h1 className="sr-only">Review recovery {plan.id}</h1>
      <ReviewBanner live={live} plan={plan} applied={recovery.applied} />
      <HorizontalStepper steps={recovery.steps} live={live} />
      <StatStrip plan={plan} />

      <div className="w-full max-w-[1600px] mx-auto grid grid-cols-1 lg:grid-cols-12 gap-6 p-4 sm:p-6">
        {/* LEFT: live database (5 cols) */}
        <section className="lg:col-span-5 flex flex-col gap-5 min-w-0 order-2 lg:order-1" aria-label="Live database">
          <LiveSnapshotHeader live={live} />
          <CompactInventory inventory={snapshot.data?.inventory} />
          <ActiveOrdersFeed orders={snapshot.data?.orders} plan={plan} live={live} />
          <ChangeLogFeed entries={snapshot.data?.changeLog} maxHeight="max-h-48" />
        </section>

        {/* RIGHT: recovery plan (7 cols) */}
        <section className="lg:col-span-7 flex flex-col gap-5 min-w-0 order-1 lg:order-2" aria-label="Recovery plan">
          {live && <SmokeChecksCard applied={recovery.applied} />}
          <MergePlanCard plan={plan} />
          <ConflictCard conflict={plan.conflict} />
          {plan.patch && <PatchDiffCard patch={plan.patch} />}
        </section>
      </div>

      <ApprovalBar
        live={live}
        plan={plan}
        applied={recovery.applied}
        pending={pending}
        onApprove={() => open('approve')}
        onDiscard={() => open('discard')}
        onUndo={() => open('undo')}
        onBack={() => navigate('/console')}
      />

      <ConfirmDialog
        open={dialog === 'approve'}
        onClose={close}
        onConfirm={() => run(approveRecovery, () => window.scrollTo({ top: 0, behavior: 'smooth' }))}
        icon="database"
        tone="rose"
        title="Apply this recovery to the live database?"
        badge={
          <span className="px-2 py-0.5 rounded-full bg-rose-50 border border-rose-200 text-rose-700 text-[10px] font-mono font-bold flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" /> LIVE
          </span>
        }
        description="The merge plan and patch will be written to production in one atomic transaction. You can undo it afterwards."
        confirmLabel="Apply to live"
        confirmVariant="danger"
        confirmIcon="bolt"
        loading={pending.approve}
        loadingText="Applying…"
        error={dialogError}
      >
        <div className="rounded-lg bg-slate-50 border border-slate-200/80 px-3.5 py-2 text-[12px] divide-y divide-slate-200/70">
          <SummaryRow label="Rewind point">{plan.rewindTarget}</SummaryRow>
          <SummaryRow label="Changes">
            {plan.stats.kept} kept · {plan.stats.discarded} discarded · {plan.stats.conflicts} conflict resolved
          </SummaryRow>
          <SummaryRow label="Patch">
            {plan.patch
              ? `${plan.patch.file} — ${plan.patch.verification?.passed ? 'verified on clone' : 'not verified'}`
              : 'No code change'}
          </SummaryRow>
          <SummaryRow label="Risk">
            {riskPercent(plan.risk.score)} · {level.label}
          </SummaryRow>
          <SummaryRow label="Legitimate rows lost">{plan.stats.legitimateRowsLost ?? '—'}</SummaryRow>
        </div>
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog === 'discard'}
        onClose={close}
        onConfirm={() => run(discardRecovery, () => navigate('/console'))}
        icon="delete_sweep"
        tone="slate"
        title="Discard this recovery plan?"
        badge={
          <span className="px-2 py-0.5 rounded-full bg-violet-50 border border-violet-200 text-violet-700 text-[10px] font-mono font-bold">CLONE</span>
        }
        description="The clone and its plan are thrown away. Nothing was written to the live database. This is recorded in the audit log."
        confirmLabel="Discard plan"
        confirmVariant="danger-soft"
        loading={pending.discard}
        loadingText="Discarding…"
        error={dialogError}
      />

      <ConfirmDialog
        open={dialog === 'undo'}
        onClose={close}
        onConfirm={() => run(undoRecovery, () => navigate('/console'))}
        icon="undo"
        tone="rose"
        title="Undo this recovery?"
        description={`The live database goes back to its state just before ${recovery.applied?.id} was applied (${recovery.applied?.appliedAt}). This is recorded in the audit log.`}
        confirmLabel="Undo recovery"
        confirmVariant="danger"
        confirmIcon="undo"
        loading={pending.undo}
        loadingText="Undoing…"
        error={dialogError}
      />
    </div>
  )
}
