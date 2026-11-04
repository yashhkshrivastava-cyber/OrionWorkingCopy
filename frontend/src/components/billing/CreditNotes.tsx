import { useCallback, useEffect, useRef, useState } from 'react'
import { FilePlus2 } from 'lucide-react'
import { api } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { money } from '../../billing/billCalc'
import { Alert, Badge } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MoneyInput } from '../ui/MoneyInput'
import { formatDay } from './BillDocument'
import { CreditNoteDialog, STATUS_BADGE } from './CreditNoteDialog'
import type { CreditNote, CreditNoteKind, CreditNotePreview, SavedBill } from '../../types'

const todayIso = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

/**
 * The credit notes against a bill. A credit note takes money off what the client still owes (and the revenue and GST in it) without changing the bill;
 * it is made here and takes effect only when someone else (or an admin) approves it.
 */
export function CreditNotes({ bill, canWrite, isAdmin, onChange }: { bill: SavedBill; canWrite: boolean; isAdmin: boolean; onChange: (bill: SavedBill) => void }) {
  const [notes, setNotes] = useState<CreditNote[]>([])
  const [open, setOpen] = useState<CreditNote | null>(null)
  const [making, setMaking] = useState(false)
  const [kind, setKind] = useState<CreditNoteKind>('Credit note')
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState(todayIso)
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState<CreditNotePreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const idemKey = useRef(newIdempotencyKey())

  const load = useCallback(() => {
    api
      .billCreditNotes(bill.id)
      .then((r) => setNotes(r.credit_notes))
      .catch(() => setNotes([]))
  }, [bill.id])

  useEffect(load, [load, bill.version_no, bill.revenue?.credited])

  // What the credit would be made of, shown while it is typed. It is only a preview: the figures are worked out again when the note is approved.
  useEffect(() => {
    if (!making || !(Number(amount) > 0)) {
      setPreview(null)
      return
    }
    let stale = false
    const timer = window.setTimeout(() => {
      api
        .creditNotePreview(bill.id, amount)
        .then((p) => !stale && setPreview(p))
        .catch(() => !stale && setPreview(null))
    }, 250)
    return () => {
      stale = true
      window.clearTimeout(timer)
    }
  }, [making, amount, bill.id])

  const remaining = bill.revenue?.remaining ?? 0
  const issued = bill.status === 'Issued'
  if (!bill.revenue || (!notes.length && !(canWrite && issued && remaining > 0))) return null

  const begin = () => {
    setKind('Credit note')
    setAmount('')
    setDay(todayIso())
    setReason('')
    setPreview(null)
    setError('')
    idemKey.current = newIdempotencyKey()
    setMaking(true)
  }

  const make = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError('')
    try {
      await api.makeCreditNote({ bill_code: bill.id, kind, total: amount.trim(), note_date: day, reason: reason.trim() }, idemKey.current)
      setMaking(false)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const changed = async (note: CreditNote) => {
    setNotes((now) => now.map((n) => (n.id === note.id ? note : n)))
    // an approval or a reversal changes what is owed on the bill: read it again
    const fresh = await api.bill(bill.id).catch(() => null)
    if (fresh) onChange(fresh)
    load()
  }

  const valid = Number(amount) > 0 && Number(amount) <= remaining + 0.004 && reason.trim().length >= 5 && Boolean(day)

  return (
    <section aria-label="Credit notes" className="panel">
      <header className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4 sm:px-5">
        <div>
          <h3 className="t-h3 text-[color:var(--color-text)]">Credit notes</h3>
          <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
            Take money off what the client owes (a rate dispute, a short service, a bad debt) without changing the bill. A note takes effect when someone
            else approves it{isAdmin ? ', or you, as an admin' : ''}.
          </p>
        </div>
        {canWrite && issued && remaining > 0 && (
          <Button size="sm" variant="secondary" onClick={begin}>
            <FilePlus2 className="h-4 w-4" /> Issue credit note
          </Button>
        )}
      </header>

      {notes.length > 0 && (
        <div className="mt-3 overflow-x-auto border-t border-[color:var(--color-border)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-faint)]">
                <th className="px-4 py-2 sm:px-5">Note</th>
                <th className="px-4 py-2">Kind</th>
                <th className="px-4 py-2">Dated</th>
                <th className="px-4 py-2 text-right">Amount</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 sm:px-5" />
              </tr>
            </thead>
            <tbody>
              {notes.map((n) => (
                <tr key={n.id} className="border-t border-[color:var(--color-border)]">
                  <td className="px-4 py-2 font-medium tabular-nums text-[color:var(--color-text)] sm:px-5">{n.cn_number ?? 'Not numbered yet'}</td>
                  <td className="px-4 py-2 text-[color:var(--color-text-muted)]">{n.kind}</td>
                  <td className="px-4 py-2 text-[color:var(--color-text-muted)]">{formatDay(n.note_date)}</td>
                  <td className="px-4 py-2 text-right tabular-nums text-[color:var(--color-text)]">₹ {money(n.total)}</td>
                  <td className="px-4 py-2">
                    <Badge variant={STATUS_BADGE[n.status]}>{n.status}</Badge>
                  </td>
                  <td className="px-4 py-2 text-right sm:px-5">
                    <Button variant="ghost" size="sm" onClick={() => setOpen(n)}>
                      {n.can_approve ? 'Review' : 'Open'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreditNoteDialog note={open} onClose={() => setOpen(null)} onChanged={changed} />

      <Modal
        open={making}
        title={`Credit note on bill ${bill.bill_number}`}
        onClose={() => setMaking(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setMaking(false)}>
              Cancel
            </Button>
            <Button onClick={make} loading={busy} disabled={!valid}>
              Make the credit note
            </Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="What is it" required>
            <Select value={kind} onChange={(e) => setKind(e.target.value as CreditNoteKind)} aria-label="Kind of credit note">
              <option value="Credit note">Credit note</option>
              <option value="Bad debt write-off">Bad debt write-off (an admin approves)</option>
            </Select>
          </Field>
          <Field label="Date of the note" required>
            <Input type="date" value={day} max={todayIso()} onChange={(e) => setDay(e.target.value)} />
          </Field>
        </div>
        <div className="mt-3">
          <Field label="Amount credited, GST included" required hint={`Up to ₹ ${money(remaining)}, what is still to be received on this bill.`}>
            <MoneyInput value={amount} onChange={setAmount} />
          </Field>
        </div>
        <div className="mt-3">
          <Field label="Why" required>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={400} aria-label="Why the credit note is made" />
          </Field>
        </div>
        {preview && (
          <p className="mt-3 text-sm tabular-nums text-[color:var(--color-text-muted)]">
            Taxable ₹ {money(preview.taxable)} + CGST ₹ {money(preview.cgst)} + SGST ₹ {money(preview.sgst)} = ₹ {money(preview.total)}. ₹ {money(preview.still_owed)} would
            still be owed.
          </p>
        )}
        <p className="mt-2 text-xs text-[color:var(--color-text-faint)]">
          Nothing changes until it is approved. The GST comes off in the month of the date above. Once approved it can be reversed only by an admin.
        </p>
        {error && (
          <div className="mt-3">
            <Alert variant="error">{error}</Alert>
          </div>
        )}
      </Modal>
    </section>
  )
}
