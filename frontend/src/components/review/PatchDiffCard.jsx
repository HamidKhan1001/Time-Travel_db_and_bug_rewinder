import { useToast } from '../../context/ToastContext.jsx'
import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'

const LINE = {
  context: 'text-slate-400 px-2 py-0.5',
  del: 'text-rose-300 bg-rose-950/60 border-l-2 border-rose-500 px-2 py-0.5 font-medium',
  add: 'text-emerald-300 bg-emerald-950/60 border-l-2 border-emerald-500 px-2 py-0.5 font-medium',
}

/** Patch diff with clone verification result (PRD §2 "verify it on the clone"). */
export default function PatchDiffCard({ patch }) {
  const { notify } = useToast()
  const passed = patch.verification?.passed
  const diffText = [`--- a/${patch.file}`, `+++ b/${patch.file}`, patch.hunk, ...patch.lines.map((line) => line.text)].join('\n')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(diffText)
      notify('Diff copied')
    } catch {
      notify("Couldn't copy the diff", { tone: 'danger' })
    }
  }

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-7 h-7 rounded-md bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-700 shrink-0">
            <Icon name="code" className="text-[16px]" />
          </div>
          <h2 className="font-bold text-slate-900 font-mono text-[13px] truncate">Patch Diff: {patch.file}</h2>
        </div>
        <div className="flex items-center gap-2">
          {passed ? (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-100 text-emerald-900 text-[11px] font-extrabold border border-emerald-300 shadow-xs uppercase tracking-wide">
              <Icon name="check_circle" className="text-[15px]" />
              Clone Verification Success
            </span>
          ) : (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-rose-100 text-rose-900 text-[11px] font-extrabold border border-rose-300 uppercase tracking-wide">
              <Icon name="cancel" className="text-[15px]" />
              Verification Failed
            </span>
          )}
          <button
            type="button"
            onClick={copy}
            className="p-1.5 rounded-md border border-slate-200 text-slate-500 hover:text-slate-800 hover:bg-slate-50"
            aria-label="Copy diff"
            title="Copy diff"
          >
            <Icon name="content_copy" className="text-[15px]" />
          </button>
        </div>
      </div>
      <div role="region" aria-label="Unified diff" className="whitespace-pre mt-3 bg-slate-900 text-slate-200 border border-slate-800 rounded-lg p-3.5 font-mono text-[12px] overflow-x-auto leading-relaxed shadow-inner">
        <div className="text-slate-500 mb-1 select-none">--- a/{patch.file}</div>
        <div className="text-slate-500 mb-2 select-none">+++ b/{patch.file}</div>
        <div className="text-indigo-400 bg-slate-800/80 px-2 py-0.5 rounded text-[11px] inline-block mb-1 select-none">{patch.hunk}</div>
        {patch.lines.map((line, index) => (
          <div key={index} className={LINE[line.type]}>
            {line.text}
          </div>
        ))}
      </div>
      {patch.verification && (
        <p className={`mt-3 text-[12px] flex items-center gap-1.5 ${passed ? 'text-emerald-800' : 'text-rose-800'}`}>
          <Icon name={passed ? 'task_alt' : 'error'} className="text-[16px]" />
          Re-ran the warehouse sync on the clone: touched <strong className="font-mono">{patch.verification.rowsTouchedAfter} row</strong>{' '}
          (before patch: {patch.verification.rowsTouchedBefore}).
        </p>
      )}
    </Card>
  )
}
