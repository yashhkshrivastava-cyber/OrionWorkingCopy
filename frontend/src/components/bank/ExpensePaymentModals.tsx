import { useEffect, useRef, useState } from 'react'
import { Undo2 } from 'lucide-react'
import { ApiError, payablesApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { amountOf, day, money, todayIso } from '../../bank/format'
import type { ExpensePayment, PayableDetail, PayableRow } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox, Field, Input, Select, Textarea } from '../ui/Field'
import { LoadingState } from '../ui/DataTable'
import { Modal } from '../ui/Modal'
import { MoneyInput } from '../ui/MoneyInput'

type Account = { account_id?: number; account_name?: string; account_kind?: string; opening_date?: string }

const REASON_MIN = 5

function Summary({ expense }: { expense: PayableRow }) {
  return (
    <dl className="grid grid-cols-2 gap-3 rounded-xl bg-muted/70 px-4 py-3 text-sm sm:grid-cols-4">
      <div className="min-w-0">
        <dt className="text-xs text-[color:var(--color-text-muted)]">Expense</dt>
        <dd className="truncate font-semibold">{expense.expense_type || expense.expense_code}</dd>
        <dd className="truncate text-xs text-[color:var(--color-text-muted)]">{expense.description || expense.case_name || expense.expense_code}</dd>
      </div>
      <div>
        <dt className="text-xs text-[color:var(--color-text-muted)]">Came to</dt>
        <dd className="font-semibold tabular-nums">{money(expense.total)}</dd>
      </div>
      <div>
        <dt className="text-xs text-[color:var(--color-text-muted)]">Paid so far</dt>
        <dd className="font-semibold tabular-nums">{money(expense.paid)}</dd>
      </div>
      <div>
        <dt className="text-xs text-[color:var(--color-text-muted)]">Still to pay</dt>
        <dd className="font-semibold tabular-nums">{money(expense.left)}</dd>
      </div>
    </dl>
  )
}

/**
 * Paying an expense: an amount (all that is left, or a part), the day, the account it left, and a reference. It moves the bank balance, so it is never a
 * tick: the person confirms what was paid, the server refuses a request that did not come from this screen or that was made against a stale view (it must say
 * how much had been paid when the page was opened), and the form has one key for as long as it is open, so a second click or a retry records nothing twice.
 */
export function PayExpenseModal({
  expense,
  accounts,
  defaultAccountId,
  onClose,
  onDone,
  onConflict,
}: {
  expense: PayableRow
  accounts: Account[]
  defaultAccountId?: number
  onClose: () => void
  onDone: (paid: number) => void
  onConflict: (message: string) => void
}) {
  const [amount, setAmount] = useState(expense.left.toFixed(2))
  const [date, setDate] = useState(todayIso())
  const [accountId, setAccountId] = useState<number | undefined>(defaultAccountId)
  const [reference, setReference] = useState('')
  const [sure, setSure] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const key = useRef(newIdempotencyKey())
  const working = useRef(false)
  const chosen = accounts.find((a) => a.account_id === accountId)
  const opens = chosen?.opening_date
  const paying = amountOf(amount)
  const amountOk = !Number.isNaN(paying) && paying > 0 && paying <= expense.left + 0.004
  const dateOk = Boolean(date) && date <= todayIso() && (!opens || date >= opens)
  const ready = sure && amountOk && dateOk
  const after = amountOk ? Math.max(expense.left - paying, 0) : expense.left

  const confirm = async () => {
    if (working.current || !ready) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      await payablesApi.pay(
        expense.expense_code,
        { amount: amount.trim(), paid_date: date, account_id: accountId, reference: reference.trim(), seen_paid: expense.paid, confirm: true },
        key.current,
      )
      onDone(paying)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onConflict(err.message)
        return
      }
      setError(err instanceof Error ? err.message : 'That did not save. Try again.')
      working.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`Pay ${expense.expense_code}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={confirm} loading={busy} disabled={!ready}>
            {amountOk ? `Record ${money(paying)} paid` : 'Record payment'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Summary expense={expense} />
        <p className="text-sm">
          Record money that has already gone out. An expense can be paid in parts, on different days, from different accounts. Each payment is kept in its history,
          and reversing one needs a reason.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Amount paid (₹)" required hint={`Up to ${money(expense.left)}`}>
            <MoneyInput value={amount} onChange={setAmount} />
          </Field>
          <Field label="Day it was paid" required>
            <Input type="date" value={date} max={todayIso()} min={opens} onChange={(e) => setDate(e.target.value)} />
          </Field>
          {accounts.length > 1 && (
            <Field label="Paid from" required hint="The account the money left.">
              <Select value={accountId ?? ''} onChange={(e) => setAccountId(Number(e.target.value))}>
                {accounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.account_name} ({a.account_kind === 'cash' ? 'cash' : 'bank'})
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Reference">
            <Input value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} placeholder="Cheque, UTR or voucher number" />
          </Field>
        </div>
        {amount.trim() !== '' && !amountOk && <p className="text-xs text-negative">The amount must be a number of rupees and paise, more than zero and no more than is left to pay.</p>}
        {!dateOk && date && <p className="text-xs text-negative">{opens && date < opens ? `That is before the account's opening date (${day(opens)}).` : 'The day cannot be in the future.'}</p>}
        {amountOk && (
          <p className="text-sm text-[color:var(--color-text-muted)]">
            {after < 0.005 ? 'This pays the expense in full.' : `After this, ${money(after)} is still to pay.`}
            {chosen?.account_name ? ` It reduces ${chosen.account_name} by ${money(paying)} on ${day(date)}.` : ` It reduces the bank balance by ${money(paying)} on ${day(date)}.`}
          </p>
        )}
        <div className="rounded-xl border border-[color:var(--color-border-strong)] px-4 py-3">
          <Checkbox
            label={`I confirm that ${amountOk ? money(paying) : 'this amount'} was paid for ${expense.expense_code} on the day shown.`}
            checked={sure}
            onChange={setSure}
          />
        </div>
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  )
}

/** Every payment on an expense, reversed ones too (they are never deleted). A payment is taken back with a reason, and the money returns to its account. */
export function ExpensePaymentsModal({
  code,
  canWrite,
  onClose,
  onChanged,
}: {
  code: string
  canWrite: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const [detail, setDetail] = useState<PayableDetail | null>(null)
  const [error, setError] = useState('')
  const [reversing, setReversing] = useState<ExpensePayment | null>(null)
  const [reason, setReason] = useState('')
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  const [version, setVersion] = useState(0)
  const working = useRef(false)

  useEffect(() => {
    let live = true
    payablesApi
      .get(code)
      .then((found) => live && setDetail(found))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [code, version])

  const reverse = async () => {
    if (!reversing || working.current || reason.trim().length < REASON_MIN || !sure) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      await payablesApi.reverse(reversing.payment_id, reason.trim())
      setReversing(null)
      setReason('')
      setSure(false)
      setVersion((n) => n + 1)
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work.')
      if (err instanceof ApiError && err.status === 409) setVersion((n) => n + 1)
    } finally {
      working.current = false
      setBusy(false)
    }
  }

  return (
    <Modal open title={`Payments on ${code}`} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <div className="space-y-4">
        {error && <Alert variant="error">{error}</Alert>}
        {!detail && !error && <LoadingState message="Reading the payments…" />}
        {detail && (
          <>
            <Summary expense={detail} />
            {detail.payments.length === 0 ? (
              <p className="text-sm text-[color:var(--color-text-muted)]">Nothing has been paid on this expense yet.</p>
            ) : (
              <ul className="divide-y divide-[color:var(--color-border)]/60">
                {detail.payments.map((payment) => (
                  <li key={payment.payment_id} className="py-2.5 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className={payment.reversed ? 'text-[color:var(--color-text-muted)] line-through' : ''}>
                        <span className="tabular-nums">{day(payment.paid_date)}</span> · <span className="font-semibold tabular-nums">{money(payment.amount)}</span>
                        {payment.account_name ? <span className="text-[color:var(--color-text-muted)]"> · {payment.account_name}</span> : null}
                        {payment.reference ? <span className="text-[color:var(--color-text-muted)]"> · {payment.reference}</span> : null}
                      </div>
                      {!payment.reversed && canWrite && (
                        <button
                          type="button"
                          onClick={() => {
                            setReversing(payment)
                            setReason('')
                            setSure(false)
                            setError('')
                          }}
                          className="interactive inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[color:var(--color-text-muted)] hover:bg-muted hover:text-negative"
                        >
                          <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                          Reverse
                        </button>
                      )}
                    </div>
                    {payment.reversed && <p className="t-caption mt-0.5">Reversed {day(payment.reversed_timestamp)}: {payment.reversal_reason}</p>}
                    {reversing?.payment_id === payment.payment_id && (
                      <div className="mt-3 space-y-3 rounded-xl border border-[color:var(--color-border-strong)] p-3">
                        <p>
                          Taking this back means {money(payment.amount)} is owed on {code} again and returns to {payment.account_name || 'the account'} on the Bank pages. The payment stays in the history.
                        </p>
                        <Field label="Why is it being reversed" required>
                          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="For example: paid from the wrong account" />
                        </Field>
                        <Checkbox label="I understand this changes the bank balance." checked={sure} onChange={setSure} />
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" size="sm" onClick={() => setReversing(null)} disabled={busy}>
                            Keep it
                          </Button>
                          <Button variant="danger" size="sm" onClick={reverse} loading={busy} disabled={!sure || reason.trim().length < REASON_MIN}>
                            Reverse payment
                          </Button>
                        </div>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
