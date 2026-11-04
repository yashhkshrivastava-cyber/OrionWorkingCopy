import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronLeft, Search } from 'lucide-react'
import { employeesApi } from '../../api/client'
import { Mark } from '../../components/profile/parts'
import { Alert } from '../../components/ui/Alert'
import { EmptyState, Skeleton } from '../../components/ui/EmptyState'
import type { EmployeeDirectoryRow } from '../../types'

type Show = 'active' | 'all'

/** Everyone who works for the company, as cards: their designation, the case and client they are on, and who they report to. Nothing private (Aadhaar, PAN, salary) is on it. */
export function EmployeesPage() {
  const navigate = useNavigate()
  const [typed, setTyped] = useState('')
  const [search, setSearch] = useState('')
  const [show, setShow] = useState<Show>('active')
  const [people, setPeople] = useState<EmployeeDirectoryRow[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(typed.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [typed])

  useEffect(() => {
    let live = true
    employeesApi
      .list(search)
      .then((r) => live && (setPeople(r.employees), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [search])

  const shown = useMemo(() => (people ?? []).filter((p) => show === 'all' || p.employee_status !== 'Inactive'), [people, show])

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-6">
      <div>
        <Link to="/data/orion" className="interactive mb-2 inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Data
        </Link>
        <p className="eyebrow">Orion data</p>
        <h1 className="t-h1">Employees</h1>
        <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">Everyone who works for the company. Open someone to see where they work and who they report to.</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
          <span className="sr-only">Find an employee</span>
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Find a name, designation, case or client" className="h-11 w-full rounded-full pr-4 text-sm" style={{ paddingLeft: '2.75rem' }} />
        </label>
        <div role="group" aria-label="Show" className="flex gap-2">
          {(['active', 'all'] as const).map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={show === id}
              onClick={() => setShow(id)}
              className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${show === id ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {id === 'active' ? 'Working now' : 'Everyone'}
            </button>
          ))}
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {!people && !error && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      )}
      {people && shown.length === 0 && <EmptyState compact title="No one matches">Try another word, or choose Everyone.</EmptyState>}

      {shown.length > 0 && (
        <>
          <p className="t-caption text-[color:var(--color-text-muted)]">
            {shown.length} {shown.length === 1 ? 'person' : 'people'}
            {people && people.length >= 500 ? ' (the first 500; search to narrow it)' : ''}
          </p>
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Employees">
            {shown.map((p) => (
              <li key={p.employee_code}>
                <button type="button" onClick={() => navigate(`/data/employees/${p.employee_code}`)} className="panel interactive flex h-full w-full items-start gap-4 !p-4 text-left focus-visible:ring-2 focus-visible:ring-accent">
                  <Mark name={p.employee_name} />
                  <span className="min-w-0 flex-1">
                    <span className="font-display block truncate text-base font-semibold">{p.employee_name}</span>
                    <span className="t-caption block truncate text-[color:var(--color-text-muted)]">{[p.employee_designation, p.employee_type].filter(Boolean).join(' · ') || p.employee_code}</span>
                    <span className="t-caption mt-1 block truncate text-[color:var(--color-text-faint)]">{[p.case_name, p.client_name].filter(Boolean).join(' · ') || 'Not placed on a case'}</span>
                    <span className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] font-bold">
                      {p.employee_status === 'Inactive' && <span className="rounded-full bg-muted px-2 py-0.5 text-[color:var(--color-text-muted)]">Left</span>}
                      {p.client_facing && <span className="rounded-full bg-accent-dim px-2 py-0.5">Meets clients</span>}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
