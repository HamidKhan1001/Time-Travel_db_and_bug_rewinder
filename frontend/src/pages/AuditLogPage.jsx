import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getAuditLog, getAuditSummary } from '../services/api.js'
import { errorMessage } from '../services/errors.js'
import { useDemo } from '../context/DemoContext.jsx'
import { usePageTitle } from '../hooks/usePageTitle.js'
import { AUDIT_PAGE_SIZE } from '../constants/defaults.js'
import AuditSummaryCards from '../components/audit/AuditSummaryCards.jsx'
import AuditFilters from '../components/audit/AuditFilters.jsx'
import AuditTable from '../components/audit/AuditTable.jsx'
import Pagination from '../components/audit/Pagination.jsx'
import AuditDetailDrawer from '../components/audit/AuditDetailDrawer.jsx'
import Button from '../components/ui/Button.jsx'
import Icon from '../components/ui/Icon.jsx'
import { EmptyState, ErrorBanner } from '../components/ui/StateBlocks.jsx'

/** Audit log list (Stitch export: audit-log-list). Filters, page and open record live in the URL. */
export default function AuditLogPage() {
  usePageTitle('Audit log')
  const navigate = useNavigate()
  const { scenarios, auditCount } = useDemo()
  const [params, setParams] = useSearchParams()

  const applied = useMemo(
    () => ({
      search: params.get('q') || '',
      status: params.get('status') || '',
      scenario: params.get('scenario') || '',
      page: Math.max(1, Number(params.get('page')) || 1),
    }),
    [params],
  )
  const openId = params.get('recovery')

  const [draft, setDraft] = useState({ search: applied.search, status: applied.status, scenario: applied.scenario })
  const [list, setList] = useState({ status: 'loading', data: null, error: null })
  const [summary, setSummary] = useState({ status: 'loading', data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    setDraft({ search: applied.search, status: applied.status, scenario: applied.scenario })
  }, [applied.search, applied.status, applied.scenario])

  // Load the page of results whenever the applied filters change.
  useEffect(() => {
    let cancelled = false
    setList((value) => ({ ...value, status: 'loading', error: null }))
    getAuditLog({ ...applied, pageSize: AUDIT_PAGE_SIZE })
      .then((data) => !cancelled && setList({ status: 'ready', data, error: null }))
      .catch((error) => !cancelled && setList({ status: 'error', data: null, error: errorMessage(error) }))
    return () => {
      cancelled = true
    }
  }, [applied, attempt, auditCount])

  useEffect(() => {
    let cancelled = false
    setSummary({ status: 'loading', data: null, error: null })
    getAuditSummary()
      .then((data) => !cancelled && setSummary({ status: 'ready', data, error: null }))
      .catch((error) => !cancelled && setSummary({ status: 'error', data: null, error: errorMessage(error) }))
    return () => {
      cancelled = true
    }
  }, [attempt, auditCount])

  const updateParams = useCallback(
    (next) => {
      const merged = new URLSearchParams(params)
      Object.entries(next).forEach(([key, value]) => {
        if (value === '' || value === null || value === undefined || (key === 'page' && value === 1)) merged.delete(key)
        else merged.set(key, String(value))
      })
      setParams(merged)
    },
    [params, setParams],
  )

  const applyFilters = () => updateParams({ q: draft.search.trim(), status: draft.status, scenario: draft.scenario, page: 1 })
  const resetFilters = () => {
    setDraft({ search: '', status: '', scenario: '' })
    updateParams({ q: '', status: '', scenario: '', page: 1 })
  }
  const hasFilters = Boolean(applied.search || applied.status || applied.scenario)
  const dirty = draft.search.trim() !== applied.search || draft.status !== applied.status || draft.scenario !== applied.scenario
  const items = list.data?.items || []

  return (
    <div className="flex flex-col w-full min-h-[calc(100vh-3.5rem)] p-4 sm:p-6 lg:p-8 max-w-[1440px] mx-auto">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-7">
        <div>
          <div className="flex items-center gap-1.5 text-xs font-mono font-semibold tracking-wider text-brand-600 uppercase mb-2">
            <Icon name="terminal" className="text-[15px]" />
            <span>Telemetry Archive // S10</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
            Audit log
            <span className="text-xs font-mono font-medium px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-600 border border-slate-200/80">
              v{__APP_VERSION__}
            </span>
          </h1>
          <p className="text-slate-500 text-sm mt-1.5 max-w-xl">Every time-travel recovery, what it changed, and its outcome.</p>
        </div>
        <AuditSummaryCards summary={summary} />
      </div>

      <AuditFilters
        draft={draft}
        dirty={dirty}
        onChange={(patch) => setDraft((value) => ({ ...value, ...patch }))}
        onApply={applyFilters}
        onReset={resetFilters}
        scenarios={scenarios.data}
      />

      <div className="bg-white border border-surface-border rounded-xl shadow-card overflow-hidden">
        {list.status === 'error' ? (
          <div className="p-4">
            <ErrorBanner title="Couldn't load the audit log" message={list.error} onRetry={() => setAttempt((n) => n + 1)} />
          </div>
        ) : list.status === 'ready' && items.length === 0 ? (
          hasFilters ? (
            <EmptyState
              icon="filter_alt_off"
              title="No recoveries match these filters"
              body="Try a different search or clear the filters."
              action={
                <Button variant="secondary" icon="restart_alt" onClick={resetFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon="history_toggle_off"
              title="No recoveries yet"
              body="Run a time-travel recovery from the Console and it will be recorded here."
              action={
                <Button variant="primary" icon="arrow_back" onClick={() => navigate('/console')}>
                  Go to Console
                </Button>
              }
            />
          )
        ) : (
          <>
            <AuditTable items={items} loading={list.status === 'loading' && !list.data} onOpen={(id) => updateParams({ recovery: id })} highlightId={openId} />
            {list.data && (
              <Pagination
                page={list.data.page}
                pageSize={list.data.pageSize}
                total={list.data.total}
                disabled={list.status === 'loading'}
                onPage={(page) => updateParams({ page })}
              />
            )}
          </>
        )}
      </div>

      <AuditDetailDrawer id={openId} onClose={() => updateParams({ recovery: '' })} />
    </div>
  )
}
