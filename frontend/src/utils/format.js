/** Risk score 0–1 → band. Bands are an assumption until the backend defines them. */
export function riskLevel(score) {
  if (score === null || score === undefined) return { label: '—', tone: 'slate' }
  if (score < 0.34) return { label: 'Low', tone: 'emerald' }
  if (score < 0.67) return { label: 'Medium', tone: 'amber' }
  return { label: 'High', tone: 'rose' }
}

/** 0.22 → "22" (the Review screen shows risk on a 0–100 scale). */
export const riskPercent = (score) => Math.round((score ?? 0) * 100)

export function formatDateTime(iso) {
  if (!iso) return { date: '—', time: '' }
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return { date: iso, time: '' }
  const pad = (n) => String(n).padStart(2, '0')
  return {
    date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`,
  }
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

export const formatNumber = (value) => (value === null || value === undefined ? '—' : value.toLocaleString('en-US'))

export function formatDelta(value) {
  if (!value) return '—'
  return `${value > 0 ? '+' : '−'}${Math.abs(value).toLocaleString('en-US')}`
}

export const AUDIT_STATUS = {
  applied: { label: 'Applied', tone: 'emerald' },
  undone: { label: 'Undone', tone: 'indigo' },
  discarded: { label: 'Discarded', tone: 'slate' },
  failed: { label: 'Failed', tone: 'rose' },
}
