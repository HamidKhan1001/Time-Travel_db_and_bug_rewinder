import { Fragment, useState } from 'react'
import Card from '../ui/Card.jsx'
import Icon from '../ui/Icon.jsx'
import RichText from '../ui/RichText.jsx'

const DECISION = {
  kept: { label: 'KEPT', className: 'bg-emerald-100 text-emerald-900 border-emerald-300' },
  resolved: { label: 'RESOLVED', className: 'bg-amber-100 text-amber-900 border-amber-300' },
  discarded: { label: 'DISCARDED', className: 'bg-rose-100 text-rose-900 border-rose-300' },
}

function DecisionBadge({ decision }) {
  const config = DECISION[decision] || DECISION.kept
  return (
    <span className={`inline-block px-2.5 py-1 rounded-md text-[11px] font-sans font-extrabold border shadow-xs tracking-wide ${config.className}`}>
      {config.label}
    </span>
  )
}

function Target({ op }) {
  return (
    <span className="inline-flex items-center gap-1 bg-indigo-50/80 px-2 py-0.5 rounded border border-indigo-200/70 text-indigo-800 font-mono font-semibold whitespace-nowrap">
      {op.target}
      {op.targetNote && <span className="text-indigo-500 font-medium">· {op.targetNote}</span>}
    </span>
  )
}

function Details({ op }) {
  return (
    <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 text-[11px] font-mono bg-slate-50 border border-slate-200/70 rounded-lg p-3">
      {op.details.map((item) => (
        <Fragment key={item.label}>
          <dt className="text-slate-400">{item.label}</dt>
          <dd className="text-slate-700">{item.value}</dd>
        </Fragment>
      ))}
    </dl>
  )
}

/** "Merge Plan & Operation Decisions" with plain-language reasons (PRD §5 step 4, §6). */
export default function MergePlanCard({ plan }) {
  const [expanded, setExpanded] = useState(null)
  const toggle = (id) => setExpanded((value) => (value === id ? null : id))

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-100">
        <div>
          <h2 className="text-[16px] font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <Icon name="alt_route" className="text-brand-600 text-[20px]" />
            Merge Plan &amp; Operation Decisions
          </h2>
          <p className="text-slate-500 text-[13px] mt-0.5">Automated resolution path calculated on isolated clone branch</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 font-mono text-[11px] font-bold border border-emerald-200 flex items-center gap-1 shadow-xs">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> {plan.stats.kept} Kept
          </span>
          <span className="px-2.5 py-1 rounded-full bg-rose-50 text-rose-700 font-mono text-[11px] font-bold border border-rose-200 flex items-center gap-1 shadow-xs">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" /> {plan.stats.discarded} Discarded
          </span>
        </div>
      </div>

      {/* Table (tablet and up) */}
      <div className="hidden md:block overflow-x-auto mt-2">
        <table className="w-full text-left font-mono text-[12px]">
          <thead>
            <tr className="text-slate-500 border-b border-slate-200/70 text-[11px] font-sans font-bold uppercase tracking-wider">
              <th className="py-3 px-3">Operation</th>
              <th className="py-3 px-3">Target Entity</th>
              <th className="py-3 px-3">Decision</th>
              <th className="py-3 px-3">Plain-Language Reason</th>
              <th className="py-3 px-1 w-8">
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {plan.operations.map((op) => (
              <Fragment key={op.id}>
                <tr
                  onClick={() => toggle(op.id)}
                  className={`cursor-pointer transition-colors ${
                    op.decision === 'resolved' ? 'bg-amber-50/30 hover:bg-amber-50/50' : 'hover:bg-slate-50/70'
                  }`}
                >
                  <td className="py-3 px-3 text-slate-900 font-bold text-[13px] whitespace-nowrap">{op.operation}</td>
                  <td className="py-3 px-3">
                    <Target op={op} />
                  </td>
                  <td className="py-3 px-3">
                    <DecisionBadge decision={op.decision} />
                  </td>
                  <td className="py-3 px-3 text-slate-700 font-sans leading-relaxed">
                    <RichText value={op.reason} />
                  </td>
                  <td className="py-3 px-1">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation()
                        toggle(op.id)
                      }}
                      aria-expanded={expanded === op.id}
                      aria-label={`${expanded === op.id ? 'Hide' : 'Show'} details for ${op.target}`}
                      className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                    >
                      <Icon name="expand_more" className={`text-[18px] transition-transform ${expanded === op.id ? 'rotate-180' : ''}`} />
                    </button>
                  </td>
                </tr>
                {expanded === op.id && (
                  <tr className="bg-white">
                    <td colSpan={5} className="px-3 pb-3 pt-0">
                      <Details op={op} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      {/* Cards (mobile) */}
      <ul className="md:hidden flex flex-col gap-2.5 mt-3">
        {plan.operations.map((op) => (
          <li
            key={op.id}
            className={`rounded-lg border p-3 flex flex-col gap-2 ${op.decision === 'resolved' ? 'bg-amber-50/40 border-amber-200' : 'bg-white border-slate-200/80'}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono font-bold text-[12px] text-slate-900">{op.operation}</span>
              <DecisionBadge decision={op.decision} />
            </div>
            <div className="text-[12px]">
              <Target op={op} />
            </div>
            <p className="text-[12px] text-slate-700 leading-relaxed">
              <RichText value={op.reason} />
            </p>
            <button
              type="button"
              onClick={() => toggle(op.id)}
              aria-expanded={expanded === op.id}
              className="self-start -ml-1 px-1 py-1.5 min-h-[32px] text-[12px] font-medium text-brand-600 flex items-center gap-0.5 rounded hover:bg-brand-50"
            >
              {expanded === op.id ? 'Hide details' : 'Show details'}
              <Icon name="expand_more" className={`text-[16px] transition-transform ${expanded === op.id ? 'rotate-180' : ''}`} />
            </button>
            {expanded === op.id && <Details op={op} />}
          </li>
        ))}
      </ul>
    </Card>
  )
}
