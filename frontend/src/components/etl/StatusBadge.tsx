import { CircleAlert, CircleCheck, CircleDashed, CircleSlash, LoaderCircle } from 'lucide-react'
import { STATUS_LABEL } from '../../etl/format'
import type { EtlRunStatus, EtlStepStatus } from '../../types'

const STYLE: Record<EtlRunStatus | EtlStepStatus, string> = {
  succeeded: 'bg-positive-dim text-positive',
  failed: 'bg-negative-dim text-negative',
  running: 'bg-warning-dim text-warning',
  pending: 'bg-muted text-[color:var(--color-text-muted)]',
  skipped: 'bg-muted text-[color:var(--color-text-faint)]',
}

const ICON = {
  succeeded: CircleCheck,
  failed: CircleAlert,
  running: LoaderCircle,
  pending: CircleDashed,
  skipped: CircleSlash,
}

/** A run's or a table's state, always an icon and a word, never colour alone. `null` is a pipeline that has never run. */
export function StatusBadge({ status, size = 'md' }: { status: EtlRunStatus | EtlStepStatus | null; size?: 'sm' | 'md' }) {
  const box = size === 'sm' ? 'gap-1 px-1.5 py-0.5 text-[10.5px]' : 'gap-1.5 px-2.5 py-1 text-xs'
  const icon = size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5'
  if (status === null) {
    return (
      <span className={`inline-flex items-center rounded-full bg-muted font-semibold text-[color:var(--color-text-muted)] ${box}`}>
        <CircleDashed className={icon} aria-hidden="true" /> Never run
      </span>
    )
  }
  const Icon = ICON[status]
  return (
    <span className={`inline-flex items-center rounded-full font-semibold ${box} ${STYLE[status]}`}>
      <Icon className={`${icon} ${status === 'running' ? 'animate-spin' : ''}`} aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  )
}
