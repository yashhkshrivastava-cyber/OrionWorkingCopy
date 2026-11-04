import { useEffect, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
import { ApiError, bankApi } from '../../api/client'
import { day, money, todayIso } from '../../bank/format'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field, Input, Select } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { MoneyInput } from '../../components/ui/MoneyInput'
import { useToast } from '../../components/ui/Toast'
import type { BankAccountKind, BankAccountPreview, BankActivityRow } from '../../types'
import { useBank } from './bankContext'

const OPENING = /^-?\d+(\.\d{1,2})?$/

/** One line of plain words for each thing recorded in the history. */
function describe(row: BankActivityRow): string {
  const d = row.detail as Record<string, unknown>
  const amount = typeof d.amount === 'number' || typeof d.amount === 'string' ? money(Number(d.amount)) : ''
  switch (row.action) {
    case 'account.create':
      return `Set up the account with an opening balance of ${money(Number(d.opening_balance))} on ${day(String(d.opening_date))}`
    case 'account.update': {
      const to = (d.to ?? {}) as Record<string, unknown>
      const from = (d.from ?? {}) as Record<string, unknown>
      return `Changed the account: opening balance ${money(Number(from.opening_balance))} on ${day(String(from.opening_date))} became ${money(Number(to.opening_balance))} on ${day(String(to.opening_date))}`
    }
    case 'entry.create':
      return `Added ${d.direction === 'in' ? 'money in' : 'money out'} of ${amount} (${String(d.category).replace(/_/g, ' ')}) dated ${day(String(d.date))}`
    case 'entry.void':
      return `Voided an entry of ${amount}: ${String(d.reason ?? '')}`
    case 'statement.import':
      return `Uploaded ${String(d.filename)}: ${String(d.new)} new line${d.new === 1 ? '' : 's'}, ${String(d.duplicates)} already known, ${String(d.auto_matched)} matched by Orion`
    case 'statement.remove':
      return `Took back the upload ${String(d.filename)} (${String(d.lines)} lines)`
    case 'match.auto':
      return `Orion matched ${String(d.matched)} statement line${d.matched === 1 ? '' : 's'} that were certain`
    case 'match.manual':
      return `Matched a statement line of ${amount} by hand`
    case 'match.remove':
      return `Unmatched a statement line`
    case 'line.ignore':
      return `Set aside a statement line of ${amount}: ${String(d.reason ?? '')}`
    case 'line.unignore':
      return `Brought back a statement line that had been set aside`
    default:
      return row.action
  }
}

/** The account the book is kept for, and the opening balance everything starts from. Changing that figure moves every balance, so it is confirmed. */
export function BankAccountPage() {
  const { account, accounts, setScope, canWrite, version, accountChanged } = useBank()
  const toast = useToast()
  // `creating` is the form for a new account; otherwise it edits the account chosen in the switcher
  const [creating, setCreating] = useState(!account.configured)
  const [kind, setKind] = useState<BankAccountKind>(account.account_kind ?? 'bank')
  const [name, setName] = useState(account.account_name ?? 'Current account')
  const [bank, setBank] = useState(account.bank_name ?? '')
  const [last4, setLast4] = useState(account.account_last4 ?? '')
  const [opening, setOpening] = useState(account.opening_balance !== undefined ? String(account.opening_balance) : '')
  const [openingDate, setOpeningDate] = useState(account.opening_date ?? '')
  const [floor, setFloor] = useState(account.low_balance_floor != null ? String(account.low_balance_floor) : '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const working = useRef(false)
  const [confirming, setConfirming] = useState<BankAccountPreview | null>(null)
  const [history, setHistory] = useState<BankActivityRow[] | null>(null)

  // Choosing another account in the switcher shows that account in the form.
  const shownId = account.account_id
  useEffect(() => {
    if (!account.configured) return
    setCreating(false)
    setKind(account.account_kind ?? 'bank')
    setName(account.account_name ?? '')
    setBank(account.bank_name ?? '')
    setLast4(account.account_last4 ?? '')
    setOpening(account.opening_balance !== undefined ? String(account.opening_balance) : '')
    setOpeningDate(account.opening_date ?? '')
    setError('')
  }, [shownId]) // eslint-disable-line react-hooks/exhaustive-deps -- only a different account resets the form; typing must not

  useEffect(() => {
    let live = true
    bankApi
      .activity(100)
      .then((r) => live && setHistory(r.activity))
      .catch(() => live && setHistory([]))
    return () => {
      live = false
    }
  }, [version])

  const startNew = () => {
    setCreating(true)
    setKind('bank')
    setName('')
    setBank('')
    setLast4('')
    setOpening('')
    setOpeningDate('')
    setError('')
  }

  const input = () => ({
    account_id: creating ? undefined : account.account_id,
    account_kind: kind,
    account_name: name.trim(),
    bank_name: bank.trim(),
    account_last4: last4.trim(),
    opening_balance: opening.trim(),
    opening_date: openingDate,
    low_balance_floor: floor.trim(),
  })

  const problem = (): string => {
    if (!name.trim()) return 'Give the account a name.'
    if (last4.trim() && !/^\d{4}$/.test(last4.trim())) return 'Give the last four digits of the account number, or leave it empty.'
    if (!OPENING.test(opening.trim())) return 'Enter the opening balance as a number, for example 250000 or 250000.50.'
    if (!openingDate) return 'Choose the day the opening balance was true.'
    if (openingDate > todayIso()) return 'The opening day cannot be in the future.'
    return ''
  }

  const send = async (confirm: boolean) => {
    if (working.current) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      const saved = creating && account.configured ? await bankApi.createAccount(input()) : await bankApi.saveAccount({ ...input(), confirm })
      setConfirming(null)
      accountChanged(saved)
      toast.show(creating ? 'Account added' : 'Account updated', { detail: `The balance is now ${money(saved.balance)}.` })
    } catch (err) {
      setConfirming(null)
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'That did not save. Try again.')
    } finally {
      working.current = false
      setBusy(false)
    }
  }

  const submit = async () => {
    const found = problem()
    if (found) return setError(found)
    setError('')
    const changed = !creating && account.configured && (Number(opening) !== account.opening_balance || openingDate !== account.opening_date)
    if (!changed) return send(false)
    try {
      setConfirming(await bankApi.previewAccount(opening.trim(), openingDate, account.account_id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not work out the effect of that change.')
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-5">
      {accounts.length > 0 && (
        <section aria-label="Accounts" className="panel p-5 lg:col-span-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="t-h3">Your accounts</h2>
              <p className="t-caption mt-0.5">Bank accounts and cash. Each has its own balance and its own opening balance; a payment, an expense or an entry says which account it moved in.</p>
            </div>
            {canWrite && (
              <Button variant="secondary" size="sm" onClick={startNew}>
                <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                Add an account
              </Button>
            )}
          </div>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {accounts.map((a) => (
              <li key={a.account_id}>
                <button
                  type="button"
                  onClick={() => {
                    setScope(a.account_id ?? null)
                    setCreating(false)
                  }}
                  aria-pressed={!creating && a.account_id === account.account_id}
                  className={`interactive w-full rounded-xl border p-3 text-left ${!creating && a.account_id === account.account_id ? 'border-accent bg-accent-dim/40' : 'border-[color:var(--color-border)] hover:bg-muted'}`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{a.account_name}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide">{a.account_kind === 'cash' ? 'Cash' : 'Bank'}</span>
                  </span>
                  <span className="mt-1 block text-lg font-semibold tabular-nums">{money(a.balance)}</span>
                  <span className="t-caption">{a.bank_name ? `${a.bank_name} · ` : ''}opened {day(a.opening_date)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Account" className="panel space-y-4 p-5 lg:col-span-2">
        <div>
          <h2 className="t-h3">{creating ? (account.configured ? 'Add an account' : 'Set up the account') : account.account_name}</h2>
          <p className="t-caption mt-0.5">
            Orion keeps the balance for you. Tell it what the bank held on one day, and it adds and takes away from there: clients’ payments, expenses and GST paid come from the bills and expenses
            it already has, and you add the rest (interest, charges, loans) on the Ledger.
          </p>
        </div>
        <fieldset disabled={!canWrite || busy} className="space-y-4">
          <Field label="Kind" hint={kind === 'cash' ? 'Cash has no bank statement: it is counted, not reconciled.' : 'A bank account is checked against its statement.'}>
            <Select value={kind} onChange={(e) => setKind(e.target.value as BankAccountKind)} aria-label="Kind of account">
              <option value="bank">Bank account</option>
              <option value="cash">Cash (petty cash, a cash box)</option>
            </Select>
          </Field>
          <Field label="Account name" required>
            <Input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Bank">
              <Input value={bank} maxLength={80} onChange={(e) => setBank(e.target.value)} placeholder="Optional" />
            </Field>
            <Field label="Last four digits" hint="Only the last four, to tell accounts apart.">
              <Input value={last4} inputMode="numeric" maxLength={4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, ''))} placeholder="Optional" />
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Opening balance (₹)" required hint="What the bank held at the start of that day. An overdraft is a negative number.">
              <MoneyInput value={opening} allowNegative onChange={setOpening} placeholder="2,50,000.00" />
            </Field>
            <Field label="As on" required hint="Money before this day is already inside the balance.">
              <Input type="date" value={openingDate} max={todayIso()} onChange={(e) => setOpeningDate(e.target.value)} />
            </Field>
          </div>
          <Field
            label="Minimum balance (₹)"
            hint="Optional. Orion warns on the Overview and in the Copilot when this account is below it, or when the accounts together are expected to fall below their minimums within two weeks. It only warns."
          >
            <MoneyInput value={floor} allowNegative onChange={setFloor} placeholder="Leave empty for no warning" />
          </Field>
        </fieldset>
        {error && <Alert variant="error">{error}</Alert>}
        {canWrite ? (
          <Button onClick={submit} loading={busy}>
            {creating ? (account.configured ? 'Add the account' : 'Set up the account') : 'Save changes'}
          </Button>
        ) : (
          <p className="t-caption">You can see the account but not change it.</p>
        )}
        {account.configured && !creating && (
          <p className="rounded-xl bg-muted px-3 py-2 text-sm">
            Balance today: <span className="font-semibold tabular-nums">{money(account.balance)}</span>
          </p>
        )}
      </section>

      <section aria-label="History" className="panel p-5 lg:col-span-3">
        <h2 className="t-h3">What has been done</h2>
        <p className="t-caption mt-0.5">Every change to the account, entries, uploads and matches, newest first. It cannot be edited.</p>
        {history === null ? (
          <p className="t-small mt-4 text-[color:var(--color-text-muted)]">Loading…</p>
        ) : history.length === 0 ? (
          <p className="t-small mt-4 text-[color:var(--color-text-muted)]">Nothing yet.</p>
        ) : (
          <ol className="mt-4 divide-y divide-[color:var(--color-border)]/60">
            {history.map((row) => (
              <li key={row.audit_id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2.5 text-sm">
                <span className="min-w-0 flex-1">{describe(row)}</span>
                <span className="t-caption whitespace-nowrap">
                  {row.username ?? 'Someone'} · {new Date(row.occurred).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <Modal
        open={confirming !== null}
        title="Change the opening balance?"
        onClose={() => setConfirming(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirming(null)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => send(true)} loading={busy}>
              Yes, change it
            </Button>
          </>
        }
      >
        {confirming && (
          <div className="space-y-3 text-sm">
            <p>This changes every balance Orion shows, on this page, the dashboards and in the Copilot.</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-xl bg-muted px-4 py-3">
              <dt className="text-[color:var(--color-text-muted)]">Balance today</dt>
              <dd className="text-right font-semibold tabular-nums">{money(confirming.current_balance)}</dd>
              <dt className="text-[color:var(--color-text-muted)]">Becomes</dt>
              <dd className="text-right font-semibold tabular-nums">{money(confirming.new_balance)}</dd>
            </dl>
            <p className="t-caption">The old figure and who changed it are kept in the history.</p>
          </div>
        )}
      </Modal>
    </div>
  )
}
