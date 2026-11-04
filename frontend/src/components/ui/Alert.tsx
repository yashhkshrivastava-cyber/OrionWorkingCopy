import type { ReactNode } from 'react'
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react'

type AlertVariant = 'error' | 'success' | 'info' | 'warning'

const styles: Record<AlertVariant, string> = {
  error: 'border-negative/25 bg-negative-dim text-[color:var(--color-text)] [&>svg]:text-negative',
  success: 'border-positive/25 bg-positive-dim text-[color:var(--color-text)] [&>svg]:text-positive',
  info: 'border-accent/25 bg-accent-dim/60 text-[color:var(--color-text)] [&>svg]:text-accent',
  warning: 'border-warning/30 bg-warning-dim text-[color:var(--color-text)] [&>svg]:text-warning',
}

const icons = { error: CircleAlert, success: CircleCheck, info: Info, warning: TriangleAlert }

export function Alert({
  variant = 'info',
  children,
  onDismiss,
}: {
  variant?: AlertVariant
  children: ReactNode
  onDismiss?: () => void
}) {
  const Icon = icons[variant]
  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={`page-enter flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${styles[variant]}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">{children}</span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="-mr-1 shrink-0 rounded p-0.5 text-[color:var(--color-text-faint)] transition-colors hover:text-[color:var(--color-text)]"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}

export function Badge({
  children,
  variant = 'default',
}: {
  children: ReactNode
  variant?: 'default' | 'cyan' | 'violet' | 'amber' | 'rose' | 'emerald'
}) {
  const colors = {
    default: 'bg-muted text-[color:var(--color-text-muted)]',
    cyan: 'bg-accent-dim text-accent',
    violet: 'bg-violet-dim text-violet',
    amber: 'bg-warning-dim text-warning',
    rose: 'bg-negative-dim text-negative',
    emerald: 'bg-positive-dim text-positive',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colors[variant]}`}
    >
      {children}
    </span>
  )
}
