import { useState } from 'react'
import { Eye, FileText } from 'lucide-react'
import { money } from '../../billing/billCalc'
import type { BillView } from '../../types'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { BillDocument } from './BillDocument'
import { PaperDesk } from './lumenBill'

/**
 * The bar that stays at the bottom of the bill form: what the bill comes to, why it cannot be saved yet if it cannot, and the two things to do next,
 * look at the bill as it will print (large, in a window, so every figure can be read) or save it. Same in both looks; the figures are the ones the server
 * will work out.
 */
export function BillBar({
  total,
  nextNumber,
  saveLabel,
  saving,
  disabled,
  blocker,
  onSave,
  bill,
  previewBeside = false,
}: {
  total: number
  nextNumber: string | null
  saveLabel: string
  saving: boolean
  disabled: boolean
  blocker: string
  onSave: () => void
  bill: BillView | null
  /** The bill is already drawn beside the form, so there is no window to open. */
  previewBeside?: boolean
}) {
  const [open, setOpen] = useState(false)
  /** On a phone the bar keeps to one row: the button says just "Save" there. */
  const saveButton = (short: boolean) => (
    <Button onClick={onSave} loading={saving} disabled={disabled}>
      <FileText className="h-4 w-4" /> {short ? <><span className="max-sm:hidden">{saveLabel}</span><span className="sm:hidden">Save</span></> : saveLabel}
    </Button>
  )

  return (
    <>
      <section aria-label="Total and save" className="sticky bottom-3 z-10 mt-4 rounded-2xl border border-[color:var(--color-border)] bg-surface/95 px-4 py-3 shadow-raised backdrop-blur max-md:bottom-24">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="t-caption text-[color:var(--color-text-muted)]">Grand total</p>
            <p className="text-xl font-semibold tabular-nums sm:text-2xl">₹ {money(total)}</p>
            {nextNumber && (
              <p className="t-caption text-[color:var(--color-text-faint)] max-sm:hidden">
                Will be numbered <span className="font-medium text-[color:var(--color-text-muted)]">{nextNumber}</span>
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {!previewBeside && (
              <Button variant="secondary" onClick={() => setOpen(true)} disabled={!bill} aria-label="Preview the bill">
                <Eye className="h-4 w-4" /> <span className="max-sm:hidden">Preview</span>
              </Button>
            )}
            {saveButton(true)}
          </div>
        </div>
        {blocker && <p className="mt-2 text-right text-xs text-[color:var(--color-text-muted)]">{blocker}</p>}
      </section>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="The bill as it will print"
        size="2xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Back to the form
            </Button>
            {saveButton(false)}
          </>
        }
      >
        {bill && <PaperDesk><BillDocument bill={bill} /></PaperDesk>}
      </Modal>
    </>
  )
}
