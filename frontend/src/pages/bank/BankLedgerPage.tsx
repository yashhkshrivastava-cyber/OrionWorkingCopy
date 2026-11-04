import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownLeft, ArrowUpRight, CircleCheck, Download, Landmark, Plus, Search, Undo2 } from 'lucide-react'
import { ApiError, bankApi } from '../../api/client'
import { day, money, todayIso } from '../../bank/format'
import { BillText } from '../../components/bank/BillText'
import { EntryModal } from '../../components/bank/EntryModal'
import { BillNumber } from '../../components/billing/BillNumber'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { LoadingState } from '../../components/ui/DataTable'
import { Field, Input, Select, Textarea } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { useToast } from '../../components/ui/Toast'
import type { BankLedger, BankLedgerQuery, BankLedgerRow } from '../../types'
import { useBank } from './bankContext'
import { useLumen } from '../../lumen/useLumen'

const PAGE_SIZE = 50
const BLANK: BankLedgerQuery = { date_from: '', date_to: '', direction: '', category: '', source: '', q: '', reconciled: '' }

function Reference({ row }: { row: BankLedgerRow }) {
  if (row.source === 'revenue' && row.reference) return <BillNumber number={row.reference} code={row.bill_code} />
  return <>{row.reference || ''}</>
}

/** Every movement behind the balance, newest first, with the balance after each one. */
export function BankLedgerPage() {
  const { meta, account, accounts, scope, canWrite, version, changed } = useBank()
  const showAccount = scope === null && accounts.length > 1
  const lumen = useLumen()
  const toast = useToast()
  const [filters, setFilters] = useState<BankLedgerQuery>(BLANK)
  const [typed, setTyped] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<BankLedger | null>(null)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [voiding, setVoiding] = useState<BankLedgerRow | null>(null)
  const [reason, setReason] = useState('')
  const [voidError, setVoidError] = useState('')
  const [busy, setBusy] = useState(false)

  // Typing in the search box waits for a pause before it asks the server.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((current) => (current.q === typed ? current : { ...current, q: typed }))
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [typed])

  const query = useMemo<BankLedgerQuery>(() => ({ ...filters, page, limit: PAGE_SIZE, account_id: scope ?? undefined }), [filters, page, scope])

  useEffect(() => {
    if (!account.configured) return
    let live = true
    bankApi
      .ledger(query)
      .then((result) => {
        if (!live) return
        setData(result)
        setError('')
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [account.configured, query, version])

  const change = (patch: Partial<BankLedgerQuery>) => {
    setFilters((current) => ({ ...current, ...patch }))
    setPage(1)
  }
  const filtered = Object.entries(filters).some(([, value]) => value)
  const categories = useMemo(() => Object.entries(meta.category_labels).sort((a, b) => a[1].localeCompare(b[1])), [meta])

  const doVoid = async () => {
    if (!voiding || busy) return
    if (reason.trim().length < 5) return setVoidError('Say why in a few words, so the history makes sense later.')
    setBusy(true)
    setVoidError('')
    try {
      await bankApi.voidEntry(Number(voiding.source_ref), reason.trim())
      setVoiding(null)
      setReason('')
      toast.show('Entry voided', { detail: 'It no longer counts, and stays in the history.' })
      changed()
    } catch (err) {
      setVoidError(err instanceof ApiError || err instanceof Error ? err.message : 'That did not work. Try again.')
    } finally {
      setBusy(false)
    }
  }

  // Lumen shows the same rows under the day they happened, with what came in and went out that day on this page.
  const days = useMemo(() => {
    const groups: { date: string; rows: BankLedgerRow[]; moneyIn: number; moneyOut: number }[] = []
    for (const row of data?.rows ?? []) {
      let group = groups[groups.length - 1]
      if (!group || group.date !== row.move_date) {
        group = { date: row.move_date, rows: [], moneyIn: 0, moneyOut: 0 }
        groups.push(group)
      }
      group.rows.push(row)
      if (row.direction === 'in') group.moneyIn += row.amount
      else group.moneyOut += row.amount
    }
    return groups
  }, [data])

  if (!account.configured) {
    return (
      <EmptyState icon={Landmark} title="The bank account is not set up yet">
        <Link to="/bank/account" className="text-accent hover:underline">Enter the opening balance</Link> first; the ledger starts from it.
      </EmptyState>
    )
  }

  const total = data?.total ?? 0
  const last = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="space-y-4">
      <section aria-label="Filters" className="panel space-y-3 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Search" className="min-w-[14rem] flex-1">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Name, note or reference" className="pl-9" />
            </div>
          </Field>
          <Field label="From">
            <Input type="date" value={filters.date_from} min={account.opening_date} max={todayIso()} onChange={(e) => change({ date_from: e.target.value })} />
          </Field>
          <Field label="To">
            <Input type="date" value={filters.date_to} max={todayIso()} onChange={(e) => change({ date_to: e.target.value })} />
          </Field>
          <Field label="Money">
            <Select value={filters.direction} onChange={(e) => change({ direction: e.target.value as BankLedgerQuery['direction'] })}>
              <option value="">In and out</option>
              <option value="in">In</option>
              <option value="out">Out</option>
            </Select>
          </Field>
          <Field label="Kind">
            <Select value={filters.category} onChange={(e) => change({ category: e.target.value })}>
              <option value="">Everything</option>
              {categories.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Reconciled">
            <Select value={filters.reconciled} onChange={(e) => change({ reconciled: e.target.value as BankLedgerQuery['reconciled'] })}>
              <option value="">Either</option>
              <option value="yes">On a statement</option>
              <option value="no">Not on a statement</option>
            </Select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="t-caption" aria-live="polite">
            {data ? (
              <>
                {total.toLocaleString('en-IN')} movement{total === 1 ? '' : 's'}
                {filtered && data.totals ? <> · {money(data.totals.in)} in · {money(data.totals.out)} out</> : null}
              </>
            ) : (
              'Loading…'
            )}
          </p>
          <div className="flex gap-2">
            {filtered && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setTyped('')
                  setFilters(BLANK)
                  setPage(1)
                }}
              >
                Clear filters
              </Button>
            )}
            <a
              href={bankApi.ledgerCsvUrl({ ...filters, account_id: scope ?? undefined })}
              download
              className="interactive inline-flex h-8 items-center gap-2 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 text-xs font-medium shadow-card hover:bg-surface-hover"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              Export CSV
            </a>
            {canWrite && (
              <Button size="sm" onClick={() => setAdding(true)}>
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                Add entry
              </Button>
            )}
          </div>
        </div>
      </section>

      {error && <Alert variant="error">{error}</Alert>}
      {!data && !error && <LoadingState message="Reading the ledger…" />}

      {data && data.rows.length === 0 && (
        <EmptyState compact title={filtered ? 'Nothing matches these filters' : 'Nothing has moved yet'}>
          {filtered ? 'Try a wider period or take a filter off.' : 'Clients’ payments, expenses, GST paid and the entries you add will appear here.'}
        </EmptyState>
      )}

      {lumen && data && data.rows.length > 0 && (
        <div className="space-y-5">
          {days.map((group) => (
            <section key={group.date} aria-label={day(group.date)} className="space-y-2">
              <header className="flex flex-wrap items-baseline justify-between gap-2 px-1">
                <h3 className="font-display text-lg font-semibold">{day(group.date)}</h3>
                <p className="t-caption flex gap-3 tabular-nums text-[color:var(--color-text-muted)]">
                  {group.moneyIn > 0 && <span className="text-positive">+ {money(group.moneyIn)}</span>}
                  {group.moneyOut > 0 && <span className="text-negative">− {money(group.moneyOut)}</span>}
                </p>
              </header>
              <ul className="panel divide-y divide-[color:var(--color-border)] !p-0">
                {group.rows.map((row) => (
                  <li key={`${row.source}:${row.source_ref}`} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                    <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-2xl ${row.direction === 'in' ? 'bg-positive-dim text-positive' : 'bg-negative-dim text-negative'}`} aria-hidden="true">
                      {row.direction === 'in' ? <ArrowDownLeft className="h-5 w-5" /> : <ArrowUpRight className="h-5 w-5" />}
                    </span>
                    <div className="min-w-0 flex-1 basis-60">
                      <p className="truncate font-semibold">{row.counterparty || row.category_label}</p>
                      <p className="t-caption mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[color:var(--color-text-muted)]">
                        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">{row.category_label}</span>
                        {showAccount && <span>{row.account_name}</span>}
                        <span className="min-w-0">
                          <BillText text={row.description} />
                        </span>
                      </p>
                    </div>
                    <span className="t-caption text-[color:var(--color-text-muted)]">
                      <Reference row={row} />
                    </span>
                    <div className="ml-auto text-right">
                      <p className={`font-display text-lg font-semibold tabular-nums ${row.direction === 'in' ? 'text-positive' : 'text-negative'}`}>
                        {row.direction === 'in' ? '+' : '−'} {money(row.amount)}
                      </p>
                      <p className={`t-caption tabular-nums ${row.balance < 0 ? 'text-negative' : 'text-[color:var(--color-text-faint)]'}`}>balance {money(row.balance)}</p>
                    </div>
                    {row.reconciled && <CircleCheck className="h-5 w-5 shrink-0 text-positive" role="img" aria-label="On a bank statement" />}
                    {canWrite && row.source === 'entry' && (
                      <button
                        type="button"
                        onClick={() => {
                          setVoiding(row)
                          setReason('')
                          setVoidError('')
                        }}
                        className="interactive inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold text-[color:var(--color-text-muted)] hover:bg-negative-dim hover:text-negative"
                      >
                        <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                        Void
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      {!lumen && data && data.rows.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[52rem] text-sm">
            <caption className="sr-only">Bank ledger</caption>
            <thead>
              <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                <th scope="col" className="px-4 py-2.5 font-medium">Date</th>
                {showAccount && <th scope="col" className="px-2 py-2.5 font-medium">Account</th>}
                <th scope="col" className="px-2 py-2.5 font-medium">What</th>
                <th scope="col" className="px-2 py-2.5 font-medium">Reference</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">In</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Out</th>
                <th scope="col" className="px-2 py-2.5 text-right font-medium">Balance</th>
                <th scope="col" className="px-2 py-2.5 text-center font-medium"><span className="sr-only">On a statement</span></th>
                {canWrite && <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={`${row.source}:${row.source_ref}`} className="border-b border-[color:var(--color-border)]/60 align-top hover:bg-muted/40">
                  <td className="whitespace-nowrap px-4 py-2.5 tabular-nums">{day(row.move_date)}</td>
                  {showAccount && <td className="whitespace-nowrap px-2 py-2.5 text-xs text-[color:var(--color-text-muted)]">{row.account_name}</td>}
                  <td className="px-2 py-2.5">
                    <div className="font-medium">{row.counterparty || row.category_label}</div>
                    <div className="text-xs text-[color:var(--color-text-muted)]">
                      <span className="mr-1.5 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide">{row.category_label}</span>
                      <BillText text={row.description} />
                    </div>
                  </td>
                  <td className="px-2 py-2.5 text-xs text-[color:var(--color-text-muted)]"><Reference row={row} /></td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-positive">{row.direction === 'in' ? money(row.amount) : ''}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-negative">{row.direction === 'out' ? money(row.amount) : ''}</td>
                  <td className={`whitespace-nowrap px-2 py-2.5 text-right font-medium tabular-nums ${row.balance < 0 ? 'text-negative' : ''}`}>{money(row.balance)}</td>
                  <td className="px-2 py-2.5 text-center">
                    {row.reconciled ? <CircleCheck className="inline h-4 w-4 text-positive" role="img" aria-label="On a bank statement" /> : null}
                  </td>
                  {canWrite && (
                    <td className="px-4 py-2.5 text-right">
                      {row.source === 'entry' && (
                        <button
                          type="button"
                          onClick={() => {
                            setVoiding(row)
                            setReason('')
                            setVoidError('')
                          }}
                          className="interactive inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[color:var(--color-text-muted)] hover:bg-muted hover:text-negative"
                        >
                          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Void
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && last > 1 && (
        <nav aria-label="Pages" className="flex items-center justify-between">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Newer
          </Button>
          <span className="t-caption">
            Page {page} of {last}
          </span>
          <Button variant="secondary" size="sm" disabled={page >= last} onClick={() => setPage(page + 1)}>
            Older
          </Button>
        </nav>
      )}

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

      <Modal
        open={voiding !== null}
        title="Void this entry"
        onClose={() => setVoiding(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setVoiding(null)} disabled={busy}>
              Keep it
            </Button>
            <Button variant="danger" onClick={doVoid} loading={busy}>
              Void entry
            </Button>
          </>
        }
      >
        {voiding && (
          <div className="space-y-4">
            <p className="text-sm">
              {voiding.direction === 'in' ? 'Money in' : 'Money out'} of <span className="font-semibold tabular-nums">{money(voiding.amount)}</span> on {day(voiding.move_date)} ({voiding.category_label}). It stops counting toward the balance and is
              kept in the history. If a statement line was matched to it, that line goes back to unmatched.
            </p>
            <Field label="Why is it wrong" required>
              <Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="For example: entered twice" />
            </Field>
            {voidError && <Alert variant="error">{voidError}</Alert>}
          </div>
        )}
      </Modal>
    </div>
  )
}
