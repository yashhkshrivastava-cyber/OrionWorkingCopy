import { useEffect, useState } from 'react'
import { Undo2 } from 'lucide-react'
import { payrollApi } from '../../api/client'
import { day, money } from '../../bank/format'
import { MonthCard, RunRow } from '../../components/bank/lumenBank'
import { MarkPaidModal, monthLabel, ReverseRunModal } from '../../components/bank/PayrollModals'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { LoadingState } from '../../components/ui/DataTable'
import { EmptyState } from '../../components/ui/EmptyState'
import { useToast } from '../../components/ui/Toast'
import { useLumen } from '../../lumen/useLumen'
import type { PayrollMonth, PayrollRun } from '../../types'
import { useBank } from './bankContext'

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

/**
 * Salary reaching the bank. A month's salary lines are entered in Operational Data (Employee Transaction); one bank transfer pays many of them, so paying is a
 * <i>pay run</i>: the month, the day, the account and the bank reference. The bank counts a run as one movement, so one transfer on the statement matches one
 * line, and a run that is reversed puts the lines back to unpaid and the money back in the account. Every run is kept for ever.
 */
export function BankPayrollPage() {
  const { accounts, account, canWrite, version, changed } = useBank()
  const toast = useToast()
  const lumen = useLumen()
  const [months, setMonths] = useState<PayrollMonth[] | null>(null)
  const [runs, setRuns] = useState<PayrollRun[] | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [paying, setPaying] = useState<PayrollMonth | null>(null)
  const [reversing, setReversing] = useState<PayrollRun | null>(null)

  useEffect(() => {
    let live = true
    Promise.all([payrollApi.months(), payrollApi.runs({ limit: 50 })])
      .then(([m, r]) => {
        if (!live) return
        setMonths(m.months)
        setRuns(r.runs)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [version])

  const choices = accounts.map((a) => ({ account_id: a.account_id, account_name: a.account_name, account_kind: a.account_kind, opening_date: a.opening_date }))
  const owed = months?.reduce((sum, m) => sum + Number(m.unpaid_total), 0) ?? 0
  const owedMonths = months?.filter((m) => m.unpaid_lines > 0).length ?? 0
  const latest = runs?.find((r) => !r.reversed)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="t-h2">Payroll</h1>
        <p className="t-caption mt-0.5">
          Salary lines are entered in Operational Data, or by posting an attendance register. They reach the bank when a month is marked paid here: one transfer, one pay run, on the day it was paid. A month can be paid one case at a time.
        </p>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {notice && <Alert variant="error" onDismiss={() => setNotice('')}>{notice}</Alert>}
      {!months && !error && <LoadingState message="Reading the salary…" />}

      {months && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Figure label="Salary still to pay" value={money(owed)} tone={owed > 0 ? 'text-warning' : undefined} note={`${owedMonths} month${owedMonths === 1 ? '' : 's'} with unpaid lines`} />
          <Figure label="Last pay run" value={latest ? money(latest.total) : '—'} note={latest ? `${monthLabel(latest.month_year)} · paid ${day(latest.paid_date)}` : 'No pay run yet'} />
          <Figure label="Pay runs on record" value={String(runs?.filter((r) => !r.reversed).length ?? 0)} note="Reversed runs are kept in the list below" />
        </div>
      )}

      {months && months.length === 0 && (
        <EmptyState compact title="No salary lines yet">
          Enter a month&apos;s salary in Operational Data, Employee Transaction (Salary Paid: No), then mark it paid here.
        </EmptyState>
      )}

      {lumen && months && months.length > 0 && (
        <ul aria-label="Months" className="space-y-3">
          {months.map((m) => (
            <MonthCard key={m.month_year} month={m} label={monthLabel(m.month_year)} canWrite={canWrite} onPay={() => { setNotice(''); setPaying(m) }} />
          ))}
        </ul>
      )}

      {!lumen && months && months.length > 0 && (
        <section aria-label="Months" className="panel overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <caption className="sr-only">Salary by month</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th scope="col" className="px-4 py-2.5 font-medium">Month</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Lines</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Salary</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Paid</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Still to pay</th>
                <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {months.map((m) => (
                <tr key={m.month_year} className="border-b border-[color:var(--color-border)]/60 hover:bg-muted/40">
                  <td className="whitespace-nowrap px-4 py-2.5 font-medium">{monthLabel(m.month_year)}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{m.lines}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{money(Number(m.total))}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">
                    {money(Number(m.paid_total))}
                    <span className="t-caption ml-1">({m.paid_lines})</span>
                  </td>
                  <td className={`whitespace-nowrap px-2 py-2.5 text-right font-medium tabular-nums ${m.unpaid_lines > 0 ? 'text-warning' : 'text-[color:var(--color-text-muted)]'}`}>
                    {money(Number(m.unpaid_total))}
                    {m.unpaid_lines > 0 && <span className="t-caption ml-1">({m.unpaid_lines})</span>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    {canWrite && m.unpaid_lines > 0 && (
                      <Button size="sm" variant="secondary" onClick={() => { setNotice(''); setPaying(m) }}>
                        Mark paid…
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {lumen && runs && runs.length > 0 && (
        <section aria-label="Pay runs" className="panel !p-0">
          <h2 className="t-h3 px-4 pt-4">Pay runs</h2>
          <ul className="mt-2 divide-y divide-[color:var(--color-border)]">
            {runs.map((run) => (
              <RunRow key={run.run_id} run={run} label={monthLabel(run.month_year)} canWrite={canWrite} onReverse={() => { setNotice(''); setReversing(run) }} />
            ))}
          </ul>
        </section>
      )}

      {!lumen && runs && runs.length > 0 && (
        <section aria-label="Pay runs" className="panel overflow-x-auto">
          <h2 className="t-h3 px-4 pt-4">Pay runs</h2>
          <table className="mt-2 w-full min-w-[44rem] text-sm">
            <caption className="sr-only">Salary pay runs</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th scope="col" className="px-4 py-2.5 font-medium">Paid on</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Month</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Employees</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Amount</th>
                <th scope="col" className="px-2 py-2.5 font-medium">From</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Reference</th>
                <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className="border-b border-[color:var(--color-border)]/60 align-top hover:bg-muted/40">
                  <td className={`whitespace-nowrap px-4 py-2.5 tabular-nums ${run.reversed ? 'text-[color:var(--color-text-muted)] line-through' : ''}`}>{day(run.paid_date)}</td>
                  <td className="whitespace-nowrap px-2 py-2.5">{monthLabel(run.month_year)}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{run.lines}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums">{money(Number(run.total))}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-xs text-[color:var(--color-text-muted)]">{run.account_name ?? '—'}</td>
                  <td className="px-2 py-2.5 text-xs text-[color:var(--color-text-muted)]">
                    {run.reference || ''}
                    {run.reversed && <div>Reversed {day(run.reversed_timestamp)}: {run.reversal_reason}</div>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    {canWrite && !run.reversed && (
                      <button
                        type="button"
                        onClick={() => { setNotice(''); setReversing(run) }}
                        className="interactive inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[color:var(--color-text-muted)] hover:bg-muted hover:text-negative"
                      >
                        <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                        Reverse
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {paying && (
        <MarkPaidModal
          month={paying}
          accounts={choices}
          defaultAccountId={accounts.length > 1 ? undefined : account.account_id}
          onClose={() => setPaying(null)}
          onDone={(lines, total) => {
            setPaying(null)
            toast.show('Pay run recorded', { detail: `${money(total)} for ${lines} ${lines === 1 ? 'employee' : 'employees'}, ${monthLabel(paying.month_year)}.` })
            changed()
          }}
          onConflict={(message) => {
            setPaying(null)
            setNotice(message)
            changed()
          }}
        />
      )}
      {reversing && (
        <ReverseRunModal
          run={reversing}
          onClose={() => setReversing(null)}
          onDone={() => {
            setReversing(null)
            toast.show('Pay run reversed', { detail: 'Its salary lines are owed again.' })
            changed()
          }}
          onConflict={(message) => {
            setReversing(null)
            setNotice(message)
            changed()
          }}
        />
      )}
    </div>
  )
}
