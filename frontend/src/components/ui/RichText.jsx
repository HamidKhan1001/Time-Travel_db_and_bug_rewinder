const TONES = {
  strong: 'text-slate-900 font-bold',
  success: 'text-emerald-700 font-bold',
  warning: 'text-amber-800 font-bold',
  danger: 'text-rose-700 font-bold',
}

/**
 * Renders a plain string, or an array of { text, tone } segments
 * (how the mock data emphasises words in plain-language reasons).
 */
export default function RichText({ value }) {
  if (!value) return null
  if (typeof value === 'string') return value
  return value.map((segment, index) =>
    segment.tone ? (
      <strong key={index} className={TONES[segment.tone]}>
        {segment.text}
      </strong>
    ) : (
      <span key={index}>{segment.text}</span>
    ),
  )
}
