import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronLeft, Search } from 'lucide-react'
import { casesApi } from '../../api/client'
import { inr } from '../../components/dashboard/format'
import { Mark } from '../../components/profile/parts'
import { Alert } from '../../components/ui/Alert'
import { EmptyState, Skeleton } from '../../components/ui/EmptyState'
import type { CaseDirectoryRow } from '../../types'

type Show = 'active' | 'owing' | 'all'

/** Every case, as cards: its client, how many people are on it and (for someone who may see billing) what it owes. Opening one shows the case's page. */
export function CasesPage() {
  const navigate = useNavigate()
  const [typed, setTyped] = useState('')
  const [search, setSearch] = useState('')
  const [show, setShow] = useState<Show>('active')
  const [cases, setCases] = useState<CaseDirectoryRow[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(typed.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [typed])

  useEffect(() => {
    let live = true
    casesApi
      .list(search)
      .then((r) => live && (setCases(r.cases), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [search])

  const hasMoney = Boolean(cases?.some((c) => c.owed !== undefined))
  const shown = useMemo(() => (cases ?? []).filter((c) => (show === 'active' ? c.case_status !== 'Inactive' : show === 'owing' ? (c.owed ?? 0) > 0 : true)), [cases, show])
  const owing = (cases ?? []).filter((c) => (c.owed ?? 0) > 0).length
  const chips: { id: Show; label: string }[] = [
    { id: 'active', label: 'Active' },
    ...(hasMoney ? [{ id: 'owing' as const, label: `Owing ${owing}` }] : []),
    { id: 'all', label: 'Everything' },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-6">
      <div>
        <Link to="/data/orion" className="interactive mb-2 inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Data
        </Link>
        <p className="eyebrow">Orion data</p>
        <h1 className="t-h1">Cases</h1>
        <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">Every site and contract we run. Open one to see who works there, who we deal with, what has been spent{hasMoney ? ' and what it has billed' : ''}.</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
          <span className="sr-only">Find a case</span>
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Find a case or client" className="h-11 w-full rounded-full pr-4 text-sm" style={{ paddingLeft: '2.75rem' }} />
        </label>
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              aria-pressed={show === chip.id}
              onClick={() => setShow(chip.id)}
              className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${show === chip.id ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {!cases && !error && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      )}
      {cases && shown.length === 0 && <EmptyState compact title="No case matches">Try another name, or choose Everything.</EmptyState>}

      {shown.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Cases">
          {shown.map((c) => (
            <li key={c.case_code}>
              <button type="button" onClick={() => navigate(`/data/cases/${c.case_code}`)} className="panel interactive flex h-full w-full items-start gap-4 !p-4 text-left focus-visible:ring-2 focus-visible:ring-accent">
                <Mark name={c.case_name} />
                <span className="min-w-0 flex-1">
                  <span className="font-display block truncate text-base font-semibold">{c.case_name}</span>
                  <span className="t-caption block truncate text-[color:var(--color-text-muted)]">{c.client_name ?? 'No client'}</span>
                  <span className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] font-bold">
                    {c.case_status === 'Inactive' && <span className="rounded-full bg-muted px-2 py-0.5 text-[color:var(--color-text-muted)]">Inactive</span>}
                    <span className="rounded-full bg-accent-dim px-2 py-0.5">
                      {c.employees} {c.employees === 1 ? 'person' : 'people'}
                    </span>
                    <span className="font-medium text-[color:var(--color-text-faint)]">{c.case_code}</span>
                  </span>
                </span>
                {c.owed !== undefined && (
                  <span className="shrink-0 text-right">
                    <span className={`font-display block text-lg font-semibold tabular-nums ${c.owed > 0 ? '' : 'text-[color:var(--color-text-faint)]'}`}>{c.owed > 0 ? inr(c.owed) : '—'}</span>
                    <span className="t-caption block text-[color:var(--color-text-faint)]">{c.owed > 0 ? `owed${c.oldest_days != null ? ` · ${c.oldest_days}d` : ''}` : 'nothing owed'}</span>
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
