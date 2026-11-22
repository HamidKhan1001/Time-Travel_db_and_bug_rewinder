import Icon from './Icon.jsx'

/** Native select styled like the Audit log filters (unfold icon on the right). */
export default function SelectField({ value, onChange, options, label, className = '', selectClassName = '', ...props }) {
  return (
    <div className={`relative ${className}`}>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={label}
        className={`w-full bg-slate-50/80 hover:bg-slate-50 focus:bg-white border border-surface-border focus:border-brand-500 rounded-lg text-slate-700 pl-3.5 pr-8 py-2 text-xs font-medium appearance-none bg-none focus:outline-none focus:ring-4 focus:ring-brand-500/10 transition-all cursor-pointer ${selectClassName}`}
        {...props}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="absolute inset-y-0 right-0 pr-2.5 flex items-center pointer-events-none text-slate-400">
        <Icon name="unfold_more" className="text-[18px]" />
      </span>
    </div>
  )
}
