import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Briefcase, ChevronLeft, Pencil, UserRound } from 'lucide-react'
import { employeesApi } from '../../api/client'
import { formatDay } from '../../components/billing/BillDocument'
import { inr } from '../../components/dashboard/format'
import { formLink } from '../../components/profile/links'
import { Fact, Mark, Nothing, Section, StatusPill } from '../../components/profile/parts'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/EmptyState'
import { useAuth } from '../../context/AuthContext'
import type { EmployeeProfile } from '../../types'

/** How long someone has been here, or was: "2 years 3 months". */
function tenure(start: string | null, end: string | null): string | null {
  if (!start) return null
  const from = new Date(start)
  const to = end ? new Date(end) : new Date()
  const months = (to.getFullYear() - from.getFullYear()) * 12 + (to.getMonth() - from.getMonth())
  if (months < 1) return 'Less than a month'
  const years = Math.floor(months / 12)
  const rest = months % 12
  return [years ? `${years} ${years === 1 ? 'year' : 'years'}` : '', rest ? `${rest} ${rest === 1 ? 'month' : 'months'}` : ''].filter(Boolean).join(' ')
}

/**
 * One employee on one page: who they are, where they work, who they report to and who reports to them, and the contacts they look after. Recent pay is there only for someone
 * with bank access. It never carries the private details (Aadhaar, PAN, the agreed salary); their papers are in the Document Center.
 */
export function EmployeePage() {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [data, setData] = useState<EmployeeProfile | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    setData(null)
    employeesApi
      .get(code)
      .then((r) => live && (setData(r), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [code])

  if (error)
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        <Link to="/data/employees" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Employees
        </Link>
        <Alert variant="error">{error}</Alert>
      </div>
    )
  if (!data)
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        <Skeleton className="h-32" />
        <Skeleton className="h-64" />
      </div>
    )

  const { employee, reports, relationships, pay } = data
  const here = tenure(employee.emp_start_date, employee.emp_end_date)

  return (
    <div className="mx-auto max-w-5xl space-y-5 pb-6">
      <Link to="/data/employees" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
        <ChevronLeft className="h-4 w-4" /> Employees
      </Link>

      <header className="panel flex flex-wrap items-center gap-5 !p-5 sm:!p-6">
        <Mark name={employee.employee_name} size="lg" />
        <div className="min-w-0 flex-1 basis-64">
          <p className="eyebrow">{employee.employee_code}</p>
          <h1 className="t-h1 break-words">{employee.employee_name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs font-bold">
            <StatusPill status={employee.employee_status === 'Inactive' ? 'Left' : employee.employee_status} />
            {employee.employee_designation && <span className="rounded-full bg-accent-dim px-2.5 py-1">{employee.employee_designation}</span>}
            {employee.employee_type && <span className="rounded-full bg-muted px-2.5 py-1 text-[color:var(--color-text-muted)]">{employee.employee_type}</span>}
            {employee.client_facing && <span className="rounded-full bg-muted px-2.5 py-1 text-[color:var(--color-text-muted)]">Meets clients</span>}
            {here && <span className="font-medium text-[color:var(--color-text-muted)]">{employee.emp_end_date ? `Worked here ${here}` : `With us ${here}`}</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {employee.case_code && (
            <Button variant="secondary" onClick={() => navigate(`/data/cases/${employee.case_code}`)}>
              <Briefcase className="h-4 w-4" /> Their case
            </Button>
          )}
          {user?.can_ods_write && (
            <Button onClick={() => navigate(formLink({ entity: 'Employee', mode: 'edit', record: employee.employee_code, back: `/data/employees/${employee.employee_code}`, backLabel: 'Employee' }))}>
              <Pencil className="h-4 w-4" /> Change details
            </Button>
          )}
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="Where they work">
          {employee.case_code ? (
            <Link to={`/data/cases/${employee.case_code}`} className="interactive flex items-center gap-3 rounded-2xl border border-[color:var(--color-border)] p-3 hover:bg-muted/60">
              <Mark name={employee.case_name ?? '?'} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{employee.case_name}</span>
                <span className="t-caption block truncate text-[color:var(--color-text-muted)]">{employee.client_name ?? 'No client'}</span>
              </span>
            </Link>
          ) : (
            <Nothing>Not placed on a case.</Nothing>
          )}
          <dl className="mt-3 divide-y divide-[color:var(--color-border)]">
            <Fact label="Started" value={employee.emp_start_date ? formatDay(employee.emp_start_date) : null} />
            <Fact label="Left" value={employee.emp_end_date ? formatDay(employee.emp_end_date) : null} />
          </dl>
        </Section>

        <Section title="Reporting" hint="Who they report to, and who reports to them">
          {employee.manager_code ? (
            <Link to={`/data/employees/${employee.manager_code}`} className="interactive mb-3 flex items-center gap-3 rounded-2xl border border-[color:var(--color-border)] p-3 hover:bg-muted/60">
              <UserRound className="h-4 w-4 text-accent" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-sm">
                Reports to <span className="font-semibold">{employee.manager_name}</span>
              </span>
            </Link>
          ) : (
            <p className="t-caption mb-3 text-[color:var(--color-text-muted)]">No manager is recorded.</p>
          )}
          {reports.length === 0 ? (
            <Nothing>No one reports to them.</Nothing>
          ) : (
            <ul className="space-y-1.5">
              {reports.map((p) => (
                <li key={p.employee_code}>
                  <Link to={`/data/employees/${p.employee_code}`} className="interactive flex items-center gap-2 rounded-xl px-2 py-1.5 text-sm font-medium hover:bg-muted">
                    {p.employee_name}
                    <span className="t-caption text-[color:var(--color-text-faint)]">{p.employee_designation}</span>
                    {p.employee_status === 'Inactive' && <span className="ml-auto text-xs text-[color:var(--color-text-faint)]">Left</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>

        {relationships.length > 0 && (
          <Section title="Contacts they look after" hint="People at clients they are the relationship owner for">
            <ul className="space-y-1.5">
              {relationships.map((r) => (
                <li key={r.contact_code} className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{r.contact_name}</span>
                  {r.client_code && (
                    <Link to={`/data/clients/${r.client_code}`} className="t-caption text-accent hover:underline">
                      {r.client_code}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {pay && (
          <Section title="Recent pay" hint="Their latest salary lines (shown because you have bank access)">
            {pay.length === 0 ? (
              <Nothing>No salary has been entered for them yet.</Nothing>
            ) : (
              <ul className="divide-y divide-[color:var(--color-border)]">
                {pay.map((line, index) => (
                  <li key={`${line.month_year}-${index}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm">
                    <span className="w-20 shrink-0 font-medium">{line.month_year ?? '—'}</span>
                    <span className="min-w-0 flex-1 text-[color:var(--color-text-muted)]">{line.days_worked != null ? `${line.days_worked} days` : ''}</span>
                    <span className="font-display font-semibold tabular-nums">{line.salary_amount != null ? inr(line.salary_amount) : '—'}</span>
                    <span className={`w-16 text-right text-xs font-bold ${line.salary_paid === 'Yes' ? 'text-positive' : 'text-warning'}`}>{line.salary_paid === 'Yes' ? 'Paid' : 'To pay'}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        )}
      </div>
    </div>
  )
}
