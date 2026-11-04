import { useRef, useState } from 'react'
import { ListChecks, ShieldCheck, Undo2 } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { money } from '../../billing/billCalc'
import type { BillGst, GstPayment, SavedBill } from '../../types'
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

/**
 * The GST on a bill, paid to the government in instalments: CGST and SGST on different days, a part now and the rest later. It is a
 * statement the business relies on (what is still owed, what the dashboards list as "GST to pay"), so it is never a tick that flips on a
 * click. Recording a payment asks for the amounts, the day and a reference and a confirmation that names the bill and the total;
 * reversing one asks for a reason and warns what it undoes. The server refuses a request that did not come from these screens (it must
 * say it was confirmed and how much had been paid when the person opened the bill), and every payment, and every reversal, is kept in
 * the bill's history for ever.
 */
export function GstPaid({ bill, canWrite, onChange }: { bill: SavedBill; canWrite: boolean; onChange: (bill: SavedBill) => void }) {
  const [recording, setRecording] = useState(false)
  const [listing, setListing] = useState(false)
  const [reversing, setReversing] = useState<GstPayment | null>(null)
  const [notice, setNotice] = useState('')
  const gst = bill.gst
  const issued = bill.status === 'Issued'

  if (!gst || gst.status === 'No GST') return <span>{gst ? 'No GST on this bill' : '—'}</span>

  const active = gst.payments.filter((payment) => !payment.reversed).length
  const tone = gst.status === 'Paid' ? 'text-positive' : 'text-warning'

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
          {gst.status === 'Paid' && <ShieldCheck className="h-4 w-4" aria-hidden="true" />}
          {gst.status}
        </span>
        {canWrite && issued && gst.total.remaining > 0 && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setNotice('')
              setRecording(true)
            }}
          >
            Record GST payment…
          </Button>
        )}
        <button type="button" onClick={() => setListing(true)} className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
          <ListChecks className="h-3 w-3" aria-hidden="true" /> Payments{active ? ` (${active})` : ''}
        </button>
      </div>

      <dl className="mt-1 space-y-0.5 text-xs font-normal text-[color:var(--color-text-muted)]">
        <Part label="CGST" part={gst.cgst} />
        <Part label="SGST" part={gst.sgst} />
        {gst.total.remaining > 0 && (
          <div className="font-medium text-[color:var(--color-text)]">
            {rupees(gst.total.remaining)} still to pay
          </div>
        )}
      </dl>

      {notice && (
        <div className="mt-2 max-w-xs">
          <Alert variant="error">{notice}</Alert>
        </div>
      )}

      {recording && (
        <RecordGst
          bill={bill}
          gst={gst}
          onClose={() => setRecording(false)}
          onDone={(next) => {
            setRecording(false)
            onChange(next)
          }}
          onConflict={conflict}
        />
      )}
      {reversing && (
        <ReverseGst
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
        gst={gst}
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

function Part({ label, part }: { label: string; part: BillGst['cgst'] }) {
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

function Summary({ bill, gst }: { bill: SavedBill; gst: BillGst }) {
  return (
    <>
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
          <dt className="text-xs text-[color:var(--color-text-muted)]">GST on this bill</dt>
          <dd className="font-semibold tabular-nums">{rupees(gst.total.due)}</dd>
        </div>
      </dl>
    </>
  )
}

function RecordGst({
  bill,
  gst,
  onClose,
  onDone,
  onConflict,
}: {
  bill: SavedBill
  gst: BillGst
  onClose: () => void
  onDone: (bill: SavedBill) => void
  onConflict: (message: string, fresh: SavedBill | null) => void
}) {
  const [day, setDay] = useState(todayIso)
  const [cgst, setCgst] = useState(gst.cgst.remaining > 0 ? gst.cgst.remaining.toFixed(2) : '')
  const [sgst, setSgst] = useState(gst.sgst.remaining > 0 ? gst.sgst.remaining.toFixed(2) : '')
  const [reference, setReference] = useState('')
  const [accountId, setAccountId] = useState<number | undefined>(undefined)
  const [sure, setSure] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const billDay = bill.bill_date.slice(0, 10)
  const dayOk = Boolean(day) && day <= todayIso() && day >= billDay
  const c = amountOf(cgst)
  const s = amountOf(sgst)
  const fits = (value: number, left: number) => !Number.isNaN(value) && value >= 0 && value <= left + 0.004
  const amountsOk = fits(c, gst.cgst.remaining) && fits(s, gst.sgst.remaining) && c + s > 0
  const total = amountsOk ? c + s : 0
  const ready = sure && dayOk && amountsOk

  const confirm = async () => {
    if (busyRef.current || !ready) return
    busyRef.current = true
    setBusy(true)
    setError('')
    try {
      const saved = await api.recordGstPayment(bill.id, { seenPaid: gst.total.paid, cgst, sgst, paidDate: day, reference: reference.trim(), accountId })
      rememberAccount(accountId)
      onDone(saved)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        onConflict(e.message, await api.bill(bill.id).catch(() => null))
        return
      }
      setError((e as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const left = (value: number, remaining: number) => (Number.isNaN(value) ? remaining : Math.max(remaining - value, 0))

  return (
    <Modal
      open
      title={`Record GST payment for bill ${bill.bill_number}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={confirm} loading={busy} disabled={!ready}>
            {total > 0 ? `Record ${rupees(total)} GST payment` : 'Record GST payment'}
          </Button>
        </>
      }
    >
      <Summary bill={bill} gst={gst} />
      <p className="mb-3 text-sm text-[color:var(--color-text)]">
        Record what has been paid to the government. GST can be paid in parts: CGST and SGST on different days, or less than the full amount now. Each
        payment is kept in the bill's history.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={`CGST paid (${rupees(gst.cgst.remaining)} to pay)`}>
          <MoneyInput value={cgst} disabled={gst.cgst.remaining <= 0} placeholder="0.00" onChange={setCgst} />
        </Field>
        <Field label={`SGST paid (${rupees(gst.sgst.remaining)} to pay)`}>
          <MoneyInput value={sgst} disabled={gst.sgst.remaining <= 0} placeholder="0.00" onChange={setSgst} />
        </Field>
        <Field label="Day it was paid" required>
          <Input type="date" value={day} min={billDay} max={todayIso()} onChange={(event) => setDay(event.target.value)} />
        </Field>
        <Field label="Challan or payment reference">
          <Input value={reference} maxLength={60} placeholder="Optional" onChange={(event) => setReference(event.target.value)} />
        </Field>
        <AccountPicker value={accountId} onChange={setAccountId} label="Paid from" />
      </div>
      {!dayOk && day && <p className="mt-1 text-xs text-negative">The day must be between the bill date and today.</p>}
      {!amountsOk && (cgst.trim() !== '' || sgst.trim() !== '') && (
        <p className="mt-1 text-xs text-negative">Each amount must be a number, no more than is still to pay on it, and one of them must be more than zero.</p>
      )}
      {amountsOk && (
        <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
          {left(c, gst.cgst.remaining) + left(s, gst.sgst.remaining) < 0.005
            ? 'This pays the GST on the bill in full.'
            : `After this, ${rupees(left(c, gst.cgst.remaining) + left(s, gst.sgst.remaining))} of GST is still to pay${left(c, gst.cgst.remaining) > 0.004 ? `, CGST ${rupees(left(c, gst.cgst.remaining))}` : ''}${left(s, gst.sgst.remaining) > 0.004 ? `, SGST ${rupees(left(s, gst.sgst.remaining))}` : ''}.`}
        </p>
      )}

      <div className="mt-4 rounded-xl border border-[color:var(--color-border-strong)] px-4 py-3">
        <Checkbox
          label={`I confirm that ${total > 0 ? rupees(total) : 'this amount'} of GST for bill ${bill.bill_number} has been paid to the government on the day shown.`}
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

function ReverseGst({
  bill,
  payment,
  onClose,
  onDone,
  onConflict,
}: {
  bill: SavedBill
  payment: GstPayment
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
      onDone(await api.reverseGstPayment(bill.id, payment.batch_id, reason.trim()))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        onConflict(e.message, await api.bill(bill.id).catch(() => null))
        return
      }
      setError((e as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title={`Reverse a GST payment on bill ${bill.bill_number}`}
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
            Reversing this means {rupees(payment.total)} of GST shows as <strong>still to pay</strong> again, on this bill and on the dashboards. The
            payment stays in the history, marked reversed, with who reversed it and your reason.
          </span>
        </Alert>
      </div>
      <div className="mt-3">
        <Field label="Why is this payment being reversed?" required>
          <Textarea rows={3} value={reason} maxLength={300} onChange={(event) => setReason(event.target.value)} />
        </Field>
        {reason.trim().length > 0 && reason.trim().length < REASON_MIN && <p className="mt-1 text-xs text-negative">Say a little more (at least {REASON_MIN} characters).</p>}
      </div>
      <div className="mt-4 rounded-xl border border-[color:var(--color-border-strong)] px-4 py-3">
        <Checkbox label={`I understand this reverses a GST payment record for bill ${bill.bill_number}.`} checked={sure} onChange={setSure} />
      </div>
      {error && (
        <div className="mt-3">
          <Alert variant="error">{error}</Alert>
        </div>
      )}
    </Modal>
  )
}

function PaymentLine({ payment }: { payment: GstPayment }) {
  const parts = [payment.cgst > 0 ? `CGST ${rupees(payment.cgst)}` : '', payment.sgst > 0 ? `SGST ${rupees(payment.sgst)}` : ''].filter(Boolean).join(' + ')
  const when = (iso: string) => new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
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
        {!payment.paid_date ? ' · the day it was paid was not recorded' : ''}
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
  gst,
  open,
  canReverse,
  onClose,
  onReverse,
}: {
  bill: SavedBill
  gst: BillGst
  open: boolean
  canReverse: boolean
  onClose: () => void
  onReverse: (payment: GstPayment) => void
}) {
  return (
    <Modal open={open} title={`GST payments on bill ${bill.bill_number}`} onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <dl className="mb-4 grid grid-cols-3 gap-3 rounded-xl bg-muted/70 px-4 py-3 text-sm">
        <div>
          <dt className="text-xs text-[color:var(--color-text-muted)]">GST on the bill</dt>
          <dd className="font-semibold tabular-nums">{rupees(gst.total.due)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[color:var(--color-text-muted)]">Paid so far</dt>
          <dd className="font-semibold tabular-nums text-positive">{rupees(gst.total.paid)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[color:var(--color-text-muted)]">Still to pay</dt>
          <dd className={`font-semibold tabular-nums ${gst.total.remaining > 0 ? 'text-warning' : ''}`}>{rupees(gst.total.remaining)}</dd>
        </div>
      </dl>
      {gst.payments.length === 0 ? (
        <p className="text-sm text-[color:var(--color-text-muted)]">No GST payment has been recorded on this bill.</p>
      ) : (
        <ol className="space-y-3">
          {gst.payments.map((payment) => (
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
