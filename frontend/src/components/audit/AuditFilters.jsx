import Icon from '../ui/Icon.jsx'
import SelectField from '../ui/SelectField.jsx'

const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  { value: 'applied', label: 'Applied' },
  { value: 'undone', label: 'Undone' },
  { value: 'discarded', label: 'Discarded' },
  { value: 'failed', label: 'Failed' },
]

/** Search + status + scenario filters. Changes apply on "Apply Filters" or Enter. */
export default function AuditFilters({ draft, onChange, onApply, onReset, scenarios, dirty }) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onApply()
      }}
      className="bg-white border border-surface-border rounded-xl p-3 sm:p-4 mb-5 flex flex-col lg:flex-row gap-3 items-stretch lg:items-center justify-between shadow-card"
      role="search"
    >
      <div className="flex flex-1 flex-col sm:flex-row gap-3">
        <div className="relative flex-1 group">
          <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400 group-focus-within:text-brand-600 transition-colors">
            <Icon name="search" className="text-[18px]" />
          </span>
          <input
            type="search"
            value={draft.search}
            onChange={(event) => onChange({ search: event.target.value })}
            placeholder="Search prompts, IDs, or diff signatures..."
            aria-label="Search recoveries"
            className="w-full bg-slate-50/80 hover:bg-slate-50 focus:bg-white border border-surface-border focus:border-brand-500 rounded-lg text-slate-800 pl-10 pr-4 py-2 text-xs font-mono placeholder:text-slate-400 focus:outline-none focus:ring-4 focus:ring-brand-500/10 transition-all"
          />
        </div>
        <SelectField
          className="w-full sm:w-44"
          label="Status"
          value={draft.status}
          onChange={(status) => onChange({ status })}
          options={STATUS_OPTIONS}
        />
        <SelectField
          className="w-full sm:w-52"
          label="Scenario"
          value={draft.scenario}
          onChange={(scenario) => onChange({ scenario })}
          options={[{ value: '', label: 'Scenario: All' }, ...scenarios.map((item) => ({ value: item.name, label: item.name }))]}
        />
      </div>
      <div className="flex items-center gap-2 self-end lg:self-auto">
        <button
          type="submit"
          className={`px-4 py-2 bg-brand-600 hover:bg-brand-700 active:bg-brand-800 text-white rounded-lg text-xs font-semibold shadow-sm hover:shadow-brand-500/25 transition-all duration-150 flex items-center gap-1.5 focus:ring-4 focus:ring-brand-500/20 ${
            dirty ? 'ring-4 ring-brand-500/20' : ''
          }`}
        >
          <Icon name="tune" className="text-[16px]" />
          Apply Filters
        </button>
        <button
          type="button"
          onClick={onReset}
          className="p-2 bg-slate-50 hover:bg-slate-100 border border-surface-border rounded-lg text-slate-500 hover:text-slate-800 transition-colors"
          title="Reset filters"
          aria-label="Reset filters"
        >
          <Icon name="restart_alt" className="text-[17px]" />
        </button>
      </div>
    </form>
  )
}
