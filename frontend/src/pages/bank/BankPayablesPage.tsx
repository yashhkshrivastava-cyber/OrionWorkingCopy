import { useEffect, useMemo, useState } from 'react'
import { ListChecks, Search } from 'lucide-react'
import { payablesApi } from '../../api/client'
import { day, money } from '../../bank/format'
import { ExpensePaymentsModal, PayExpenseModal } from '../../components/bank/ExpensePaymentModals'
import { PayableCard } from '../../components/bank/lumenBank'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { LoadingState } from '../../components/ui/DataTable'
import { EmptyState } from '../../components/ui/EmptyState'
import { Input, Select } from '../../components/ui/Field'
import { Segmented } from '../../components/ui/Segmented'
import { useToast } from '../../components/ui/Toast'
import { useLumen } from '../../lumen/useLumen'
import type { PayableBucket, PayableRow, PayablesList } from '../../types'
import { useBank } from './bankContext'

const PAGE_SIZE = 50

const LATE_TONE: Record<PayableBucket, string> = {
  not_due: 'text-[color:var(--color-text-muted)]',
  '0-30': 'text-warning',
  '31-60': 'text-warning',
  '61-90': 'text-negative',
  '90+': 'text-negative',
}

function Figure({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  const lumen = useLumen()
  if (lumen) return <StatTile label={label} text={value} hint={note} tone={tone} />
  return (
    <div className="panel p-4">
      <p className="t-caption">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${tone ?? ''}`}>{value}</p>
      {note && <p className="t-caption mt-0.5">{note}</p>}
    </div>
  )
}

function Late({ row }: { row: PayableRow }) {
  if (row.bucket === null || row.days_late === null) return null
  const text = row.bucket === 'not_due' ? `due in ${-row.days_late} day${row.days_late === -1 ? '' : 's'}` : row.days_late === 0 ? 'due today' : `${row.days_late} day${row.days_late === 1 ? '' : 's'} late`
  return <span className={`text-xs ${LATE_TONE[row.bucket]}`}>{text}</span>
}

/**
 * What the firm owes on expenses. A Committed expense is a cost taken on; the money leaves the bank when a payment is recorded here, which may be later, in
 * parts and from different accounts. Whether an expense is unpaid, part paid or paid is worked out from its payments, and each payment is kept for ever.
 */
export function BankPayablesPage() {
  const { accounts, account, canWrite, version, changed } = useBank()
  const toast = useToast()
  const lumen = useLumen()
  const [status, setStatus] = useState<'open' | 'paid'>('open')
  const [bucket, setBucket] = useState<PayableBucket | undefined>(undefined)
  const [caseCode, setCaseCode] = useState('')
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PayablesList | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [paying, setPaying] = useState<PayableRow | null>(null)
  const [listing, setListing] = useState<string | null>(null)

  // Typing in the search box waits for a pause before it asks the server.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQ(typed)
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [typed])

  const query = useMemo(() => ({ status, bucket: status === 'open' ? bucket : undefined, q, case_code: caseCode || undefined, page, limit: PAGE_SIZE }), [status, bucket, q, caseCode, page])

  useEffect(() => {
    let live = true
    payablesApi
      .list(query)
      .then((result) => {
        if (!live) return
        setData(result)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [query, version])

  const last = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1
  const choices = accounts.map((a) => ({ account_id: a.account_id, account_name: a.account_name, account_kind: a.account_kind, opening_date: a.opening_date }))

  return (
    <div className="space-y-4">
      <div>
        <h1 className="t-h2">Payables</h1>
        <p className="t-caption mt-0.5">
          Expenses that have been incurred and what is still owed on them. An expense reaches the bank when a payment is recorded here, not when it is entered.
        </p>
      </div>

      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Figure label="Owed on expenses" value={money(data.summary.owed)} note={`${data.summary.open_count} expense${data.summary.open_count === 1 ? '' : 's'} with something to pay`} />
            <Figure label="Past its pay-by day" value={money(data.summary.overdue)} tone={data.summary.overdue > 0 ? 'text-negative' : undefined} />
            <Figure label="Due in the next 7 days" value={money(data.summary.due_in_7_days)} />
          </div>
          <div role="group" aria-label="Ageing" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {data.ageing.map((group) => {
              const active = bucket === group.bucket && status === 'open'
              return (
                <button
                  key={group.bucket}
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    setStatus('open')
                    setBucket(active ? undefined : group.bucket)
                    setPage(1)
                  }}
                  className={`interactive panel p-3 text-left ${active ? 'ring-2 ring-accent' : ''}`}
                >
                  <span className="t-caption block">{group.label}</span>
                  <span className={`mt-0.5 block font-semibold tabular-nums ${LATE_TONE[group.bucket]}`}>{money(group.amount)}</span>
                  <span className="t-caption block">{group.count} expense{group.count === 1 ? '' : 's'}</span>
                </button>
              )
            })}
          </div>
        </>
      )}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <Segmented
          label="Show"
          value={status}
          options={[
            { id: 'open', label: 'To pay' },
            { id: 'paid', label: 'Paid' },
          ]}
          onChange={(next) => {
            setStatus(next)
            setBucket(undefined)
            setPage(1)
          }}
        />
        <label className="relative block w-full sm:w-72">
          <span className="sr-only">Search expenses</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-muted)]" aria-hidden="true" />
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Search by code, case, type or note" className="pl-9" />
        </label>
        {data && data.cases.filter((c) => c.case_code).length > 1 && (
          <label className="block w-full sm:w-64">
            <span className="sr-only">Case</span>
            <Select
              value={caseCode}
              onChange={(e) => {
                setCaseCode(e.target.value)
                setPage(1)
              }}
            >
              <option value="">All cases</option>
              {data.cases
                .filter((c) => c.case_code)
                .map((c) => (
                  <option key={c.case_code} value={c.case_code ?? ''}>
                    {c.case_name} ({money(c.amount)})
                  </option>
                ))}
            </Select>
          </label>
        )}
      </div>

      {notice && <Alert variant="error" onDismiss={() => setNotice('')}>{notice}</Alert>}
      {error && <Alert variant="error">{error}</Alert>}
      {!data && !error && <LoadingState message="Reading what is owed…" />}

      {data && data.items.length === 0 && (
        <EmptyState compact title={status === 'open' ? (bucket || q ? 'Nothing matches' : 'Nothing is owed') : 'Nothing found'}>
          {status === 'open'
            ? bucket || q
              ? 'Try another ageing group or search.'
              : 'Every incurred expense has been paid. An expense entered in Operational Data as Incurred appears here until it is paid (or until it is entered as already paid).'
            : 'Expenses paid in full appear here.'}
        </EmptyState>
      )}

      {lumen && data && data.items.length > 0 && (
        <ul className="space-y-3" aria-label="Expenses and what is owed on them">
          {data.items.map((row) => (
            <PayableCard key={row.expense_code} row={row} late={<Late row={row} />} canWrite={canWrite} onPay={() => { setNotice(''); setPaying(row) }} onPayments={() => setListing(row.expense_code)} />
          ))}
        </ul>
      )}

      {!lumen && data && data.items.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[56rem] text-sm">
            <caption className="sr-only">Expenses and what is owed on them</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th scope="col" className="px-4 py-2.5 font-medium">Expense</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Pay by</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Came to</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Paid</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Left</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Status</th>
                <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.expense_code} className="border-b border-[color:var(--color-border)]/60 align-top hover:bg-muted/40">
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{row.expense_type || 'Expense'}</div>
                    <div className="text-xs text-[color:var(--color-text-muted)]">
                      <span className="mr-1.5 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide">{row.expense_code}</span>
                      {[row.case_name, row.description].filter(Boolean).join(' · ')}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5">
                    <div className="tabular-nums">{day(row.pay_by)}</div>
                    <Late row={row} />
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{money(row.total)}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{money(row.paid)}</td>
                  <td className={`whitespace-nowrap px-2 py-2.5 text-right font-medium tabular-nums ${row.left > 0 ? '' : 'text-[color:var(--color-text-muted)]'}`}>{money(row.left)}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-xs">{row.payment_status}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {canWrite && row.left > 0 && (
                        <Button size="sm" variant="secondary" onClick={() => { setNotice(''); setPaying(row) }}>
                          Pay…
                        </Button>
                      )}
                      <button
                        type="button"
                        onClick={() => setListing(row.expense_code)}
                        className="interactive inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[color:var(--color-text-muted)] hover:bg-muted"
                      >
                        <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
                        Payments
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && last > 1 && (
        <nav aria-label="Pages" className="flex items-center justify-between">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span className="t-caption">
            Page {page} of {last}
          </span>
          <Button variant="secondary" size="sm" disabled={page >= last} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </nav>
      )}

      {paying && (
        <PayExpenseModal
          expense={paying}
          accounts={choices}
          defaultAccountId={account.account_id}
          onClose={() => setPaying(null)}
          onDone={(amount) => {
            setPaying(null)
            toast.show('Payment recorded', { detail: `${money(amount)} paid on ${paying.expense_code}.` })
            changed()
          }}
          onConflict={(message) => {
            setPaying(null)
            setNotice(message)
            changed()
          }}
        />
      )}
      {listing && <ExpensePaymentsModal code={listing} canWrite={canWrite} onClose={() => setListing(null)} onChanged={changed} />}
    </div>
  )
}
