import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDemo } from '../../context/DemoContext.jsx'
import { DEFAULT_PROMPT } from '../../constants/defaults.js'
import Button from '../ui/Button.jsx'
import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'

const STATUS_PILL = {
  idle: 'AI Agent Ready',
  failed: 'AI Agent Ready',
  running: 'Running on clone…',
  review: 'Plan ready',
  live: 'Recovery live',
}

/** "Recovery Composer" card: the time-travel prompt (PRD §5 step 3). */
export default function RecoveryComposer() {
  const { recovery, runTimeTravel, snapshot } = useDemo()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [touched, setTouched] = useState(false)
  const running = recovery.status === 'running'
  const empty = !prompt.trim()
  const planPending = recovery.status === 'review'
  const isLive = recovery.status === 'live'

  const submit = async (event) => {
    event?.preventDefault()
    setTouched(true)
    if (empty || running || planPending || isLive) return
    const plan = await runTimeTravel(prompt)
    if (plan) navigate('/console/review')
  }

  return (
    <Card as="form" onSubmit={submit} className="p-5 flex flex-col gap-4 !border-indigo-200/70 relative overflow-hidden">
      <div className="absolute -top-12 -right-12 w-36 h-36 bg-gradient-to-br from-indigo-200/40 via-purple-200/30 to-transparent rounded-full blur-2xl pointer-events-none" />
      <div className="flex items-center justify-between gap-2 relative z-10">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shadow-xs">
            <Icon name="history_toggle_off" className="text-[17px]" />
          </div>
          <h2 className="font-bold text-slate-800 text-[14px]">Recovery Composer</h2>
        </div>
        <span className="px-2.5 py-0.5 rounded-full bg-gradient-to-r from-indigo-50 to-purple-50 text-indigo-700 border border-indigo-200/70 text-[11px] font-bold tracking-tight shadow-xs whitespace-nowrap">
          {STATUS_PILL[recovery.status]}
        </span>
      </div>

      <div className="flex flex-col gap-2 relative z-10">
        <label htmlFor="correction-prompt" className="text-[12px] font-semibold text-slate-700 flex items-center justify-between">
          <span>Correction Prompt</span>
          <span className="text-[10px] font-mono text-slate-400 font-normal">Target commit: #88f2</span>
        </label>
        <textarea
          id="correction-prompt"
          rows={5}
          value={prompt}
          onChange={(event) => {
            setPrompt(event.target.value)
            setTouched(true)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit(event)
          }}
          disabled={running}
          aria-invalid={touched && empty}
          aria-describedby="prompt-help"
          className={`w-full bg-slate-50/90 hover:bg-slate-50 focus:bg-white text-slate-800 p-3 rounded-lg font-mono text-[12px] leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 border transition-all resize-none shadow-xs disabled:opacity-70 ${
            touched && empty ? 'border-rose-300' : 'border-slate-200'
          }`}
        />
        <span id="prompt-help" className={`text-[11px] leading-normal ${touched && empty ? 'text-rose-600' : 'text-slate-500'}`}>
          {touched && empty
            ? 'Describe what went wrong first, e.g. "the warehouse sync at 02:14 wiped inventory".'
            : 'Natural language instructions for state reconstruction and transaction rollback.'}
        </span>
      </div>

      {planPending ? (
        <Button variant="primary" icon="fact_check" className="w-full !py-3 relative z-10" onClick={() => navigate('/console/review')}>
          Review recovery plan
        </Button>
      ) : (
        <Button
          type="submit"
          variant="primary"
          icon="play_arrow"
          iconClassName="text-[18px]"
          className="w-full !py-3 relative z-10"
          loading={running}
          loadingText="Running time-travel…"
          disabled={empty || !snapshot.data || isLive}
          title={
            isLive
              ? `Recovery ${recovery.applied?.id} is live. Undo it or reset the demo before starting another.`
              : empty
                ? 'Enter a description first'
                : 'Ctrl/⌘ + Enter'
          }
        >
          Run time-travel
        </Button>
      )}
    </Card>
  )
}
