import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, payrollApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { day, money, month as monthName, todayIso } from '../../bank/format'
import type { PayrollMonth, PayrollRun, PayrollUnpaid } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Search } from 'lucide-react'
import { Checkbox, Field, Input, Select, Textarea } from '../ui/Field'
import { LoadingState } from '../ui/DataTable'
import { Modal } from '../ui/Modal'

type Account = { account_id?: number; account_name?: string; account_kind?: string; opening_date?: string }

const REASON_MIN = 5
/** "2026-09" as "Sep 2026". */
export const monthLabel = (value: string) => monthName(`${value}-01`)

/**
 * Marking a month's salary paid: one bank transfer pays many lines, so it is one pay run. The person chooses the lines that were paid (all of the month's
 * unpaid lines to begin with; a line left out stays owed), the day, the account and the bank reference, and confirms. The server refuses a request that did
 * not come from this screen or that was made against a stale view (it must say how many lines and how much the person saw), and the form has one key for
 * as long as it is open, so a second click or a retry pays nothing twice.
 */
export function MarkPaidModal({
  month,
  accounts,
  defaultAccountId,
  onClose,
  onDone,
  onConflict,
}: {
  month: PayrollMonth
  accounts: Account[]
  defaultAccountId?: number
  onClose: () => void
  onDone: (lines: number, total: number) => void
  onConflict: (message: string) => void
}) {
  const [data, setData] = useState<PayrollUnpaid | null>(null)
  const [error, setError] = useState('')
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [find, setFind] = useState('')
  const [caseCode, setCaseCode] = useState('')
  const [date, setDate] = useState(todayIso())
  const [accountId, setAccountId] = useState<number | undefined>(defaultAccountId)
  const [reference, setReference] = useState('')
  const [sure, setSure] = useState(false)
  const [busy, setBusy] = useState(false)
  const key = useRef(newIdempotencyKey())
  const working = useRef(false)

  useEffect(() => {
    let live = true
    payrollApi
      .unpaid(month.month_year)
      .then((found) => {
        if (!live) return
        setData(found)
        setChosen(new Set(found.lines.map((line) => line.code)))
      })
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [month.month_year])

  const picked = useMemo(() => (data ? data.lines.filter((line) => chosen.has(line.code)) : []), [data, chosen])
  // The lines the search shows: All and None act on these, so one name can be found and ticked among hundreds.
  const needle = find.trim().toLowerCase()
  const visible = useMemo(
    () =>
      data
        ? data.lines.filter(
            (line) => (!caseCode || (caseCode === 'none' ? !line.case_code : line.case_code === caseCode)) && (!needle || `${line.employee_name ?? ''} ${line.employee_code ?? ''}`.toLowerCase().includes(needle)),
          )
        : [],
    [data, needle, caseCode],
  )
  const total = useMemo(() => Math.round(picked.reduce((sum, line) => sum + Number(line.amount) * 100, 0)) / 100, [picked])
  const account = accounts.find((a) => a.account_id === accountId)
  const before = account?.opening_date && date < account.opening_date
  const dateOk = Boolean(date) && date <= todayIso()
  const needsAccount = accounts.length > 1 && accountId === undefined
  const ready = sure && picked.length > 0 && dateOk && !needsAccount

  const toggle = (code: string, on: boolean) =>
    setChosen((current) => {
      const next = new Set(current)
      if (on) next.add(code)
      else next.delete(code)
      return next
    })

  const confirm = async () => {
    if (working.current || !ready || !data) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      await payrollApi.record(
        {
          month_year: month.month_year,
          line_codes: picked.map((line) => line.code),
          seen_count: picked.length,
          seen_total: total.toFixed(2),
          paid_date: date,
          account_id: accountId,
          reference: reference.trim(),
          confirm: true,
        },
        key.current,
      )
      onDone(picked.length, total)
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
      title={`Mark ${monthLabel(month.month_year)} salary paid`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={confirm} loading={busy} disabled={!ready}>
            {picked.length > 0 ? `Record ${money(total)} paid` : 'Record pay run'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!data && !error && <LoadingState message="Reading the salary lines…" />}
        {error && <Alert variant="error">{error}</Alert>}
        {data && (
          <>
            <p className="text-sm">
              One bank transfer that paid these lines is one <span className="font-semibold">pay run</span>. It moves the bank balance on the day it was paid, and matches one line on the
              bank statement. Lines you leave out stay owed.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Day it was paid" required>
                <Input type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} />
              </Field>
              {accounts.length > 1 && (
                <Field label="Paid from" required hint="The account the transfer left.">
                  <Select value={accountId ?? ''} onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : undefined)}>
                    <option value="">Choose…</option>
                    {accounts.map((a) => (
                      <option key={a.account_id} value={a.account_id}>
                        {a.account_name} ({a.account_kind === 'cash' ? 'cash' : 'bank'})
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              <Field label="Bank reference" className={accounts.length > 1 ? '' : 'sm:col-span-2'}>
                <Input value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} placeholder="UTR or batch number of the transfer" />
              </Field>
            </div>
            {data.cases.length > 1 && (
              <Field label="Case" hint="Pay one case's salary at a time, or all of them together. Choosing a case ticks only its lines.">
                <Select
                  value={caseCode}
                  onChange={(e) => {
                    const next = e.target.value
                    setCaseCode(next)
                    setChosen(new Set(data.lines.filter((line) => !next || (next === 'none' ? !line.case_code : line.case_code === next)).map((line) => line.code)))
                  }}
                >
                  <option value="">All cases ({data.count} lines)</option>
                  {data.cases.map((c) => (
                    <option key={c.case_code ?? 'none'} value={c.case_code ?? 'none'}>
                      {c.case_name ?? 'No case'} ({c.lines} {c.lines === 1 ? 'line' : 'lines'}, {money(Number(c.total))})
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            {!dateOk && date && <p className="text-xs text-negative">The day cannot be in the future.</p>}
            {before && (
              <p className="text-xs text-warning">
                That is before {account?.account_name ?? 'the account'} opened ({day(account?.opening_date)}): that salary is already inside the opening balance, so this will not change the
                balance.
              </p>
            )}
            <div>
              <div className="flex items-center justify-between gap-3">
                <p className="t-label">
                  {picked.length} of {data.count} lines · <span className="tabular-nums">{money(total)}</span>
                </p>
                <div className="flex gap-3 text-xs">
                  <button
                    type="button"
                    className="font-medium text-accent hover:underline"
                    onClick={() => setChosen((current) => new Set([...current, ...visible.map((l) => l.code)]))}
                  >
                    {needle ? `Select ${visible.length} shown` : 'Select all'}
                  </button>
                  <button
                    type="button"
                    className="font-medium text-accent hover:underline"
                    onClick={() => setChosen((current) => new Set([...current].filter((code) => !visible.some((l) => l.code === code))))}
                  >
                    {needle ? 'Clear shown' : 'Clear all'}
                  </button>
                </div>
              </div>
              {data.lines.length > 8 && (
                <div className="relative mt-2">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
                  <Input aria-label="Find an employee" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find an employee" className="pl-9" />
                </div>
              )}
              <ul className="scroll-quiet mt-2 max-h-64 divide-y divide-[color:var(--color-border)]/60 overflow-y-auto rounded-xl border border-[color:var(--color-border)] px-3">
                {visible.length === 0 && <li className="py-4 text-center text-sm text-[color:var(--color-text-muted)]">No employee matches “{find.trim()}”.</li>}
                {visible.map((line) => (
                  <li key={line.code} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <Checkbox label={line.employee_name || line.employee_code || line.code} checked={chosen.has(line.code)} onChange={(on) => toggle(line.code, on)} />
                    <span className="flex items-baseline gap-3">
                      {line.case_name && !caseCode && data.cases.length > 1 && <span className="t-caption max-w-[10rem] truncate">{line.case_name}</span>}
                      <span className="tabular-nums">{money(Number(line.amount))}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-[color:var(--color-border-strong)] px-4 py-3">
              <Checkbox
                label={`I confirm that ${picked.length > 0 ? money(total) : 'this amount'} of ${monthLabel(month.month_year)} salary, for ${picked.length} ${picked.length === 1 ? 'employee' : 'employees'}, was paid on the day shown.`}
                checked={sure}
                onChange={setSure}
              />
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

/** Taking a pay run back: its lines are owed again and the money returns to the account. The run stays in the history. */
export function ReverseRunModal({ run, onClose, onDone, onConflict }: { run: PayrollRun; onClose: () => void; onDone: () => void; onConflict: (message: string) => void }) {
  const [reason, setReason] = useState('')
  const [sure, setSure] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const working = useRef(false)
  const ready = sure && reason.trim().length >= REASON_MIN

  const reverse = async () => {
    if (working.current || !ready) return
    working.current = true
    setBusy(true)
    setError('')
    try {
      await payrollApi.reverse(run.run_id, reason.trim())
      onDone()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onConflict(err.message)
        return
      }
      setError(err instanceof Error ? err.message : 'That did not work.')
      working.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`Reverse the ${monthLabel(run.month_year)} pay run`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Keep it
          </Button>
          <Button variant="danger" onClick={reverse} loading={busy} disabled={!ready}>
            Reverse pay run
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">
          {money(run.total)} paid on {day(run.paid_date)} for {run.lines} {run.lines === 1 ? 'employee' : 'employees'}
          {run.account_name ? ` from ${run.account_name}` : ''}. Reversing it makes those salary lines owed again and returns the money to the account. The run stays in the history, and the lines can be paid
          again in a new run.
        </p>
        <Field label="Why is it being reversed" required>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} placeholder="For example: paid from the wrong account" />
        </Field>
        <Checkbox label="I understand this changes the bank balance." checked={sure} onChange={setSure} />
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  )
}
