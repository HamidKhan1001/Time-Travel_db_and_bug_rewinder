import Icon from './Icon.jsx'
import Spinner from './Spinner.jsx'

const VARIANTS = {
  primary: 'indigo-gradient-btn text-white font-bold',
  secondary:
    'bg-white border border-slate-200/90 text-slate-700 hover:bg-slate-50 hover:text-slate-900 hover:border-slate-300 font-medium shadow-xs',
  'danger-soft':
    'bg-rose-50/70 text-rose-700 border border-rose-200 hover:bg-rose-100 hover:border-rose-300 font-bold shadow-xs',
  danger: 'bg-rose-600 hover:bg-rose-700 text-white font-bold shadow-sm border border-rose-700/20',
  ghost: 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/70 font-medium',
}

const SIZES = {
  sm: 'px-3 py-1.5 text-[12px] gap-1.5',
  md: 'px-4 py-2 text-[13px] gap-1.5',
  lg: 'px-6 py-2.5 text-[14px] gap-2',
}

/** Shared button. Variants follow the button styles in the three Stitch exports. */
export default function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  iconClassName = 'text-[16px]',
  loading = false,
  loadingText,
  disabled,
  className = '',
  children,
  type = 'button',
  ...props
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center rounded-lg transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:active:scale-100 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    >
      {loading ? <Spinner className="w-3.5 h-3.5" /> : icon ? <Icon name={icon} className={iconClassName} /> : null}
      <span className="whitespace-nowrap">{loading && loadingText ? loadingText : children}</span>
    </button>
  )
}
