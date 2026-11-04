import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowUpRight, CircleAlert, CircleCheck, Landmark, Plus, Sparkles } from 'lucide-react'
import { bankApi } from '../../api/client'
import { day, money, month } from '../../bank/format'
import { EntryModal } from '../../components/bank/EntryModal'
import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { SERIES, inr } from '../../components/dashboard/format'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox } from '../../components/ui/Field'
import { EmptyState } from '../../components/ui/EmptyState'
import { LoadingState } from '../../components/ui/DataTable'
import { useToast } from '../../components/ui/Toast'
import type { BankAlert, BankForecast, BankReconciliation, BankSeries, BankSummary, Category, SeriesPoint } from '../../types'
import { useBank } from './bankContext'
import { BalanceHero } from '../../components/bank/BalanceHero'
import { useLumen } from '../../lumen/useLumen'

function Stat({ label, value, note, tone }: { label: string; value: string; note?: ReactNode; tone?: 'positive' | 'negative' }) {
  const lumen = useLumen()
  if (lumen) {
    return (
      <div style={{ '--hue': `var(--lumen-${tone === 'positive' ? 'green' : tone === 'negative' ? 'coral' : 'indigo'})` } as React.CSSProperties} className="panel lumen-kpi relative flex flex-col gap-1 overflow-hidden !p-5">
        <p className="t-caption relative font-semibold text-[color:var(--color-text-muted)]">{label}</p>
        <p className="lumen-figure relative font-display font-semibold tabular-nums">{value}</p>
        {note && <p className="t-caption relative text-[color:var(--color-text-faint)]">{note}</p>}
      </div>
    )
  }
  return (
    <div className="panel p-4">
      <p className="t-label text-[color:var(--color-text-muted)]">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${tone === 'positive' ? 'text-positive' : tone === 'negative' ? 'text-negative' : 'text-[color:var(--color-text)]'}`}>{value}</p>
      {note && <p className="t-caption mt-1">{note}</p>}
    </div>
  )
}

function Standing({ state }: { state: BankReconciliation | null }) {
  if (!state || state.cash) return null
  if (state.state === 'no_statement') {
    return (
      <Link to="/bank/reconcile" className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-border)] bg-surface px-3 py-1 text-xs font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
        <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        No bank statement uploaded yet
      </Link>
    )
  }
  const clean = state.state === 'reconciled'
  const bad = state.state === 'unexplained'
  const Icon = clean ? CircleCheck : CircleAlert
  return (
    <Link
      to="/bank/reconcile"
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${clean ? 'bg-positive-dim text-positive' : bad ? 'bg-negative-dim text-negative' : 'bg-warning-dim text-warning'}`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {clean ? `Agrees with the bank statement of ${day(state.as_of)}` : bad ? `Does not agree with the statement of ${day(state.as_of)}: ${money(Math.abs(state.unexplained ?? 0))} unexplained` : `Differs from the statement of ${day(state.as_of)}, and the items explain it`}
    </Link>
  )
}

function Forecast({ forecast, includeOverdue, onToggle }: { forecast: BankForecast; includeOverdue: boolean; onToggle: (value: boolean) => void }) {
  const weeks = useMemo<SeriesPoint[]>(
    () => (forecast.weeks ?? []).map((w) => ({ code: w.week_start, label: day(w.week_start).replace(/ \d{4}$/, ''), money_in: w.money_in, money_out: w.money_out, balance: w.balance })),
    [forecast.weeks],
  )
  const overdue = forecast.overdue
  const low = forecast.lowest
  const goesLow = low && forecast.balance !== undefined && low.balance < forecast.balance
  return (
    <section aria-label="Looking ahead" className="panel p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="t-h3">Looking ahead</h2>
          <p className="t-caption mt-0.5">From bills clients have yet to pay, costs still to come and GST still to pay. Only what Orion already knows.</p>
        </div>
        <Checkbox label="Count overdue money as arriving this week" checked={includeOverdue} onChange={onToggle} />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {(forecast.windows ?? []).map((w) => (
          <div key={w.days} className="rounded-xl bg-muted/60 p-3">
            <p className="t-label text-[color:var(--color-text-muted)]">In {w.days} days</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">{money(w.projected_balance)}</p>
            <p className="t-caption mt-1">
              <span className="text-positive">+{inr(w.money_in)}</span> in · <span className="text-negative">−{inr(w.money_out)}</span> out
            </p>
          </div>
        ))}
      </div>

      {overdue && overdue.count > 0 && (
        <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
          <span className="font-medium text-warning">{overdue.count} overdue</span>: {money(overdue.money_in)} still to come in from clients and {money(overdue.money_out)} still to be paid. It is left out of the figures above unless you count it.
        </p>
      )}
      {goesLow && low && (
        <p className="mt-2 text-sm">
          The lowest the balance is expected to reach is <span className="font-semibold tabular-nums">{money(low.balance)}</span>, in the week of {day(low.week_start)}.
        </p>
      )}

      <div className="mt-4">
        <MonthlyChart
          data={weeks}
          bars={[
            { key: 'money_in', label: 'Expected in', color: SERIES.joiners },
            { key: 'money_out', label: 'Expected out', color: SERIES.expense },
          ]}
          lines={[{ key: 'balance', label: 'Projected balance', color: SERIES.margin, axis: 'right' }]}
          rightFormat="money"
          height={240}
          emptyMessage="Nothing is expected in the next 13 weeks."
        />
      </div>

      {(forecast.upcoming?.length ?? 0) > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <caption className="sr-only">The next expected movements</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th className="py-2 pr-3 font-medium">Due</th>
                <th className="py-2 pr-3 font-medium">What</th>
                <th className="py-2 pr-3 text-right font-medium">In</th>
                <th className="py-2 text-right font-medium">Out</th>
              </tr>
            </thead>
            <tbody>
              {forecast.upcoming?.slice(0, 10).map((item) => (
                <tr key={`${item.source}:${item.source_ref}`} className="border-b border-[color:var(--color-border)]/60">
                  <td className="whitespace-nowrap py-2 pr-3 tabular-nums">{day(item.due_date)}</td>
                  <td className="py-2 pr-3">
                    <span className="font-medium">{item.counterparty || item.category_label}</span>
                    {item.description && <span className="text-[color:var(--color-text-muted)]"> · {item.description}</span>}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums text-positive">{item.direction === 'in' ? money(item.amount) : ''}</td>
                  <td className="py-2 text-right tabular-nums text-negative">{item.direction === 'out' ? money(item.amount) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {forecast.note && <p className="t-caption mt-3">{forecast.note}</p>}
    </section>
  )
}

/** The bank at a glance: what the account holds, where it came from and went, what is coming, and whether the book agrees with the bank. */
export function BankOverviewPage() {
  const { meta, account, accounts, scope, canWrite, version, changed } = useBank()
  const toast = useToast()
  const [summary, setSummary] = useState<BankSummary | null>(null)
  const [series, setSeries] = useState<BankSeries | null>(null)
  const [forecast, setForecast] = useState<BankForecast | null>(null)
  const [standing, setStanding] = useState<BankReconciliation | null>(null)
  const [includeOverdue, setIncludeOverdue] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [alerts, setAlerts] = useState<BankAlert[]>([])
  const lumen = useLumen()

  useEffect(() => {
    if (!account.configured) return
    let live = true
    // The book is checked against a statement one account at a time: with all accounts in view (and more than one) there is no single standing to show.
    const single = scope !== null || accounts.length <= 1
    Promise.all([bankApi.summary(scope ?? undefined), bankApi.series(12, scope ?? undefined), single ? bankApi.reconciliation(scope ?? account.account_id) : Promise.resolve(null)])
      .then(([s, m, r]) => {
        if (!live) return
        setSummary(s)
        setSeries(m)
        setStanding(r)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [account.configured, account.account_id, accounts.length, scope, version])

  useEffect(() => {
    if (!account.configured) return
    let live = true
    bankApi
      .forecast(includeOverdue)
      .then((f) => live && setForecast(f))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [account.configured, includeOverdue, version])

  // The minimum balance set on the accounts is checked whichever account is in view: it is about the firm's money, not one screen.
  useEffect(() => {
    if (!account.configured) return
    let live = true
    bankApi
      .alerts()
      .then((a) => live && setAlerts(a.alerts))
      .catch(() => live && setAlerts([])) // a warning that cannot be read is simply not shown
    return () => {
      live = false
    }
  }, [account.configured, version])

  const trend = useMemo<SeriesPoint[]>(
    () => (series?.months ?? []).map((m) => ({ code: m.month.slice(0, 7), label: month(m.month), money_in: m.money_in, money_out: m.money_out, closing_balance: m.closing_balance })),
    [series],
  )
  const mix = (direction: 'in' | 'out'): Category[] =>
    (series?.categories ?? []).filter((c) => c.direction === direction && c.total > 0).map((c) => ({ code: c.category, label: c.label, value: c.total }))

  if (!account.configured) {
    return (
      <EmptyState
        icon={Landmark}
        title="Set up the bank account"
        action={
          canWrite ? (
            <Link to="/bank/account" className="btn-primary inline-flex h-9 items-center rounded-lg px-4 text-sm font-semibold">
              Enter the opening balance
            </Link>
          ) : undefined
        }
      >
        {canWrite
          ? 'Tell Orion what the bank held on a day, and it keeps the balance from there: clients’ payments add to it, expenses and GST paid take from it, and you add interest, charges and anything else.'
          : 'The account has not been set up yet. Someone who may change the bank needs to enter its opening balance.'}
      </EmptyState>
    )
  }
  if (error) return <Alert variant="error">{error}</Alert>
  if (!summary?.financial_year || !summary.month || !summary.account || !summary.reconciliation) return <LoadingState message="Reading the bank…" />

  const fy = summary.financial_year
  const rec = summary.reconciliation
  const changedAfter = rec.changed_after_matching ?? 0
  const open = rec.book_unmatched + rec.lines_unmatched + changedAfter

  return (
    <div className="space-y-4">
      {alerts.length > 0 && (
        <div role="region" aria-label="Minimum balance" className="space-y-2">
          {alerts.map((alert) => (
            <Alert key={alert.key} variant={alert.level === 'critical' ? 'error' : 'warning'}>
              <span className="font-medium">{alert.title}.</span> {alert.detail}
            </Alert>
          ))}
        </div>
      )}
      {lumen ? (
        <BalanceHero
          eyebrow={`${summary.account.account_name}${summary.account.bank_name ? ` · ${summary.account.bank_name}` : ''}${summary.account.account_last4 ? ` ····${summary.account.account_last4}` : ''}`}
          balance={summary.balance ?? 0}
          balanceText={money(summary.balance)}
          note={`As of today. Started at ${money(summary.account.opening_balance)} on ${day(summary.account.opening_date)}.`}
          trend={trend.map((point) => Number(point.closing_balance ?? 0))}
          accounts={scope === null && (summary.accounts?.length ?? 0) > 1 ? (summary.accounts ?? []).map((a) => ({ name: a.account_name, text: money(a.balance) })) : []}
          standing={<Standing state={standing} />}
          action={
            canWrite ? (
              <button type="button" onClick={() => setAdding(true)} className="interactive inline-flex h-11 items-center gap-2 rounded-full bg-white px-5 text-sm font-bold text-ink shadow-raised hover:-translate-y-0.5">
                <Plus className="h-4 w-4" aria-hidden="true" /> Add entry
              </button>
            ) : null
          }
        />
      ) : (
      <section aria-label="Balance" className="panel flex flex-wrap items-end justify-between gap-4 p-5 sm:p-6">
        <div className="min-w-0">
          <p className="eyebrow">{summary.account.account_name}{summary.account.bank_name ? ` · ${summary.account.bank_name}` : ''}{summary.account.account_last4 ? ` ····${summary.account.account_last4}` : ''}</p>
          <p className={`mt-1 text-4xl font-semibold tabular-nums tracking-tight ${(summary.balance ?? 0) < 0 ? 'text-negative' : ''}`} aria-label={`Balance ${money(summary.balance)}`}>
            {money(summary.balance)}
          </p>
          <p className="t-caption mt-1">
            As of today. Started at {money(summary.account.opening_balance)} on {day(summary.account.opening_date)}.
          </p>
          {scope === null && (summary.accounts?.length ?? 0) > 1 && (
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {summary.accounts?.map((a) => (
                <li key={a.account_id}>
                  <span className="text-[color:var(--color-text-muted)]">{a.account_name}</span> <span className="font-medium tabular-nums">{money(a.balance)}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3">
            <Standing state={standing} />
          </div>
        </div>
        {canWrite && (
          <Button onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Add entry
          </Button>
        )}
      </section>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="This month" value={money(summary.month.net)} tone={summary.month.net >= 0 ? 'positive' : 'negative'} note={<>{money(summary.month.money_in)} in · {money(summary.month.money_out)} out</>} />
        <Stat label="This financial year" value={money(fy.net)} tone={fy.net >= 0 ? 'positive' : 'negative'} note={<>{money(fy.money_in)} in · {money(fy.money_out)} out</>} />
        <Stat label="Interest and other income" value={money(fy.interest_and_other_income)} note={<>Interest {money(fy.interest)} · other {money(fy.other_income)} this year</>} />
        <Stat
          label="Not yet reconciled"
          value={String(open)}
          note={
            <Link to="/bank/reconcile" className="text-accent hover:underline">
              {rec.book_unmatched} in the book · {rec.lines_unmatched} on the statement{changedAfter > 0 ? ` · ${changedAfter} changed after matching` : ''}
            </Link>
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard quiet className="lg:col-span-2" title="Money in, money out and the balance" subtitle="Each month’s receipts and payments, with the balance at the end of the month on the right-hand scale.">
          <MonthlyChart
            data={trend}
            bars={[
              { key: 'money_in', label: 'Money in', color: SERIES.joiners },
              { key: 'money_out', label: 'Money out', color: SERIES.expense },
            ]}
            lines={[{ key: 'closing_balance', label: 'Balance at month end', color: SERIES.margin, axis: 'right' }]}
            rightFormat="money"
            height={300}
          />
        </ChartCard>
        <ChartCard quiet title="Where the money came from" subtitle="Everything received over the last 12 months, by kind.">
          <CategoryBar data={mix('in')} color={SERIES.joiners} format={inr} labelWidth={110} height={300} emptyMessage="Nothing received yet." />
        </ChartCard>
        <ChartCard quiet className="lg:col-span-3" title="Where the money went" subtitle="Everything paid out over the last 12 months, by kind.">
          <CategoryBar data={mix('out')} color={SERIES.expense} format={inr} labelWidth={130} height={240} emptyMessage="Nothing paid out yet." />
        </ChartCard>
      </div>

      {forecast?.configured && <Forecast forecast={forecast} includeOverdue={includeOverdue} onToggle={setIncludeOverdue} />}

      <p className="t-caption flex items-center gap-1.5">
        <ArrowDownLeft className="h-3.5 w-3.5 text-positive" aria-hidden="true" />
        Clients’ payments
        <ArrowUpRight className="ml-2 h-3.5 w-3.5 text-negative" aria-hidden="true" />
        Expenses and GST paid come from the bills and expenses already in Orion, so they are never entered twice.
      </p>

      <EntryModal
        open={adding}
        meta={meta}
        openingDate={account.opening_date}
        accounts={accounts}
        defaultAccountId={account.account_id}
        onClose={() => setAdding(false)}
        onSaved={() => {
          setAdding(false)
          toast.show('Entry saved')
          changed()
        }}
      />
    </div>
  )
}
