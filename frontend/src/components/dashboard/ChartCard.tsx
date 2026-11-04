import type { ReactNode } from 'react'
import { Info, MousePointerClick, Table2, X } from 'lucide-react'
import { HoverCard } from './HoverCard'

/**
 * Frame for every dashboard visual. The title says what it is, the line under it says what it shows (the range, the
 * high and low, the biggest items: the same sentence a screen reader gets), and the longer explanation waits behind
 * the (i). Top right: the way into the rows behind it, and, once a bar or slice is selected, a one-click release.
 *
 * `quiet` drops the hover lift (a chart you are reading should not move).
 */
export function ChartCard({
  title,
  subtitle,
  drill,
  selection,
  onClear,
  actions,
  summary,
  records,
  quiet = false,
  children,
  className = '',
}: {
  title: string
  /** The longer explanation and how to click through, shown in the (i). */
  subtitle?: string
  drill?: string
  selection?: string
  onClear?: () => void
  actions?: ReactNode
  /** One line of what the chart shows. Shown under the title and read out by screen readers. */
  summary?: string
  /** Opens the rows behind this chart. Pass the record set and what to call it. */
  records?: { dataset: string; label: string; open: (dataset: string, label?: string) => void }
  quiet?: boolean
  children: ReactNode
  className?: string
}) {
  const motion = quiet ? '' : 'transition-shadow duration-300 hover:shadow-raised'
  // A visual with nothing to show does not hold a place in the grid, and leave a big empty panel beside a full one: it
  // becomes a slim line across the whole width, after the visuals that have something to say.
  const empty = 'has-[[data-empty=true]]:order-last has-[[data-empty=true]]:col-span-full!'

  return (
    <section aria-label={title} className={`panel group/chart lumen-chart flex min-w-0 flex-col ${motion} ${empty} ${className}`}>
      <header className="flex flex-wrap items-start justify-between gap-2 px-4 pt-4 sm:gap-3 sm:px-5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <h3 className="t-h3 text-[color:var(--color-text)]">{title}</h3>
            {(subtitle || drill) && (
              <HoverCard
                label={`About ${title}`}
                trigger={<Info className="h-3.5 w-3.5" aria-hidden="true" />}
                className="p-0.5 text-[color:var(--color-text-faint)] opacity-60 hover:text-accent group-hover/chart:opacity-100 focus-visible:opacity-100"
                width={300}
              >
                <div className="space-y-1.5">
                  <p className="text-sm font-semibold text-[color:var(--color-text)]">{title}</p>
                  {subtitle && <p>{subtitle}</p>}
                  {drill && (
                    <p className="flex items-center gap-1.5 text-[11px] text-[color:var(--color-text-faint)]">
                      <MousePointerClick className="h-3 w-3" aria-hidden="true" />
                      {drill} to focus the whole page on it.
                    </p>
                  )}
                </div>
              </HoverCard>
            )}
          </div>
          {summary && <p className="mt-0.5 text-xs leading-snug text-[color:var(--color-text-muted)]">{summary}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {actions}
          {records && (
            <button
              type="button"
              onClick={() => records.open(records.dataset, records.label)}
              title={`See the ${records.label.toLowerCase()} behind this chart`}
              className="interactive flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
            >
              <Table2 className="h-3.5 w-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">{records.label}</span>
            </button>
          )}
          {selection && (
            <button
              type="button"
              onClick={onClear}
              aria-label={`Clear filter: ${selection}`}
              className="interactive flex shrink-0 items-center gap-1 rounded-full bg-primary px-2.5 py-1 text-[11px] font-semibold text-on-primary hover:opacity-85"
            >
              <span className="max-w-[140px] truncate">{selection}</span>
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </header>
      <div className="flex-1 px-2 pb-3 pt-2">{children}</div>
    </section>
  )
}
