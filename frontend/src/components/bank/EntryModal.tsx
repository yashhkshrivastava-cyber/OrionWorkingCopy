import { useEffect, useRef, useState } from 'react'
import { ApiError, bankApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { amountOf, day, money, todayIso } from '../../bank/format'
import type { BankDirection, BankEntry, BankLine, BankMeta } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MoneyInput } from '../ui/MoneyInput'
import { Segmented } from '../ui/Segmented'

export type EntryPreset = { direction?: BankDirection; category?: string; counterparty?: string; description?: string; reference?: string }

/**
 * Money in or out that Orion has no record of: interest the bank paid, a charge it took, a loan, tax. (A client's payment is recorded on its bill and an
 * expense in Expenses; they reach the bank by themselves.) Made from a statement line, the date, direction and amount are the line's and only what it
 * was can be chosen. The form has one key for the whole time it is open, so a second click or a retry saves nothing twice; and a wrong entry is later
 * voided with a reason, never deleted.
 */
export function EntryModal({
  open,
  meta,
  openingDate,
  accounts = [],
  defaultAccountId,
  line,
  preset,
  onClose,
  onSaved,
}: {
  open: boolean
  meta: BankMeta
  /** With more than one, the person chooses which account the money moved in; the opening date is then that account's. */
  accounts?: { account_id?: number; account_name?: string; account_kind?: string; opening_date?: string }[]
  defaultAccountId?: number
  /** Entries before this day are already inside the opening balance. */
  openingDate?: string
  line?: BankLine | null
  preset?: EntryPreset
  onClose: () => void
  onSaved: (entry: BankEntry) => void
}) {
  const [direction, setDirection] = useState<BankDirection>('in')
  const [date, setDate] = useState(todayIso())
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [who, setWho] = useState('')
  const [note, setNote] = useState('')
  const [reference, setReference] = useState('')
  const [accountId, setAccountId] = useState<number | undefined>(defaultAccountId)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const key = useRef(newIdempotencyKey())
  const working = useRef(false)
  // What the form starts from is read when it opens; a parent that builds these again on every render must not wipe what is being typed.
  const start = useRef({ line, preset, meta, defaultAccountId })
  start.current = { line, preset, meta, defaultAccountId }
  const origin = `${line?.line_id ?? ''}|${JSON.stringify(preset ?? {})}`

  // A fresh form: a new key, and the fields from the line or the suggestion.
  useEffect(() => {
    if (!open) return
    const { line: from, preset: hint, meta: lists, defaultAccountId: account } = start.current
    setAccountId(account)
    key.current = newIdempotencyKey()
    working.current = false
    const way = from?.direction ?? hint?.direction ?? 'in'
    setDirection(way)
    setDate(from?.line_date ?? todayIso())
    setAmount(from ? String(from.amount) : '')
    // Nothing is pre-chosen unless Orion or the assistant recognised the line: a wrong default saved without looking is worse than one more click.
    setCategory(hint?.category && lists.entry_categories[way].some((c) => c.key === hint.category) ? hint.category : '')
    setWho(hint?.counterparty ?? '')
    setNote(hint?.description ?? from?.description ?? '')
    setReference(hint?.reference ?? from?.reference ?? '')
    setError('')
    setBusy(false)
  }, [open, origin])

  const choices = meta.entry_categories[direction]
  const chosen = accounts.find((a) => a.account_id === accountId)
  const opens = chosen?.opening_date ?? openingDate
  const chooseDirection = (next: BankDirection) => {
    setDirection(next)
    setCategory('')
  }

  const save = async () => {
    if (working.current) return
    const paise = amountOf(amount)
    if (Number.isNaN(paise) || paise <= 0) return setError('Enter the amount as a number, for example 1250.75.')
    if (!category) return setError('Choose what this is.')
    if (category === 'other_receipt' && !note.trim()) return setError('Say what this receipt is for: who paid, and why there is no bill.')
    if (!date) return setError('Choose the date.')
    if (date > todayIso()) return setError('The date cannot be in the future: an entry records money that has already moved.')
    if (opens && date < opens) return setError(`That is before the opening date (${day(opens)}): it is already inside the opening balance.`)
    working.current = true
    setBusy(true)
    setError('')
    try {
      const body = { category, counterparty: who.trim(), description: note.trim(), reference: reference.trim() }
      const saved = line
        ? await bankApi.entryFromLine(line.line_id, body, key.current)
        : await bankApi.createEntry({ account_id: accountId, entry_date: date, direction, amount: amount.trim(), ...body }, key.current)
      onSaved(saved)
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'That did not save. Try again.')
      working.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={line ? 'Record this statement line' : 'Add a bank entry'}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy}>
            {line ? 'Record and match' : 'Save entry'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {line ? (
          <p className="rounded-xl bg-muted px-3 py-2 text-sm">
            <span className="font-medium">{line.direction === 'in' ? 'Money in' : 'Money out'}</span> of{' '}
            <span className="font-semibold tabular-nums">{money(line.amount)}</span> on {day(line.line_date)}: <span className="text-[color:var(--color-text-muted)]">{line.description || 'no narration'}</span>
          </p>
        ) : (
          <>
            <Segmented
              label="Money"
              value={direction}
              options={[
                { id: 'in', label: 'Money in' },
                { id: 'out', label: 'Money out' },
              ]}
              onChange={chooseDirection}
            />
            {accounts.length > 1 && (
              <Field label="Account" required hint="Where the money moved: a bank account, or cash.">
                <Select value={accountId ?? ''} onChange={(e) => setAccountId(Number(e.target.value))}>
                  {accounts.map((a) => (
                    <option key={a.account_id} value={a.account_id}>
                      {a.account_name} ({a.account_kind === 'cash' ? 'cash' : 'bank'})
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Date" required>
                <Input type="date" value={date} max={todayIso()} min={opens} onChange={(e) => setDate(e.target.value)} />
              </Field>
              <Field label="Amount (₹)" required>
                <MoneyInput value={amount} onChange={setAmount} placeholder="1,250.75" />
              </Field>
            </div>
          </>
        )}
        <Field
          label="What is it"
          required
          hint={direction === 'in' ? 'A client’s payment is recorded on its bill and reaches the bank by itself.' : 'An expense is entered in Expenses and reaches the bank when it is paid, in Bank > Payables.'}
        >
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Choose…</option>
            {choices.map((choice) => (
              <option key={choice.key} value={choice.key}>
                {choice.label}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={direction === 'in' ? 'From' : 'To'}>
            <Input value={who} maxLength={120} onChange={(e) => setWho(e.target.value)} placeholder="Optional" />
          </Field>
          <Field label="Reference">
            <Input value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} placeholder="Cheque, UTR or voucher number" />
          </Field>
        </div>
        <Field
          label="Note"
          required={category === 'other_receipt'}
          hint={
            category === 'other_receipt'
              ? 'A receipt with no bill needs a reason: who paid, and why it has no bill.'
              : category === 'salary'
                ? 'Salary lines marked paid in Bank > Payroll reach the bank by themselves. Use this only for salary paid outside Orion’s payroll lines, or it will count twice.'
                : undefined
          }
        >
          <Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Optional" />
        </Field>
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  )
}
