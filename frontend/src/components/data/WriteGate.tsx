import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { useLumen } from '../../lumen/useLumen'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Checkbox } from '../ui/Field'

export function WriteGate({
  open,
  title,
  body,
  confirmLabel = 'I understand this will write data',
  continueLabel = 'Continue',
  onCancel,
  onContinue,
}: {
  open: boolean
  title: string
  body: string
  confirmLabel?: string
  continueLabel?: string
  onCancel: () => void
  onContinue: () => void
}) {
  const [accepted, setAccepted] = useState(false)
  const lumen = useLumen()

  useEffect(() => {
    if (open) setAccepted(false)
  }, [open])

  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="strong" disabled={!accepted} onClick={onContinue}>
            {continueLabel}
          </Button>
        </>
      }
    >
      {lumen && (
        <div className="mb-4 flex items-center gap-4 rounded-3xl p-4 [background:linear-gradient(135deg,color-mix(in_srgb,var(--lumen-amber)_22%,transparent),color-mix(in_srgb,var(--lumen-coral)_16%,transparent))]">
          <span className="lumen-pulse grid h-14 w-14 shrink-0 place-items-center rounded-2xl text-white shadow-lg [background:linear-gradient(135deg,var(--lumen-amber),var(--lumen-coral))]">
            <ShieldAlert className="h-7 w-7" />
          </span>
          <p className="font-display text-lg font-semibold leading-snug">These are live records. Take a moment before you change them.</p>
        </div>
      )}
      <p className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">{body}</p>
      <div className="mt-5 rounded-2xl border border-warning/30 bg-warning-dim px-4 py-3">
        <Checkbox label={confirmLabel} checked={accepted} onChange={setAccepted} />
      </div>
    </Modal>
  )
}
