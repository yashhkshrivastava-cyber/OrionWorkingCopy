import { useRef, useState } from 'react'
import { ListChecks, ShieldCheck, Undo2 } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { money } from '../../billing/billCalc'
import type { BillStatutory, SavedBill, StatutoryPart, StatutoryPayment } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox, Field, Input, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MoneyInput } from '../ui/MoneyInput'
import { AccountPicker, rememberAccount } from './AccountPicker'
import { formatDay } from './BillDocument'

const todayIso = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

const REASON_MIN = 5
const rupees = (value: number) => `₹ ${money(value)}`
/** An amount as typed: a plain number of rupees and paise, or nothing. NaN when it is not one. */
const amountOf = (text: string): number => (text.trim() === '' ? 0 : /^\d+(\.\d{0,2})?$/.test(text.trim()) ? Number(text.trim()) : Number.NaN)
const when = (iso: string) => new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

/**
 * The EPFO and ESIC a bill charged, paid over to the authorities in parts and on different days, tracked bill by bill the way GST is (see GstPaid). What is owed is
 * what the bill charged; a payment asks for the amounts, the day, a reference and a confirmation that names the bill and the total; reversing one asks for a reason and
 * warns what it undoes. The server refuses a request that did not come from these screens (it must say it was confirmed and how much had been paid when the person
 * opened the bill), and every payment, and every reversal, is kept in the bill's history for ever. None of this changes Revenue: EPFO and ESIC stay in the bill's value.
 */
export function StatutoryPaid({ bill, canWrite, onChange }: { bill: SavedBill; canWrite: boolean; onChange: (bill: SavedBill) => void }) {
  const [recording, setRecording] = useState(false)
  const [listing, setListing] = useState(false)
  const [reversing, setReversing] = useState<StatutoryPayment | null>(null)
  const [notice, setNotice] = useState('')
  const stat = bill.statutory
  const issued = bill.status === 'Issued'

  if (!stat || stat.status === 'No EPFO or ESIC') return <span>{stat ? 'No EPFO or ESIC on this bill' : '—'}</span>

  const active = stat.payments.filter((payment) => !payment.reversed).length
  const tone = stat.status === 'Paid' ? 'text-positive' : 'text-warning'

  // Somebody else changed the payments first: show what they are now, and say so.
  const conflict = (message: string, fresh: SavedBill | null) => {
    setRecording(false)
    setReversing(null)
    setNotice(message)
    if (fresh) onChange(fresh)
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`inline-flex items-center gap-1 ${tone}`}>
          {stat.status === 'Paid' && <ShieldCheck className="h-4 w-4" aria-hidden="true" />}
          {stat.status}
        </span>
        {canWrite && issued && stat.total.remaining > 0 && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setNotice('')
              setRecording(true)
            }}
          >
            Record EPFO / ESIC payment…
          </Button>
        )}
        <button type="button" onClick={() => setListing(true)} className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
          <ListChecks className="h-3 w-3" aria-hidden="true" /> Payments{active ? ` (${active})` : ''}
        </button>
      </div>

      <dl className="mt-1 space-y-0.5 text-xs font-normal text-[color:var(--color-text-muted)]">
        <Part label="EPFO" part={stat.epfo} />
        <Part label="ESIC" part={stat.esic} />
        {stat.total.remaining > 0 && <div className="font-medium text-[color:var(--color-text)]">{rupees(stat.total.remaining)} still to pay</div>}
      </dl>

      {notice && (
        <div className="mt-2 max-w-xs">
          <Alert variant="error">{notice}</Alert>
        </div>
      )}

      {recording && (
        <RecordPayment
          bill={bill}
          stat={stat}
          onClose={() => setRecording(false)}
          onDone={(next) => {
            setRecording(false)
            onChange(next)
          }}
          onConflict={conflict}
        />
      )}
      {reversing && (
        <ReversePayment
          bill={bill}
          payment={reversing}
          onClose={() => setReversing(null)}
          onDone={(next) => {
            setReversing(null)
            onChange(next)
          }}
          onConflict={conflict}
        />
      )}
      <PaymentsList
        bill={bill}
        stat={stat}
        open={listing}
        canReverse={canWrite && issued}
        onClose={() => setListing(false)}
        onReverse={(payment) => {
          setListing(false)
          setNotice('')
          setReversing(payment)
        }}
      />
    </div>
  )
}

function Part({ label, part }: { label: string; part: StatutoryPart }) {
  if (part.status === 'None') return null
  return (
    <div className="flex gap-1.5">
      <dt className="w-9 shrink-0">{label}</dt>
      <dd className="tabular-nums">
        {part.paid > 0 ? `${rupees(part.paid)} of ${rupees(part.due)} paid` : `${rupees(part.due)} to pay`}
        {part.remaining <= 0.004 && part.due > 0 ? ' ✓' : ''}
      </dd>
    </div>
  )
}

function Summary({ bill, stat }: { bill: SavedBill; stat: BillStatutory }) {
  return (
    <dl className="mb-4 grid grid-cols-2 gap-3 rounded-xl bg-muted/70 px-4 py-3 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-xs text-[color:var(--color-text-muted)]">Bill</dt>
        <dd className="font-semibold">{bill.bill_number}</dd>
      </div>
      <div className="min-w-0">
        <dt className="text-xs text-[color:var(--color-text-muted)]">Client</dt>
        <dd className="truncate font-semibold">{bill.client_name ?? bill.party_name}</dd>
      </div>
      <div>
        <dt className="text-xs text-[color:var(--color-text-muted)]">Bill date</dt>
        <dd className="font-semibold">{formatDay(bill.bill_date)}</dd>
      </div>
      <div>
        <dt className="text-xs text-[color:var(--color-text-muted)]">EPFO and ESIC charged</dt>
        <dd className="font-semibold tabular-nums">{rupees(stat.total.due)}</dd>
      </div>
    </dl>
  )
}

function RecordPayment({
  bill,
  stat,
  onClose,
  onDone,
  onConflict,
}: {
  bill: SavedBill
  stat: BillStatutory
  onClose: () => void
  onDone: (bill: SavedBill) => void
  onConflict: (message: string, fresh: SavedBill | null) => void
}) {
  const [day, setDay] = useState(todayIso)
  const [epfo, setEpfo] = useState(stat.epfo.remaining > 0 ? stat.epfo.remaining.toFixed(2) : '')
  const [esic, setEsic] = useState(stat.esic.remaining > 0 ? stat.esic.remaining.toFixed(2) : '')
  const [reference, setReference] = useState('')
  const [accountId, setAccountId] = useState<number | undefined>(undefined)
  const [sure, setSure] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const billDay = bill.bill_date.slice(0, 10)
  const dayOk = Boolean(day) && day <= todayIso() && day >= billDay
  const e = amountOf(epfo)
  const s = amountOf(esic)
  const fits = (value: number, left: number) => !Number.isNaN(value) && value >= 0 && value <= left + 0.004
  const amountsOk = fits(e, stat.epfo.remaining) && fits(s, stat.esic.remaining) && e + s > 0
  const total = amountsOk ? e + s : 0
  const ready = sure && dayOk && amountsOk
  const left = (value: number, remaining: number) => (Number.isNaN(value) ? remaining : Math.max(remaining - value, 0))
  const after = left(e, stat.epfo.remaining) + left(s, stat.esic.remaining)

  const confirm = async () => {
    if (busyRef.current || !ready) return
    busyRef.current = true
    setBusy(true)
    setError('')
    try {
      const saved = await api.recordStatutoryPayment(bill.id, { seenPaid: stat.total.paid, epfo, esic, paidDate: day, reference: reference.trim(), accountId })
      rememberAccount(accountId)
      onDone(saved)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onConflict(err.message, await api.bill(bill.id).catch(() => null))
        return
      }
      setError((err as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`Record EPFO / ESIC payment for bill ${bill.bill_number}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={confirm} loading={busy} disabled={!ready}>
            {total > 0 ? `Record ${rupees(total)} payment` : 'Record payment'}
          </Button>
        </>
      }
    >
      <Summary bill={bill} stat={stat} />
      <p className="mb-3 text-sm text-[color:var(--color-text)]">
        Record what has been paid to the authority for what this bill charged. EPFO and ESIC can be paid in parts, on different days. The money goes out of the bank on the day
        paid, and each payment is kept in the bill&apos;s history.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={`EPFO paid (${rupees(stat.epfo.remaining)} to pay)`}>
          <MoneyInput aria-label="EPFO paid" value={epfo} disabled={stat.epfo.remaining <= 0} placeholder="0.00" onChange={setEpfo} />
        </Field>
        <Field label={`ESIC paid (${rupees(stat.esic.remaining)} to pay)`}>
          <MoneyInput aria-label="ESIC paid" value={esic} disabled={stat.esic.remaining <= 0} placeholder="0.00" onChange={setEsic} />
        </Field>
        <Field label="Day it was paid" required>
          <Input type="date" aria-label="Day it was paid" value={day} min={billDay} max={todayIso()} onChange={(event) => setDay(event.target.value)} />
        </Field>
        <Field label="Challan, TRRN or payment reference">
          <Input aria-label="Challan, TRRN or payment reference" value={reference} maxLength={60} placeholder="Optional" onChange={(event) => setReference(event.target.value)} />
        </Field>
        <AccountPicker value={accountId} onChange={setAccountId} label="Paid from" />
      </div>
      {!dayOk && day && <p className="mt-1 text-xs text-negative">The day must be between the bill date and today.</p>}
      {!amountsOk && (epfo.trim() !== '' || esic.trim() !== '') && (
        <p className="mt-1 text-xs text-negative">Each amount must be a number, no more than is still to pay on it, and one of them must be more than zero.</p>
      )}
      {amountsOk && (
        <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
          {after < 0.005
            ? 'This pays the EPFO and ESIC on the bill in full.'
            : `After this, ${rupees(after)} is still to pay${left(e, stat.epfo.remaining) > 0.004 ? `, EPFO ${rupees(left(e, stat.epfo.remaining))}` : ''}${left(s, stat.esic.remaining) > 0.004 ? `, ESIC ${rupees(left(s, stat.esic.remaining))}` : ''}.`}
        </p>
      )}

      <div className="mt-4 rounded-xl border border-[color:var(--color-border-strong)] px-4 py-3">
        <Checkbox
          label={`I confirm that ${total > 0 ? rupees(total) : 'this amount'} of EPFO / ESIC for bill ${bill.bill_number} has been paid on the day shown.`}
          checked={sure}
          onChange={setSure}
        />
      </div>
      {error && (
        <div className="mt-3">
          <Alert variant="error">{error}</Alert>
        </div>
      )}
    </Modal>
  )
}

function ReversePayment({
  bill,
  payment,
  onClose,
  onDone,
  onConflict,
}: {
  bill: SavedBill
  payment: StatutoryPayment
  onClose: () => void
  onDone: (bill: SavedBill) => void
  onConflict: (message: string, fresh: SavedBill | null) => void
}) {
  const [reason, setReason] = useState('')
  const [sure, setSure] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const ready = sure && reason.trim().length >= REASON_MIN

  const confirm = async () => {
    if (busyRef.current || !ready) return
    busyRef.current = true
    setBusy(true)
    setError('')
    try {
      onDone(await api.reverseStatutoryPayment(bill.id, payment.batch_id, reason.trim()))
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        onConflict(err.message, await api.bill(bill.id).catch(() => null))
        return
      }
      setError((err as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`Reverse an EPFO / ESIC payment on bill ${bill.bill_number}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Keep payment
          </Button>
          <Button variant="danger" onClick={confirm} loading={busy} disabled={!ready}>
            Reverse this payment
          </Button>
        </>
      }
    >
      <PaymentLine payment={payment} />
      <div className="mt-3">
        <Alert variant="error">
          <span>
            Reversing this means {rupees(payment.total)} shows as <strong>still to pay</strong> again, on this bill and on the dashboards, and the bank balance goes back up by the same
            amount. The payment stays in the history, marked reversed, with who reversed it and your reason.
          </span>
        </Alert>
      </div>
      <div className="mt-3">
        <Field label="Why is this payment being reversed?" required>
          <Textarea aria-label="Why is this payment being reversed?" rows={3} value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} />
        </Field>
        {reason.trim().length > 0 && reason.trim().length < REASON_MIN && <p className="mt-1 text-xs text-negative">Say a little more (at least {REASON_MIN} characters).</p>}
      </div>
      <div className="mt-4 rounded-xl border border-[color:var(--color-border-strong)] px-4 py-3">
        <Checkbox label={`I understand this reverses an EPFO / ESIC payment record for bill ${bill.bill_number}.`} checked={sure} onChange={setSure} />
      </div>
      {error && (
        <div className="mt-3">
          <Alert variant="error">{error}</Alert>
        </div>
      )}
    </Modal>
  )
}

function PaymentLine({ payment }: { payment: StatutoryPayment }) {
  const parts = [payment.epfo > 0 ? `EPFO ${rupees(payment.epfo)}` : '', payment.esic > 0 ? `ESIC ${rupees(payment.esic)}` : ''].filter(Boolean).join(' + ')
  return (
    <div className="text-sm">
      <p className="font-semibold text-[color:var(--color-text)]">
        <span className={payment.reversed ? 'line-through opacity-70' : ''}>
          {rupees(payment.total)} <span className="font-normal text-[color:var(--color-text-muted)]">({parts})</span>
        </span>
        {payment.paid_date ? ` · paid on ${formatDay(payment.paid_date)}` : ''}
      </p>
      {payment.reference && <p className="text-[color:var(--color-text-muted)]">Reference: {payment.reference}</p>}
      <p className="text-xs text-[color:var(--color-text-faint)]">
        Recorded by {payment.recorded_by_name ?? 'someone'} · {when(payment.recorded_timestamp)}
      </p>
      {payment.reversed && (
        <p className="mt-1 text-xs text-negative">
          Reversed by {payment.reversed_by_name ?? 'someone'}
          {payment.reversed_timestamp ? ` on ${when(payment.reversed_timestamp)}` : ''}: {payment.reversal_reason}
        </p>
      )}
    </div>
  )
}

function PaymentsList({
  bill,
  stat,
  open,
  canReverse,
  onClose,
  onReverse,
}: {
  bill: SavedBill
  stat: BillStatutory
  open: boolean
  canReverse: boolean
  onClose: () => void
  onReverse: (payment: StatutoryPayment) => void
}) {
  return (
    <Modal open={open} title={`EPFO and ESIC payments on bill ${bill.bill_number}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <dl className="mb-4 grid grid-cols-3 gap-3 rounded-xl bg-muted/70 px-4 py-3 text-sm">
        <div>
          <dt className="text-xs text-[color:var(--color-text-muted)]">Charged on the bill</dt>
          <dd className="font-semibold tabular-nums">{rupees(stat.total.due)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[color:var(--color-text-muted)]">Paid so far</dt>
          <dd className="font-semibold tabular-nums text-positive">{rupees(stat.total.paid)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[color:var(--color-text-muted)]">Still to pay</dt>
          <dd className={`font-semibold tabular-nums ${stat.total.remaining > 0 ? 'text-warning' : ''}`}>{rupees(stat.total.remaining)}</dd>
        </div>
      </dl>
      {stat.payments.length === 0 ? (
        <p className="text-sm text-[color:var(--color-text-muted)]">No EPFO or ESIC payment has been recorded on this bill.</p>
      ) : (
        <ol className="space-y-3">
          {stat.payments.map((payment) => (
            <li key={payment.batch_id} className="flex items-start justify-between gap-3 rounded-xl border border-[color:var(--color-border)] px-3.5 py-2.5">
              <PaymentLine payment={payment} />
              {canReverse && !payment.reversed && (
                <Button size="sm" variant="secondary" onClick={() => onReverse(payment)}>
                  <Undo2 className="h-3.5 w-3.5" /> Reverse…
                </Button>
              )}
            </li>
          ))}
        </ol>
      )}
    </Modal>
  )
}
