import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'

/** Results of the smoke checks run after the atomic apply (PRD §5 step 5). */
export default function SmokeChecksCard({ applied }) {
  if (!applied) return null
  return (
    <Card className="p-4 sm:p-5 !border-emerald-200">
      <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <h2 className="text-[15px] font-bold text-slate-900 flex items-center gap-2">
          <Icon name="health_and_safety" className="text-[20px] text-emerald-600" />
          Smoke checks
        </h2>
        <span className="font-mono text-[11px] text-slate-500">Applied {applied.appliedAt}</span>
      </div>
      <ul className="mt-3 flex flex-col gap-2">
        {applied.smokeChecks.map((check) => (
          <li key={check.label} className="flex items-center gap-2 text-[13px] text-slate-700">
            <Icon name={check.passed ? 'check_circle' : 'cancel'} className={`text-[18px] ${check.passed ? 'text-emerald-600' : 'text-rose-600'}`} />
            {check.label}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[12px] text-slate-500 bg-slate-50 border border-slate-200/70 rounded-lg px-3 py-2">
        Next: go back to the Console and press <strong className="text-slate-700">Re-run Sync</strong>. With the patch it should touch only 1 row.
      </p>
    </Card>
  )
}
