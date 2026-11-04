import { CircleAlert, CircleCheck, Clock, ShieldAlert, Trash2, TriangleAlert } from 'lucide-react'
import { Button } from '../ui/Button'
import type { AiPendingAction } from '../../types'

/**
 * Something the Copilot has prepared but not done. Nothing happens until the person presses the button here; the
 * wording of the card is built by the server from the checked request, not by the model.
 */
export function ConfirmCard({
  action,
  onConfirm,
  onCancel,
}: {
  action: AiPendingAction
  onConfirm: (id: string) => void
  onCancel: (id: string) => void
}) {
  const { preview, status } = action
  const danger = Boolean(preview.danger) || action.risk === 'high'
  const waiting = status === 'pending' || status === 'confirming'

  if (!waiting) {
    const done = status === 'done'
    const Icon = done ? CircleCheck : status === 'cancelled' ? CircleAlert : status === 'expired' ? Clock : TriangleAlert
    const tone = done ? 'text-positive' : status === 'failed' ? 'text-negative' : 'text-[color:var(--color-text-muted)]'
    const label = done ? 'Done' : status === 'cancelled' ? 'Cancelled' : status === 'expired' ? 'Expired' : 'Not done'
    return (
      <div className="panel flex items-start gap-3 px-3.5 py-3">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="flex items-baseline justify-between gap-3 text-sm font-semibold">
            <span className="min-w-0">{preview.title}</span>
            <span className={`shrink-0 text-xs font-semibold ${tone}`}>{label}</span>
          </p>
          {action.result && <p className="t-caption mt-0.5">{action.result}</p>}
          {status === 'expired' && !action.result && <p className="t-caption mt-0.5">This was not confirmed in time. Ask again if you still want it.</p>}
        </div>
      </div>
    )
  }

  return (
    <div
      role="group"
      aria-label={`Confirm: ${preview.title}`}
      className={`panel overflow-hidden border-2 ${danger ? 'border-[color:var(--color-negative)]' : 'border-[color:var(--color-border-strong)]'}`}
    >
      <div className="flex items-start gap-3 px-3.5 pt-3.5">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${danger ? 'bg-negative-dim text-negative' : 'bg-accent-dim text-accent'}`}>
          {danger ? <Trash2 className="h-[18px] w-[18px]" aria-hidden="true" /> : <ShieldAlert className="h-[18px] w-[18px]" aria-hidden="true" />}
        </span>
        <div className="min-w-0">
          <p className="eyebrow">Needs your confirmation</p>
          <p className="mt-0.5 text-sm font-semibold leading-snug">{preview.title}</p>
        </div>
      </div>
      {preview.rows && preview.rows.length > 0 && (
        <dl className="mx-3.5 mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg bg-muted/60 px-3 py-2 text-[13px]">
          {preview.rows.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-[color:var(--color-text-muted)]">{row.label}</dt>
              <dd className="min-w-0 break-words font-medium">{row.value || '–'}</dd>
            </div>
          ))}
        </dl>
      )}
      {preview.warning && (
        <p className={`mx-3.5 mt-2.5 flex items-center gap-1.5 text-xs font-semibold ${danger ? 'text-negative' : 'text-[color:var(--color-text-muted)]'}`}>
          <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {preview.warning}
        </p>
      )}
      <div className="flex justify-end gap-2 px-3.5 pb-3.5 pt-3">
        <Button variant="secondary" size="sm" disabled={status === 'confirming'} onClick={() => onCancel(action.id)}>
          Cancel
        </Button>
        <Button variant={danger ? 'danger' : 'primary'} size="sm" loading={status === 'confirming'} onClick={() => onConfirm(action.id)}>
          {preview.confirm_label || 'Confirm'}
        </Button>
      </div>
    </div>
  )
}
