import type { ReactNode } from 'react'
import { Inbox, type LucideIcon } from 'lucide-react'

/**
 * What a list or page shows when there is nothing to show. It says what is missing and, where it can, what to do.
 * `compact` is for a spot inside a table or a card; the default is for a whole page.
 */
export function EmptyState({
  title,
  children,
  action,
  icon: Icon = Inbox,
  compact = false,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
  icon?: LucideIcon
  compact?: boolean
}) {
  return (
    <div className={`flex flex-col items-center text-center ${compact ? 'px-4 py-8' : 'panel border-dashed px-6 py-14'}`}>
      <span className="lumen-empty-icon mb-3 inline-flex rounded-full bg-accent-dim p-3 text-accent">
        <Icon className={compact ? 'h-5 w-5' : 'h-6 w-6'} aria-hidden="true" />
      </span>
      <h2 className="t-h3 text-[color:var(--color-text)]">{title}</h2>
      {children && <p className="t-small mt-1 max-w-md text-[color:var(--color-text-muted)]">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/** A grey block shaped like what is loading, with a soft sweep of light. Several make a believable page outline. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />
}
