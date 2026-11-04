import type { ReactNode } from 'react'
import { AlertTriangle, SearchX } from 'lucide-react'
import { EmptyState as SharedEmptyState } from '../ui/EmptyState'
import { leadCount } from './KpiBoard'

/** The dashboards' "nothing here": the shared empty state with the search icon. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <SharedEmptyState title={title} action={action} icon={SearchX}>
      {children}
    </SharedEmptyState>
  )
}

/**
 * Filters that match nothing. It says what the data does cover and offers the two ways out people take: widen the
 * period to everything, or drop every filter.
 */
export function NoMatch({
  title,
  covers,
  onWiden,
  onReset,
  children,
}: {
  title: string
  /** What the data does cover, e.g. "Billed data runs from 1 Apr 23 to 30 Sep 26." */
  covers?: string
  /** Offered when a period or year is what is excluding everything. */
  onWiden?: () => void
  onReset: () => void
  children?: ReactNode
}) {
  return (
    <EmptyState
      title={title}
      action={
        <div className="flex flex-wrap items-center justify-center gap-2">
          {onWiden && (
            <button
              type="button"
              onClick={onWiden}
              className="interactive rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-on-primary hover:opacity-90"
            >
              Show all time
            </button>
          )}
          <button
            type="button"
            onClick={onReset}
            className={`interactive rounded-lg px-3 py-1.5 text-sm font-semibold ${
              onWiden
                ? 'border border-[color:var(--color-border-strong)] text-[color:var(--color-text)] hover:bg-muted'
                : 'bg-primary text-on-primary hover:opacity-90'
            }`}
          >
            Clear every filter
          </button>
        </div>
      }
    >
      {children} {covers}
    </EmptyState>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-negative/30 bg-negative-dim px-4 py-3 text-sm text-negative"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">The dashboard could not be loaded</p>
        <p className="mt-0.5 break-words text-xs opacity-90">{message}</p>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="interactive shrink-0 rounded-lg border border-current px-2.5 py-1 text-xs font-medium hover:bg-surface/50"
        >
          Try again
        </button>
      )}
    </div>
  )
}

/** Same footprint as the loaded page (brief, headline cards, supporting figures, two charts), so nothing jumps when the data arrives. */
export function DashboardSkeleton({ kpis = 6 }: { kpis?: number }) {
  const block = 'skeleton rounded-xl border border-[color:var(--color-border)]'
  const lead = leadCount(kpis)
  const stats = Math.max(0, kpis - lead)
  return (
    <div aria-busy="true" aria-label="Loading dashboard" className="space-y-4">
      <div className={`${block} h-44`} />
      <div className={`grid gap-3 sm:grid-cols-2 ${lead === 3 ? 'lg:grid-cols-3' : lead === 2 ? 'lg:grid-cols-2' : ''}`}>
        {Array.from({ length: lead }).map((_, index) => (
          <div key={index} className={`${block} h-[11.5rem]`} />
        ))}
      </div>
      {stats > 0 && <div className={`${block} h-24`} />}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className={`${block} h-80 lg:col-span-2`} />
        <div className={`${block} h-80`} />
      </div>
    </div>
  )
}
