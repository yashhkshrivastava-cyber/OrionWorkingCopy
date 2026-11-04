import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CalendarCheck, ChevronLeft, FolderArchive, Mail, MapPin, Pencil, Phone, Plus, Star } from 'lucide-react'
import { casesApi } from '../../api/client'
import { BillNumber } from '../../components/billing/BillNumber'
import { formatDay, formatMonth } from '../../components/billing/BillDocument'
import { StatTile } from '../../components/billing/StatTile'
import { inr } from '../../components/dashboard/format'
import { formLink } from '../../components/profile/links'
import { Fact, Mark, Nothing, Section, StatusPill } from '../../components/profile/parts'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/EmptyState'
import { useAuth } from '../../context/AuthContext'
import type { CaseProfile } from '../../types'

/**
 * One case on one page: the site, the people who work there, the people we deal with, the deposits and expenses against it and, for someone who may see billing, what it has
 * billed and what is still owed. Everything is read from where it lives; the buttons lead to the places that change it.
 */
export function CasePage() {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [data, setData] = useState<CaseProfile | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    setData(null)
    casesApi
      .get(code)
      .then((r) => live && (setData(r), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [code])

  if (error)
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Link to="/data/cases" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Cases
        </Link>
        <Alert variant="error">{error}</Alert>
      </div>
    )
  if (!data)
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Skeleton className="h-32" />
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    )

  const { case: site, people, contacts, emds, expenses, money } = data
  const active = people.filter((p) => p.employee_status !== 'Inactive')

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-6">
      <Link to="/data/cases" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
        <ChevronLeft className="h-4 w-4" /> Cases
      </Link>

      <header className="panel flex flex-wrap items-center gap-5 !p-5 sm:!p-6">
        <Mark name={site.case_name} size="lg" />
        <div className="min-w-0 flex-1 basis-64">
          <p className="eyebrow">{site.case_code}</p>
          <h1 className="t-h1 break-words">{site.case_name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs font-bold">
            <StatusPill status={site.case_status} />
            {site.client_name && (
              <Link to={`/data/clients/${site.client_code}`} className="rounded-full bg-accent-dim px-2.5 py-1 hover:underline">
                {site.client_name}
              </Link>
            )}
            {site.capability_name && <span className="rounded-full bg-muted px-2.5 py-1 text-[color:var(--color-text-muted)]">{site.capability_name}</span>}
            {site.business_domain_name && <span className="rounded-full bg-muted px-2.5 py-1 text-[color:var(--color-text-muted)]">{site.business_domain_name}</span>}
            {site.case_start_date && (
              <span className="inline-flex items-center gap-1 font-medium text-[color:var(--color-text-muted)]">
                <MapPin className="h-3.5 w-3.5" aria-hidden="true" /> since {formatDay(site.case_start_date)}
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {user?.pages.includes('documents') && (
            <Button variant="secondary" onClick={() => navigate(`/documents?node=case:${site.case_code}`)}>
              <FolderArchive className="h-4 w-4" /> Documents
            </Button>
          )}
          {user?.pages.includes('attendance') && (
            <Button variant="secondary" onClick={() => navigate('/attendance')}>
              <CalendarCheck className="h-4 w-4" /> Attendance
            </Button>
          )}
          {user?.can_ods_write && (
            <>
              <Button variant="secondary" onClick={() => navigate(formLink({ entity: 'Expense Transaction', mode: 'create', fill: { case_code: site.case_code }, back: `/data/cases/${site.case_code}`, backLabel: 'Case' }))}>
                <Plus className="h-4 w-4" /> Add an expense
              </Button>
              <Button onClick={() => navigate(formLink({ entity: 'Case', mode: 'edit', record: site.case_code, back: `/data/cases/${site.case_code}`, backLabel: 'Case' }))}>
                <Pencil className="h-4 w-4" /> Change details
              </Button>
            </>
          )}
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {money ? (
          <>
            <StatTile label="Billed" text={inr(money.billed)} hint={`${money.bills} ${money.bills === 1 ? 'bill' : 'bills'}${money.credited ? ` · ${inr(money.credited)} credited` : ''}`} />
            <StatTile label="Owed now" text={money.owed > 0 ? inr(money.owed) : '₹0'} hint={money.owed > 0 ? (money.oldest_days != null ? `Oldest is ${money.oldest_days} days` : 'Unpaid bills') : 'Nothing is owed'} tone={money.owed > 0 ? 'text-warning' : 'text-positive'} />
          </>
        ) : (
          <>
            <StatTile label="People on it" text={String(active.length)} hint={`${people.length - active.length} left or inactive`} />
            <StatTile label="Contacts" text={String(contacts.length)} hint="People we deal with" />
          </>
        )}
        <StatTile label="Spent so far" text={inr(expenses.total)} hint={`${expenses.count} ${expenses.count === 1 ? 'expense' : 'expenses'}, paid or owed`} />
        <StatTile label="Expected a month" text={site.monthly_expected_revenue != null ? inr(site.monthly_expected_revenue) : '—'} hint={site.monthly_allowed_km ? `${site.monthly_allowed_km} km allowed` : 'Revenue planned for this case'} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-5">
          <Section title="People on this case" hint={`${active.length} working here`}>
            {people.length === 0 ? (
              <Nothing>No employee is placed on this case.</Nothing>
            ) : (
              <ul className="grid gap-2.5 sm:grid-cols-2">
                {people.map((p) => (
                  <li key={p.employee_code}>
                    <Link to={`/data/employees/${p.employee_code}`} className="interactive flex items-center gap-3 rounded-2xl border border-[color:var(--color-border)] p-3 hover:bg-muted/60">
                      <Mark name={p.employee_name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{p.employee_name}</span>
                        <span className="t-caption block truncate text-[color:var(--color-text-muted)]">{[p.employee_designation, p.employee_type].filter(Boolean).join(' · ') || p.employee_code}</span>
                      </span>
                      {p.employee_status === 'Inactive' && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold text-[color:var(--color-text-muted)]">Left</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {money && (
            <Section title="Recent bills" hint={money.bills ? `Latest ${money.recent.length} of ${money.bills}` : undefined}>
              {money.recent.length === 0 ? (
                <Nothing>No bill has been raised for this case yet.</Nothing>
              ) : (
                <ul className="divide-y divide-[color:var(--color-border)]">
                  {money.recent.map((bill) => {
                    const open = Math.max(0, bill.grand_total - (bill.credited_amount ?? 0) - bill.received_total)
                    const cancelled = bill.status === 'Cancelled'
                    return (
                      <li key={bill.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-sm">
                        <BillNumber number={bill.bill_number} code={bill.id} className={`min-w-[7rem] font-semibold ${cancelled ? 'line-through' : ''}`} />
                        <span className="min-w-0 flex-1 truncate text-[color:var(--color-text-muted)]">{formatMonth(bill.service_month)}</span>
                        <span className="font-display font-semibold tabular-nums">{inr(bill.grand_total)}</span>
                        <span className={`w-24 text-right text-xs font-bold ${cancelled ? 'text-negative' : open > 0 ? 'text-warning' : 'text-positive'}`}>{cancelled ? 'Cancelled' : open > 0 ? `${inr(open)} due` : 'Settled'}</span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Section>
          )}

          <Section title="Recent expenses" hint={expenses.count ? `Latest ${expenses.recent.length} of ${expenses.count}` : undefined}>
            {expenses.recent.length === 0 ? (
              <Nothing>No expense has been recorded against this case.</Nothing>
            ) : (
              <ul className="divide-y divide-[color:var(--color-border)]">
                {expenses.recent.map((x) => (
                  <li key={x.expense_code} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-sm">
                    <span className="w-24 shrink-0 text-xs tabular-nums text-[color:var(--color-text-muted)]">{x.transaction_date ? formatDay(x.transaction_date) : '—'}</span>
                    <span className="min-w-0 flex-1 truncate">
                      <span className="font-medium">{x.expense_type ?? 'Expense'}</span>
                      {x.description ? <span className="text-[color:var(--color-text-muted)]"> · {x.description}</span> : null}
                    </span>
                    <span className="font-display font-semibold tabular-nums">{x.amount != null ? inr(x.amount) : '—'}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        <div className="min-w-0 space-y-5">
          <Section title="People we deal with" hint="Contacts for this site, and the client's main contact">
            {contacts.length === 0 ? (
              <Nothing>No contact is recorded for this case.</Nothing>
            ) : (
              <ul className="space-y-2.5">
                {contacts.map((person) => (
                  <li key={person.contact_code} className="rounded-2xl border border-[color:var(--color-border)] p-3">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">{person.contact_name}</span>
                      {person.is_primary_contact === 'Yes' && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-accent-dim px-2 py-0.5 text-[11px] font-bold">
                          <Star className="h-3 w-3" aria-hidden="true" /> Main contact
                        </span>
                      )}
                    </p>
                    <p className="t-caption text-[color:var(--color-text-muted)]">{[person.designation, person.contact_role].filter(Boolean).join(' · ')}</p>
                    <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                      {person.phone && (
                        <a href={`tel:${person.phone}`} className="inline-flex items-center gap-1 text-accent hover:underline">
                          <Phone className="h-3.5 w-3.5" aria-hidden="true" /> {person.phone}
                        </a>
                      )}
                      {person.email && (
                        <a href={`mailto:${person.email}`} className="inline-flex min-w-0 items-center gap-1 text-accent hover:underline">
                          <Mail className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> <span className="truncate">{person.email}</span>
                        </a>
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Deposits" hint="Earnest money put up for this case">
            {emds.length === 0 ? (
              <Nothing>No EMD is recorded for this case.</Nothing>
            ) : (
              <ul className="space-y-2">
                {emds.map((e) => (
                  <li key={e.emd_code} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-2xl border border-[color:var(--color-border)] p-3 text-sm">
                    <span className="font-display font-semibold tabular-nums">{inr(e.emd_amount)}</span>
                    <span className="text-xs font-bold text-[color:var(--color-text-muted)]">{e.emd_status ?? 'Deposited'}</span>
                    <span className="t-caption w-full text-[color:var(--color-text-muted)]">
                      {[e.tender_reference ? `Tender ${e.tender_reference}` : '', e.deposit_date ? `deposited ${formatDay(e.deposit_date)}` : '', e.refund_due_date ? `refund due ${formatDay(e.refund_due_date)}` : ''].filter(Boolean).join(' · ') || e.emd_code}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Details">
            <dl className="divide-y divide-[color:var(--color-border)]">
              <Fact label="Client" value={site.client_name} />
              <Fact label="Service" value={site.capability_name} />
              <Fact label="Domain" value={site.business_domain_name} />
              <Fact label="Started" value={site.case_start_date ? formatDay(site.case_start_date) : null} />
              <Fact label="Ended" value={site.case_end_date ? formatDay(site.case_end_date) : null} />
            </dl>
          </Section>
        </div>
      </div>
    </div>
  )
}
