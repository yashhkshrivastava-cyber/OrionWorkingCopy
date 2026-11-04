import { useRef, useState } from 'react'
import { HandCoins, Plus, Undo2, X } from 'lucide-react'
import { api } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { money } from '../../billing/billCalc'
import { Alert, Badge } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MoneyInput } from '../ui/MoneyInput'
import { AccountPicker, rememberAccount } from './AccountPicker'
import { formatDay } from './BillDocument'
import type { BillRevenueEntry, DeductionKind, SavedBill, TdsSuggestion } from '../../types'

const todayIso = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

const STATUS = {
  Committed: { label: 'Received', badge: 'emerald' },
  Prospective: { label: 'To receive', badge: 'amber' },
  Cancelled: { label: 'Cancelled', badge: 'default' },
} as const

/** One deduction as it is being typed: kept as text, checked and sent when the payment is recorded. */
interface DeductionRow {
  key: number
  kind: DeductionKind
  amount: string
  section: string
  rate: string
  reason: string
  /** The amount is still the one suggested from the rate, so a change of rate may change it. */
  suggested: boolean
}

const KINDS: DeductionKind[] = ['TDS', 'Penalty', 'Rounding', 'Other']
const HINT: Record<DeductionKind, string> = {
  TDS: 'Tax the client deducted at source. It is claimed back through Form 26AS.',
  Penalty: 'A deduction for late or short service. Say why. It is a loss: it counts as a cost and lowers the margin.',
  Rounding: 'A few rupees the client rounded off (up to ₹ 10). Counts as a small cost.',
  Other: 'A short payment or anything else the client held back. Say why. It counts as a cost and lowers the margin.',
}

/** What a client deducting TDS at this rate would hold back from the payment that settles `settled` of the bill (TDS is on the taxable value, not the GST). */
function suggestedTds(settled: number, bill: SavedBill, rate: number): number {
  if (!(settled > 0) || !(bill.grand_total > 0) || !(rate > 0)) return 0
  return Math.round(((settled * bill.taxable_total) / bill.grand_total) * rate) / 100
}

const numberOf = (text: string) => {
  const n = Number(text)
  return text.trim() !== '' && Number.isFinite(n) ? n : 0
}

function Figure({ label, value, tone = '' }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <dt className="text-xs font-medium text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className={`font-display mt-1 text-xl font-bold tabular-nums ${tone || 'text-[color:var(--color-text)]'}`}>
        ₹ {money(value)}
      </dd>
    </div>
  )
}

/**
 * What has been received against a bill and what is still to come. Each row is a revenue
 * entry (case transaction) the bill owns: recording a payment turns "to receive" into
 * "received", in full or in part.
 */
export function BillPayments({
  bill,
  canWrite,
  isAdmin,
  onChange,
}: {
  bill: SavedBill
  canWrite: boolean
  isAdmin: boolean
  onChange: (bill: SavedBill) => void
}) {
  const [recording, setRecording] = useState(false)
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState(todayIso)
  const [accountId, setAccountId] = useState<number | undefined>(undefined)
  const [held, setHeld] = useState<DeductionRow[]>([])
  const [suggestion, setSuggestion] = useState<TdsSuggestion | null>(null)
  // The cash defaults to what is left after what the client held back, until the person types the cash themselves.
  const cashTyped = useRef(false)
  const rowKey = useRef(0)
  const [reversing, setReversing] = useState<BillRevenueEntry | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // A key for each time the form is opened, kept for every attempt at that payment (a second click, a retry after a dropped
  // connection); opening the form again is a new payment and gets a new key. See api/idempotency.ts.
  const idemKey = useRef(newIdempotencyKey())
  const busyRef = useRef(false)

  const revenue = bill.revenue
  if (!revenue) return null

  const issued = bill.status === 'Issued'
  const { received, remaining, entries } = revenue
  const share = bill.grand_total - revenue.credited > 0 ? Math.min(100, (received / (bill.grand_total - revenue.credited)) * 100) : 0
  const entered = Number(amount)
  const heldTotal = held.reduce((sum, row) => sum + numberOf(row.amount), 0)
  const settles = (Number.isFinite(entered) ? entered : 0) + heldTotal
  const heldOk = held.every(
    (row) =>
      numberOf(row.amount) > 0 && (row.kind !== 'TDS' || row.section.trim() !== '') && (!['Penalty', 'Other'].includes(row.kind) || row.reason.trim() !== ''),
  )
  const valid = amount.trim() !== '' && Number.isFinite(entered) && entered > 0 && settles <= remaining + 0.004 && heldOk
  const leaves = valid ? Math.max(0, remaining - settles) : null

  const open = () => {
    setAmount(remaining.toFixed(2))
    setDay(todayIso())
    setAccountId(undefined)
    setHeld([])
    setSuggestion(null)
    cashTyped.current = false
    setError('')
    idemKey.current = newIdempotencyKey()
    setRecording(true)
    // What this client was last deducted under: only a hint for the section and rate, so a failure to ask costs nothing.
    api.tdsSuggestion(bill.id).then(setSuggestion).catch(() => setSuggestion(null))
  }

  const changeRows = (next: DeductionRow[]) => {
    setHeld(next)
    if (!cashTyped.current) setAmount(Math.max(0, remaining - next.reduce((sum, row) => sum + numberOf(row.amount), 0)).toFixed(2))
  }

  const addRow = (kind: DeductionKind) => {
    rowKey.current += 1
    const section = suggestion?.section ?? '194C'
    const rate = String(suggestion?.rate ?? 2)
    const amountText = kind === 'TDS' ? suggestedTds(remaining, bill, Number(rate)).toFixed(2) : ''
    changeRows([...held, { key: rowKey.current, kind, amount: amountText === '0.00' ? '' : amountText, section: kind === 'TDS' ? section : '', rate: kind === 'TDS' ? rate : '', reason: '', suggested: kind === 'TDS' }])
  }

  const changeRow = (key: number, patch: Partial<DeductionRow>) =>
    changeRows(
      held.map((row) => {
        if (row.key !== key) return row
        const next = { ...row, ...patch, suggested: 'amount' in patch ? false : row.suggested }
        if (next.kind === 'TDS' && next.suggested && 'rate' in patch) {
          const text = suggestedTds(remaining, bill, numberOf(next.rate)).toFixed(2)
          next.amount = text === '0.00' ? '' : text
        }
        return next
      }),
    )

  const record = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError('')
    try {
      const deductions = held.map((row) => ({
        kind: row.kind,
        amount: row.amount.trim(),
        ...(row.kind === 'TDS' ? { section: row.section.trim(), rate: row.rate.trim() } : {}),
        ...(row.reason.trim() ? { reason: row.reason.trim() } : {}),
      }))
      onChange(await api.recordBillPayment(bill.id, amount.trim(), day, idemKey.current, accountId, deductions))
      rememberAccount(accountId)
      setRecording(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const reverse = async () => {
    if (!reversing) return
    setBusy(true)
    setError('')
    try {
      onChange(await api.reverseBillPayment(bill.id, reversing.id))
      setReversing(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Payments" className="panel">
      <header className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4 sm:px-5">
        <div>
          <h3 className="t-h3 text-[color:var(--color-text)]">Payments</h3>
          <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
            Recorded against the case as revenue: received is committed, the rest is prospective.
          </p>
        </div>
        {canWrite && issued && remaining > 0 && bill.case_code && (
          <Button size="sm" onClick={open}>
            <HandCoins className="h-4 w-4" /> Record payment
          </Button>
        )}
      </header>

      <div className="px-4 pb-4 pt-4 sm:px-5">
        <dl className={`grid gap-4 ${revenue.deducted > 0 || revenue.credited > 0 ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-3'}`}>
          <Figure label="Billed" value={bill.grand_total} />
          {revenue.credited > 0 && <Figure label="Credited" value={revenue.credited} />}
          <Figure label="Received" value={received - revenue.deducted} tone={received > 0 ? 'text-positive' : ''} />
          {revenue.deducted > 0 && <Figure label="Held back by the client" value={revenue.deducted} />}
          <Figure label="Still to receive" value={remaining} tone={remaining > 0 ? 'text-warning' : ''} />
        </dl>
        <div
          className="mt-4 h-2 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(share)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Share of the bill received"
        >
          <div className="h-full rounded-full bg-positive transition-[width] duration-500" style={{ width: `${share}%` }} />
        </div>
        <p className="mt-1.5 text-xs text-[color:var(--color-text-muted)]">
          {!issued
            ? 'This bill is cancelled, so nothing is to be received.'
            : remaining <= 0
              ? 'Received in full.'
              : !bill.case_code
                ? 'Tag this bill to a case, by editing it, to start recording payments.'
                : `${share.toFixed(0)}% received.`}
        </p>
      </div>

      {entries.length > 0 && (
        <div className="overflow-x-auto border-t border-[color:var(--color-border)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-faint)]">
                <th className="px-4 py-2 sm:px-5">Revenue entry</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Received on</th>
                <th className="px-4 py-2 text-right">Amount</th>
                <th className="px-4 py-2 sm:px-5" />
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="border-t border-[color:var(--color-border)]">
                  <td className="px-4 py-2 font-medium tabular-nums text-[color:var(--color-text)] sm:px-5">{entry.id}</td>
                  <td className="px-4 py-2">
                    <Badge variant={STATUS[entry.status].badge}>{STATUS[entry.status].label}</Badge>
                  </td>
                  <td className="px-4 py-2 text-[color:var(--color-text-muted)]">
                    {entry.received_date ? formatDay(entry.received_date) : '—'}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums text-[color:var(--color-text)]">
                    ₹ {money(entry.amount)}
                    {entry.deductions.length > 0 && (
                      <span className="block text-xs text-[color:var(--color-text-muted)]">
                        ₹ {money(entry.cash)} received
                        {entry.deductions.map((d) => ` + ₹ ${money(d.amount)} ${d.kind === 'TDS' ? `TDS (${d.section})` : d.kind.toLowerCase()}`).join('')}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right sm:px-5">
                    {isAdmin && issued && entry.status === 'Committed' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setError('')
                          setReversing(entry)
                        }}
                      >
                        <Undo2 className="h-3.5 w-3.5" /> Reverse
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={recording}
        title={`Record payment for bill ${bill.bill_number}`}
        onClose={() => setRecording(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRecording(false)}>
              Cancel
            </Button>
            <Button onClick={record} loading={busy} disabled={!valid || !day}>
              Record payment
            </Button>
          </>
        }
      >
        <dl className="mb-4 grid grid-cols-3 gap-3 rounded-xl bg-muted/70 px-4 py-3 text-sm">
          <div>
            <dt className="text-xs text-[color:var(--color-text-muted)]">Billed</dt>
            <dd className="font-semibold tabular-nums">₹ {money(bill.grand_total)}</dd>
          </div>
          <div>
            <dt className="text-xs text-[color:var(--color-text-muted)]">Received so far</dt>
            <dd className="font-semibold tabular-nums">₹ {money(received)}</dd>
          </div>
          <div>
            <dt className="text-xs text-[color:var(--color-text-muted)]">Still to receive</dt>
            <dd className="font-semibold tabular-nums">₹ {money(remaining)}</dd>
          </div>
        </dl>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Cash received in the account" required>
            <MoneyInput
              value={amount}
              onChange={(raw) => {
                cashTyped.current = true
                setAmount(raw)
              }}
            />
          </Field>
          <Field label="Date received" required>
            <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </Field>
        </div>
        <div className="mt-3">
          <AccountPicker value={accountId} onChange={setAccountId} label="Received into" />
        </div>

        <fieldset className="mt-4 rounded-xl border border-[color:var(--color-border)] px-3 pb-3 pt-2">
          <legend className="px-1 text-xs font-semibold text-[color:var(--color-text-muted)]">Held back by the client (optional)</legend>
          {held.length === 0 && (
            <p className="text-xs text-[color:var(--color-text-muted)]">
              If the client paid less because it deducted TDS or anything else, add it here so the bill closes. The bank gets only the cash.
            </p>
          )}
          <ul className="space-y-3">
            {held.map((row) => (
              <li key={row.key} className="rounded-lg bg-muted/60 p-2.5">
                <div className="flex flex-wrap items-end gap-2">
                  <Field label="What" className="w-32">
                    <Select value={row.kind} onChange={(e) => changeRow(row.key, { kind: e.target.value as DeductionKind })} aria-label="What was held back">
                      {KINDS.map((kind) => (
                        <option key={kind} value={kind}>
                          {kind}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {row.kind === 'TDS' && (
                    <>
                      <Field label="Section" className="w-28">
                        <Input
                          list="tds-sections"
                          value={row.section}
                          onChange={(e) => changeRow(row.key, { section: e.target.value.toUpperCase() })}
                          aria-label="TDS section"
                          maxLength={8}
                        />
                      </Field>
                      <Field label="Rate %" className="w-20">
                        <Input
                          inputMode="decimal"
                          value={row.rate}
                          onChange={(e) => changeRow(row.key, { rate: e.target.value.replace(/[^0-9.]/g, '') })}
                          aria-label="TDS rate in percent"
                        />
                      </Field>
                    </>
                  )}
                  <Field label="Amount" className="min-w-[9rem] flex-1">
                    <MoneyInput value={row.amount} onChange={(raw) => changeRow(row.key, { amount: raw })} words={false} aria-label={`${row.kind} amount`} />
                  </Field>
                  <button
                    type="button"
                    onClick={() => changeRows(held.filter((r) => r.key !== row.key))}
                    className="mb-1 rounded-lg p-2 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] focus-visible:ring-2 focus-visible:ring-accent"
                    aria-label={`Remove this ${row.kind} deduction`}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                {row.kind !== 'TDS' && row.kind !== 'Rounding' && (
                  <div className="mt-2">
                    <Field label="Why">
                      <Input value={row.reason} onChange={(e) => changeRow(row.key, { reason: e.target.value })} maxLength={300} aria-label="Why it was held back" />
                    </Field>
                  </div>
                )}
                <p className="mt-1.5 text-xs text-[color:var(--color-text-faint)]">
                  {HINT[row.kind]}
                  {row.kind === 'TDS' && suggestion && (
                    <>
                      {' '}
                      {suggestion.source === 'last' ? 'Section and rate are what this client last deducted under.' : 'The rate is only a usual one: use what the client deducted.'}
                    </>
                  )}
                </p>
              </li>
            ))}
          </ul>
          <datalist id="tds-sections">
            {(suggestion?.sections ?? []).map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </datalist>
          <div className="mt-2 flex flex-wrap gap-2">
            {KINDS.filter((kind) => kind !== 'TDS' || !held.some((row) => row.kind === 'TDS')).map((kind) => (
              <Button key={kind} type="button" variant="secondary" size="sm" onClick={() => addRow(kind)} disabled={held.length >= 6}>
                <Plus className="h-3.5 w-3.5" /> {kind === 'TDS' ? 'TDS deducted' : kind}
              </Button>
            ))}
          </div>
        </fieldset>

        <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
          {held.length > 0 && Number.isFinite(entered) && entered > 0 && (
            <span className="mb-1 block tabular-nums text-[color:var(--color-text)]">
              ₹ {money(entered)} received + ₹ {money(heldTotal)} held back = ₹ {money(settles)} off the bill.{' '}
            </span>
          )}
          {leaves === null
            ? settles > remaining + 0.004
              ? `The cash and what was held back come to more than the ₹ ${money(remaining)} still to be received.`
              : !heldOk
                ? 'Give each deduction an amount, the TDS its section, and a reason for a penalty or anything else.'
                : `Enter an amount up to ₹ ${money(remaining)}.`
            : leaves < 0.005
              ? 'This settles the bill: all of it becomes committed revenue.'
              : `Part payment: ₹ ${money(settles)} becomes committed revenue and ₹ ${money(leaves)} stays to be received.`}
        </p>
        <p className="mt-1 text-xs text-[color:var(--color-text-faint)]">
          Once recorded, a payment cannot be edited. Only an admin can reverse it.
        </p>
        {error && (
          <div className="mt-3">
            <Alert variant="error">{error}</Alert>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(reversing)}
        title="Reverse this payment"
        onClose={() => setReversing(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReversing(null)}>
              Keep payment
            </Button>
            <Button variant="danger" onClick={reverse} loading={busy}>
              Reverse payment
            </Button>
          </>
        }
      >
        {reversing && (
          <p className="text-sm text-[color:var(--color-text-muted)]">
            ₹ {money(reversing.amount)}
            {reversing.deductions.length > 0 ? ` (₹ ${money(reversing.cash)} received and ₹ ${money(reversing.amount - reversing.cash)} held back by the client)` : ''}
            {reversing.received_date ? `, received on ${formatDay(reversing.received_date)},` : ''} will go back to
            being still to receive on bill {bill.bill_number}
            {reversing.deductions.length > 0 ? ', and what the client held back is taken off the TDS list' : ''}. Use this only to correct a payment
            recorded by mistake.
          </p>
        )}
        {error && (
          <div className="mt-3">
            <Alert variant="error">{error}</Alert>
          </div>
        )}
      </Modal>
    </section>
  )
}
