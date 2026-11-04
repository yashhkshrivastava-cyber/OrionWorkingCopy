import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, ChevronDown, FileDown, Search } from 'lucide-react'
import { money } from '../../billing/billCalc'
import { formatDay, formatMonth } from './BillDocument'
import { BillNumber } from './BillNumber'
import { inr } from '../dashboard/format'
import { AskAiButton } from '../assistant/Launcher'
import { useAuth } from '../../context/AuthContext'
import type { ReceivableClient, ReceivablesReport } from '../../types'

/** Older money is hotter: the colour of each age bucket, in order. */
const BUCKET_HUE = ['teal', 'amber', 'orange', 'coral']

type SortKey = 'amount' | 'oldest' | 'quiet'

/** The whole of what is owed as one bar split by age, with what each part is. */
function AgeingBar({ buckets, labels, total, tall = false }: { buckets: number[]; labels: string[]; total: number; tall?: boolean }) {
  return (
    <div className={`flex w-full overflow-hidden rounded-full bg-muted ${tall ? 'h-4' : 'h-2'}`} role="img" aria-label={labels.map((label, i) => `${label}: ${inr(buckets[i] ?? 0)}`).join(', ')}>
      {buckets.map((value, index) =>
        value > 0 && total > 0 ? (
          <span key={index} title={`${labels[index]}: ${inr(value)}`} style={{ width: `${(value / total) * 100}%`, background: `var(--lumen-${BUCKET_HUE[index] ?? 'coral'})` }} className="h-full transition-[width] duration-700 first:rounded-l-full last:rounded-r-full" />
        ) : null,
      )}
    </div>
  )
}

function ageChip(days: number): string {
  return days > 90 ? 'bg-negative-dim text-negative' : days > 60 ? 'bg-warning-dim text-warning' : days > 30 ? 'bg-accent-dim text-accent' : 'bg-muted text-[color:var(--color-text-muted)]'
}

/**
 * Receivables as a conversation with each client rather than a table: the total owed and how old it is across the top, then one card per client with its own
 * ageing bar, how long its oldest bill has waited, and the two things you do about it (send the statement, send a reminder). A card opens to its bills.
 * It reads the same report and calls the same actions as the plain table.
 */
export function LumenReceivables({
  report,
  canWrite,
  onStatement,
  onRemind,
}: {
  report: ReceivablesReport
  canWrite: boolean
  onStatement: (client: ReceivableClient) => void
  onRemind: (client: ReceivableClient) => void
}) {
  const { user } = useAuth()
  const canOpenClient = Boolean(user?.can_ods)
  const [search, setSearch] = useState('')
  const [minDays, setMinDays] = useState(0)
  const [sort, setSort] = useState<SortKey>('amount')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const labels = report.bucket_labels
  const totals = report.totals

  const clients = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const found = report.clients.filter((c) => (!needle || c.client_name.toLowerCase().includes(needle)) && c.oldest_days >= minDays)
    return [...found].sort((a, b) => (sort === 'amount' ? b.total - a.total : sort === 'oldest' ? b.oldest_days - a.oldest_days : (a.last_reminder ?? '').localeCompare(b.last_reminder ?? '') || b.total - a.total))
  }, [report.clients, search, minDays, sort])

  const toggle = (code: string) =>
    setOpen((now) => {
      const next = new Set(now)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })

  return (
    <div className="space-y-5">
      <section className="panel relative overflow-hidden !p-6" aria-label="What is owed">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Owed to you</p>
            <p className="lumen-figure mt-1 font-display text-4xl font-semibold tabular-nums leading-none">{inr(totals.total)}</p>
            <p className="t-small mt-2 text-[color:var(--color-text-muted)]">
              {totals.clients} {totals.clients === 1 ? 'client' : 'clients'} · {totals.bills} {totals.bills === 1 ? 'bill' : 'bills'} · as on {formatDay(report.as_of)}
            </p>
          </div>
          <AskAiButton prompt="Which clients have bills unpaid for more than 90 days, and what should I do about them?">Ask AI</AskAiButton>
        </div>
        <div className="mt-5">
          <AgeingBar buckets={totals.buckets} labels={labels} total={totals.total} tall />
          <ul className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {labels.map((label, index) => (
              <li key={label} className="flex items-start gap-2">
                <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: `var(--lumen-${BUCKET_HUE[index] ?? 'coral'})` }} aria-hidden="true" />
                <div>
                  <p className="t-caption text-[color:var(--color-text-muted)]">{label}</p>
                  <p className="font-display text-lg font-semibold tabular-nums">{inr(totals.buckets[index] ?? 0)}</p>
                  <p className="t-caption text-[color:var(--color-text-faint)]">{totals.total > 0 ? `${Math.round(((totals.buckets[index] ?? 0) / totals.total) * 100)}%` : '0%'}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
          <span className="sr-only">Search clients</span>
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search clients" className="h-11 w-full rounded-full pl-10 pr-4 text-sm" />
        </label>
        <div role="group" aria-label="How late" className="flex rounded-full border border-[color:var(--color-border)] bg-muted p-1">
          {(
            [
              [0, 'All'],
              [31, 'Over 30 days'],
              [61, 'Over 60'],
              [91, 'Over 90'],
            ] as const
          ).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={minDays === value} onClick={() => setMinDays(value)} className={`interactive rounded-full px-3.5 py-1.5 text-sm font-semibold ${minDays === value ? 'bg-surface text-[color:var(--color-text)] shadow-card' : 'text-[color:var(--color-text-muted)]'}`}>
              {label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort clients by" className="h-10 rounded-full px-3 text-sm">
            <option value="amount">Most owed</option>
            <option value="oldest">Oldest bill</option>
            <option value="quiet">Not reminded lately</option>
          </select>
        </label>
      </div>

      {report.clients.length === 0 ? (
        <div className="panel px-6 py-14 text-center">
          <p className="font-display text-xl font-semibold">Nothing is outstanding</p>
          <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">Every issued bill has been received in full.</p>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {clients.map((client) => {
            const expanded = open.has(client.client_code)
            return (
              <article key={client.client_code} className={`panel !p-0 ${expanded ? 'xl:col-span-2' : ''}`}>
                <div className="flex flex-wrap items-center gap-4 p-5">
                  <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl text-lg font-bold text-on-primary [background-image:var(--orion-highlight-fill)]" aria-hidden="true">
                    {client.client_name.trim()[0]?.toUpperCase() ?? '?'}
                  </span>
                  <div className="min-w-0 flex-1 basis-48">
                    <h3 className="font-display truncate text-lg font-semibold">
                      {canOpenClient ? (
                        <Link to={`/data/clients/${client.client_code}`} className="hover:underline" title="Open this client">
                          {client.client_name}
                        </Link>
                      ) : (
                        client.client_name
                      )}
                    </h3>
                    <p className="t-caption mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[color:var(--color-text-muted)]">
                      {client.bills.length} {client.bills.length === 1 ? 'bill' : 'bills'}
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${ageChip(client.oldest_days)}`}>oldest {client.oldest_days} days</span>
                      <span>{client.last_reminder ? `reminded ${formatDay(client.last_reminder)}` : 'never reminded'}</span>
                    </p>
                  </div>
                  <p className="font-display text-2xl font-semibold tabular-nums">{inr(client.total)}</p>
                </div>
                <div className="px-5">
                  <AgeingBar buckets={client.buckets} labels={labels} total={client.total} />
                </div>
                <div className="flex flex-wrap items-center gap-2 p-4 pt-3">
                  <button type="button" aria-expanded={expanded} onClick={() => toggle(client.client_code)} className="interactive inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-sm font-semibold text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]">
                    <ChevronDown className={`h-4 w-4 transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                    {expanded ? 'Hide bills' : 'Show bills'}
                  </button>
                  <span className="ml-auto flex gap-2">
                    <button type="button" onClick={() => onStatement(client)} className="interactive inline-flex h-9 items-center gap-1.5 rounded-full border border-[color:var(--color-border-strong)] px-3.5 text-sm font-semibold hover:bg-muted">
                      <FileDown className="h-4 w-4" aria-hidden="true" /> Statement
                    </button>
                    {canWrite && (
                      <button type="button" onClick={() => onRemind(client)} className="btn-primary interactive inline-flex h-9 items-center gap-1.5 rounded-full px-4 text-sm font-semibold">
                        <Bell className="h-4 w-4" aria-hidden="true" /> Remind
                      </button>
                    )}
                  </span>
                </div>
                {expanded && (
                  <ul className="divide-y divide-[color:var(--color-border)] border-t border-[color:var(--color-border)]">
                    {client.bills.map((bill) => (
                      <li key={bill.id} className="flex flex-wrap items-center gap-x-5 gap-y-1 px-5 py-3 text-sm">
                        <BillNumber number={bill.bill_number} code={String(bill.id)} className="min-w-[7.5rem] font-semibold" />
                        <span className="text-[color:var(--color-text-muted)]">{formatMonth(bill.service_month)}</span>
                        <span className="min-w-0 flex-1 truncate text-[color:var(--color-text-muted)]">{bill.case_name}</span>
                        <span className="tabular-nums text-[color:var(--color-text-faint)]">of ₹ {money(bill.grand_total)}</span>
                        <span className="font-display font-semibold tabular-nums">₹ {money(bill.balance)}</span>
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold tabular-nums ${ageChip(bill.days)}`}>{bill.days} days</span>
                        <span className="t-caption w-28 text-right text-[color:var(--color-text-faint)]">{bill.reminders ? `${bill.reminders}× · ${formatDay(bill.last_reminder)}` : 'Not reminded'}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            )
          })}
          {clients.length === 0 && <p className="panel px-6 py-10 text-center text-sm text-[color:var(--color-text-muted)] xl:col-span-2">No client matches that.</p>}
        </div>
      )}
    </div>
  )
}
