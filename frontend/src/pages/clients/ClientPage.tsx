import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Briefcase, ChevronLeft, FileText, FolderArchive, Mail, MapPin, Pencil, Phone, Plus, Star, Users } from 'lucide-react'
import { clientsApi } from '../../api/client'
import { BillNumber } from '../../components/billing/BillNumber'
import { formatDay, formatMonth } from '../../components/billing/BillDocument'
import { StatTile } from '../../components/billing/StatTile'
import { inr } from '../../components/dashboard/format'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Skeleton } from '../../components/ui/EmptyState'
import { useAuth } from '../../context/AuthContext'
import type { ClientProfile } from '../../types'
import { formLink } from '../../components/profile/links'
import { Fact, Mark, Section } from '../../components/profile/parts'

/** Older money is hotter, as on the Outstanding page. */
const BUCKET_HUE = ['teal', 'amber', 'orange', 'coral']

/**
 * One client on one page: who they are, the cases we run for them, the people we deal with and, for someone who may see billing, what has been billed, what has come in
 * and what is still owed. Everything on it is read from where it lives; a change is made in the place that owns it, and the buttons here lead there.
 */
export function ClientPage() {
  const { code = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [data, setData] = useState<ClientProfile | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    setData(null)
    clientsApi
      .get(code)
      .then((r) => live && (setData(r), setError('')))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [code])

  const canWrite = Boolean(user?.can_ods_write)

  if (error) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Link to="/data/clients" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Clients
        </Link>
        <Alert variant="error">{error}</Alert>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Skeleton className="h-32" />
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  const { client, cases, contacts, members, money } = data
  const place = [client.client_location_city, client.client_location_state].filter(Boolean).join(', ')
  const totalBucket = money ? money.buckets.reduce((sum, value) => sum + value, 0) : 0

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-6">
      <Link to="/data/clients" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
        <ChevronLeft className="h-4 w-4" /> Clients
      </Link>

      <header className="panel flex flex-wrap items-center gap-5 !p-5 sm:!p-6">
        <Mark name={client.client_name} size="lg" />
        <div className="min-w-0 flex-1 basis-64">
          <p className="eyebrow">{client.client_code}</p>
          <h1 className="t-h1 break-words">{client.client_name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-xs font-bold">
            <span className={`rounded-full px-2.5 py-1 ${client.client_status === 'Inactive' ? 'bg-muted text-[color:var(--color-text-muted)]' : 'bg-positive-dim text-positive'}`}>{client.client_status ?? 'Active'}</span>
            {client.client_type && <span className="rounded-full bg-accent-dim px-2.5 py-1">{client.client_type}</span>}
            {client.firm_priority && <span className="rounded-full bg-muted px-2.5 py-1 text-[color:var(--color-text-muted)]">Priority {client.firm_priority}</span>}
            {client.group_name && (
              <Link to={`/data/clients/${client.client_group_code}`} className="rounded-full bg-muted px-2.5 py-1 text-[color:var(--color-text-muted)] hover:underline">
                Group: {client.group_name}
              </Link>
            )}
            {place && (
              <span className="inline-flex items-center gap-1 font-medium text-[color:var(--color-text-muted)]">
                <MapPin className="h-3.5 w-3.5" aria-hidden="true" /> {place}
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {user?.pages.includes('documents') && (
            <Button variant="secondary" onClick={() => navigate(`/documents?node=client:${client.client_code}`)}>
              <FolderArchive className="h-4 w-4" /> Documents
            </Button>
          )}
          {money && money.owed > 0 && (
            <Button variant="secondary" onClick={() => navigate('/utility/receivables')}>
              <FileText className="h-4 w-4" /> Outstanding
            </Button>
          )}
          {canWrite && (
            <>
              <Button variant="secondary" onClick={() => navigate(formLink({ entity: 'Case', mode: 'create', fill: { client_code: client.client_code }, back: `/data/clients/${client.client_code}`, backLabel: 'Client' }))}>
                <Plus className="h-4 w-4" /> Add a case
              </Button>
              <Button onClick={() => navigate(formLink({ entity: 'Client', mode: 'edit', record: client.client_code, back: `/data/clients/${client.client_code}`, backLabel: 'Client' }))}>
                <Pencil className="h-4 w-4" /> Change details
              </Button>
            </>
          )}
        </div>
      </header>

      {money && (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <StatTile label="Billed" text={inr(money.billed)} hint={`${money.bills} ${money.bills === 1 ? 'bill' : 'bills'}${money.credited ? ` · ${inr(money.credited)} credited` : ''}`} />
            <StatTile label="Received" text={inr(money.received)} hint="Cash, before TDS and other deductions" tone="text-positive" />
            <StatTile label="Owed now" text={money.owed > 0 ? inr(money.owed) : '₹0'} hint={money.owed > 0 ? (money.last_reminder ? `Reminded ${formatDay(money.last_reminder)}` : 'Never reminded') : 'Nothing is owed'} tone={money.owed > 0 ? 'text-warning' : 'text-positive'} />
            <StatTile label="Oldest unpaid" text={money.oldest_days != null ? `${money.oldest_days} days` : '—'} hint={money.oldest_days != null ? 'Since its bill date' : 'No unpaid bill'} tone={(money.oldest_days ?? 0) > 60 ? 'text-negative' : ''} />
          </div>
          {totalBucket > 0 && (
            <div className="panel !p-4" aria-label="How old what is owed is">
              <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={money.bucket_labels.map((label, i) => `${label}: ${inr(money.buckets[i] ?? 0)}`).join(', ')}>
                {money.buckets.map((value, index) =>
                  value > 0 ? <span key={index} className="h-full" style={{ width: `${(value / totalBucket) * 100}%`, background: `var(--lumen-${BUCKET_HUE[index] ?? 'coral'})` }} /> : null,
                )}
              </div>
              <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
                {money.bucket_labels.map((label, index) => (
                  <li key={label} className="t-caption flex items-center gap-1.5 text-[color:var(--color-text-muted)]">
                    <span className="h-2 w-2 rounded-full" style={{ background: `var(--lumen-${BUCKET_HUE[index] ?? 'coral'})` }} aria-hidden="true" />
                    {label} <span className="font-semibold tabular-nums text-[color:var(--color-text)]">{inr(money.buckets[index] ?? 0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-5">
          <Section title="Cases" hint={`${cases.filter((c) => c.case_status !== 'Inactive').length} active of ${cases.length}`}>
            {cases.length === 0 ? (
              <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-[color:var(--color-text-muted)]">No case yet for this client.</p>
            ) : (
              <ul className="grid gap-2.5 sm:grid-cols-2">
                {cases.map((c) => (
                  <li key={c.case_code} className="rounded-2xl border border-[color:var(--color-border)] p-3">
                    <p className="flex items-start gap-2">
                      <Briefcase className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
                      <Link to={`/data/cases/${c.case_code}`} className="min-w-0 flex-1 text-sm font-semibold leading-snug hover:underline">{c.case_name}</Link>
                      {c.case_status === 'Inactive' && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold text-[color:var(--color-text-muted)]">Inactive</span>}
                    </p>
                    <p className="t-caption mt-1 text-[color:var(--color-text-muted)]">
                      {[c.case_code, c.case_start_date ? `since ${formatDay(c.case_start_date)}` : '', `${c.employees} ${c.employees === 1 ? 'person' : 'people'} on it`].filter(Boolean).join(' · ')}
                    </p>
                    {c.monthly_expected_revenue != null && <p className="t-caption text-[color:var(--color-text-faint)]">Expected {inr(c.monthly_expected_revenue)} a month</p>}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {money && (
            <Section title="Recent bills" hint={money.bills ? `Latest ${money.recent.length} of ${money.bills}` : undefined}>
              {money.recent.length === 0 ? (
                <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-[color:var(--color-text-muted)]">No bill has been raised for this client yet.</p>
              ) : (
                <ul className="divide-y divide-[color:var(--color-border)]">
                  {money.recent.map((bill) => {
                    const open = Math.max(0, bill.grand_total - (bill.credited_amount ?? 0) - bill.received_total)
                    const cancelled = bill.status === 'Cancelled'
                    return (
                      <li key={bill.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5 text-sm">
                        <BillNumber number={bill.bill_number} code={bill.id} className={`min-w-[7rem] font-semibold ${cancelled ? 'line-through' : ''}`} />
                        <span className="min-w-0 flex-1 truncate text-[color:var(--color-text-muted)]">
                          {[formatMonth(bill.service_month), bill.case_name].filter(Boolean).join(' · ')}
                        </span>
                        <span className="font-display font-semibold tabular-nums">{inr(bill.grand_total)}</span>
                        <span className={`w-24 text-right text-xs font-bold ${cancelled ? 'text-negative' : open > 0 ? 'text-warning' : 'text-positive'}`}>{cancelled ? 'Cancelled' : open > 0 ? `${inr(open)} due` : 'Settled'}</span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Section>
          )}
        </div>

        <div className="min-w-0 space-y-5">
          <Section title="People" hint="Who we deal with there">
            {contacts.length === 0 ? (
              <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-[color:var(--color-text-muted)]">No contact is recorded for this client.</p>
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
                      {person.contact_status && person.contact_status !== 'Active' && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold text-[color:var(--color-text-muted)]">{person.contact_status}</span>}
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

          <Section title="Details">
            <dl className="divide-y divide-[color:var(--color-border)]">
              <Fact label="Name on bills" value={client.billing_name} />
              <Fact label="GSTIN" value={client.gstin} />
              <Fact label="Billing address" value={client.billing_address} />
              <Fact label="Client since" value={client.client_start_date ? formatDay(client.client_start_date) : client.client_onboarded ? formatDay(client.client_onboarded) : null} />
              <Fact label="Ended" value={client.client_end_date ? formatDay(client.client_end_date) : null} />
            </dl>
            {!client.billing_name && !client.gstin && !client.billing_address && <p className="t-caption text-[color:var(--color-text-muted)]">No billing details are recorded. Add them with Change details.</p>}
          </Section>

          {members.length > 0 && (
            <Section title="Group" hint="Clients that belong to this one">
              <ul className="space-y-1.5">
                {members.map((m) => (
                  <li key={m.client_code}>
                    <Link to={`/data/clients/${m.client_code}`} className="interactive flex items-center gap-2 rounded-xl px-2 py-1.5 text-sm font-medium hover:bg-muted">
                      <Users className="h-4 w-4 text-accent" aria-hidden="true" /> {m.client_name}
                      {m.client_status === 'Inactive' && <span className="ml-auto text-xs text-[color:var(--color-text-faint)]">Inactive</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}
