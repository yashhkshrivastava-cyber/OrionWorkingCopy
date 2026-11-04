import { useState } from 'react'
import { CircleCheck, Undo2 } from 'lucide-react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { Alert, Badge } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox, Field, Input } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { formatDay } from './BillDocument'
import type { CreditNote, CreditNoteStatus } from '../../types'

export const STATUS_BADGE: Record<CreditNoteStatus, 'amber' | 'emerald' | 'rose' | 'default'> = {
  Pending: 'amber',
  Approved: 'emerald',
  Rejected: 'rose',
  Withdrawn: 'default',
  Reversed: 'default',
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className="min-w-0 text-right tabular-nums text-[color:var(--color-text)]">{children}</dd>
    </div>
  )
}

/**
 * One credit note, with what the person may do to it: approve (after ticking that they have checked it), refuse (with a reason), withdraw (its maker) and
 * reverse (an admin, with a reason). What each person may do is worked out by the server and arrives on the note; this only asks.
 */
export function CreditNoteDialog({ note, onClose, onChanged }: { note: CreditNote | null; onClose: () => void; onChanged: (note: CreditNote) => void }) {
  const [checked, setChecked] = useState(false)
  const [mode, setMode] = useState<'reject' | 'reverse' | null>(null)
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const close = () => {
    setChecked(false)
    setMode(null)
    setWhy('')
    setError('')
    onClose()
  }

  const run = async (action: () => Promise<CreditNote>) => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const done = await action()
      onChanged(done)
      close()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!note) return <Modal open={false} title="" onClose={close}>{null}</Modal>
  const decided = note.status !== 'Pending'
  const parts = note.status === 'Approved' || note.status === 'Reversed'

  return (
    <Modal
      open
      title={note.cn_number ? `${note.kind} ${note.cn_number}` : `${note.kind} (waiting for approval)`}
      onClose={close}
      footer={
        mode ? (
          <>
            <Button variant="secondary" onClick={() => setMode(null)}>
              Back
            </Button>
            <Button
              variant="danger"
              loading={busy}
              disabled={why.trim().length < 5}
              onClick={() => run(() => (mode === 'reject' ? api.rejectCreditNote(note.id, why.trim()) : api.reverseCreditNote(note.id, why.trim())))}
            >
              {mode === 'reject' ? 'Refuse it' : 'Reverse it'}
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" onClick={close}>
              Close
            </Button>
            {note.can_withdraw && (
              <Button variant="secondary" loading={busy} onClick={() => run(() => api.withdrawCreditNote(note.id))}>
                Withdraw
              </Button>
            )}
            {note.status === 'Pending' && (
              <Button variant="secondary" onClick={() => setMode('reject')}>
                Refuse…
              </Button>
            )}
            {note.can_reverse && (
              <Button variant="secondary" onClick={() => setMode('reverse')}>
                <Undo2 className="h-4 w-4" /> Reverse…
              </Button>
            )}
            {note.can_approve && (
              <Button loading={busy} disabled={!checked} onClick={() => run(() => api.approveCreditNote(note.id, note.total))}>
                <CircleCheck className="h-4 w-4" /> Approve
              </Button>
            )}
          </>
        )
      }
    >
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={STATUS_BADGE[note.status]}>{note.status}</Badge>
          <span className="text-[color:var(--color-text-muted)]">
            on bill {note.bill_number}
            {note.client_name ? `, ${note.client_name}` : ''}
          </span>
        </div>
        <dl className="space-y-1.5 rounded-xl bg-muted/70 px-4 py-3">
          <Line label="Amount credited">₹ {money(note.total)}</Line>
          {parts && (
            <>
              <Line label="Taxable value">₹ {money(note.taxable)}</Line>
              <Line label="CGST">₹ {money(note.cgst)}</Line>
              <Line label="SGST">₹ {money(note.sgst)}</Line>
            </>
          )}
          <Line label="Dated">{formatDay(note.note_date)}</Line>
          <Line label="Made by">{note.created_by_name ?? '—'}</Line>
          {decided && note.decided_by_name && <Line label={note.status === 'Approved' ? 'Approved by' : 'Decided by'}>{note.decided_by_name}</Line>}
        </dl>
        <p className="text-[color:var(--color-text-muted)]">
          <span className="font-medium text-[color:var(--color-text)]">Why: </span>
          {note.reason}
        </p>
        {note.decision_note && <p className="text-[color:var(--color-text-muted)]">Reason it was refused: {note.decision_note}</p>}
        {note.status === 'Reversed' && <p className="text-[color:var(--color-text-muted)]">Reversed by {note.reversed_by_name}: {note.reversal_reason}</p>}

        {note.status === 'Pending' && !mode && (
          <>
            <p className="text-xs text-[color:var(--color-text-faint)]">
              Approving takes ₹ {money(note.total)} off what the client owes on this bill, with the revenue and the GST in it, and gives the note its number. The
              bill itself does not change.
            </p>
            {note.can_approve ? (
              <Checkbox label={`I have checked this credit note for ₹ ${money(note.total)}`} checked={checked} onChange={setChecked} />
            ) : (
              note.approve_blocked && <Alert variant="info">{note.approve_blocked}</Alert>
            )}
          </>
        )}

        {mode && (
          <Field label={mode === 'reject' ? 'Why it is refused' : 'Why it is reversed'} required>
            <Input value={why} onChange={(e) => setWhy(e.target.value)} maxLength={400} aria-label="Reason" autoFocus />
          </Field>
        )}
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  )
}
