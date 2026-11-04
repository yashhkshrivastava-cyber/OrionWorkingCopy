import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Download } from 'lucide-react'
import type { DashboardKpi } from '../../types'
import type { CompareMode } from '../../dashboards/compare'
import { kpiIcon } from '../../dashboards/kpiIcons'
import { Segmented } from '../ui/Segmented'
import { MetricCard } from './MetricCard'

/** The first few figures on a tab are its headlines; the rest support them. */
export function leadCount(total: number): number {
  if (total <= 3) return total
  if (total <= 5) return 2
  return 3
}

const LEAD_COLS: Record<number, string> = { 1: '', 2: 'lg:grid-cols-2', 3: 'lg:grid-cols-3' }

/** The narrowest a supporting figure can be before it is cramped. */
const STAT_MIN_PX = 232

/**
 * A panel of supporting figures that never leaves a hole. The columns that fit are worked out from the panel's width, then
 * evened out (five figures where four fit become three and two, not four and one), and the last row's figures widen to
 * fill it. The grid is sixty columns wide so any row of one to six figures divides it exactly.
 */
function StatGrid({ count, children }: { count: number; children: ReactNode[] }) {
  const root = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState(3)

  useLayoutEffect(() => {
    const node = root.current
    if (!node) return
    const measure = () => setFit(Math.max(1, Math.min(6, Math.floor(node.clientWidth / STAT_MIN_PX))))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const rows = Math.ceil(count / Math.min(fit, count))
  const columns = Math.ceil(count / rows)
  const lastRow = count - (rows - 1) * columns
  return (
    <div ref={root} className="grid -ml-px -mt-px [&>*]:border-l [&>*]:border-t [&>*]:border-[color:var(--color-border)]" style={{ gridTemplateColumns: 'repeat(60, minmax(0, 1fr))' }}>
      {children.map((child, index) => {
        const inLast = index >= count - lastRow
        return (
          <div key={index} className="flex min-w-0 [&>*]:flex-1" style={{ gridColumn: `span ${60 / (inLast ? lastRow : columns)}` }}>
            {child}
          </div>
        )
      })}
    </div>
  )
}

/**
 * A tab's figures in two weights. The headlines are cards with room for a trend; everything else sits in one panel
 * as quiet rows, so eight figures do not read as eight equal boxes. Which figures lead is the order the tab lists
 * them in, so the registry decides what matters most on each page.
 */
export function KpiBoard({
  kpis,
  caption,
  onExplore,
  onExport,
  snapshotLabel,
  snapshotNote,
  compare,
}: {
  kpis: DashboardKpi[]
  /** What the figures cover, e.g. the range and what the change is measured against. */
  caption: ReactNode
  onExplore: (kpi: DashboardKpi) => void
  onExport: () => void
  snapshotLabel?: string
  snapshotNote?: string
  /** Offered when a financial year in progress is selected: set it against the same period of the year before, or all of it. */
  compare?: { mode: CompareMode; onChange: (mode: CompareMode) => void }
}) {
  const lead = kpis.slice(0, leadCount(kpis.length))
  const stats = kpis.slice(lead.length)
  const explore = (kpi: DashboardKpi) => (kpi.explore ? () => onExplore(kpi) : undefined)

  return (
    <section aria-label="Key figures" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-[color:var(--color-text-muted)]">
          <span className="font-semibold text-[color:var(--color-text)]">Key figures</span>
          {caption}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {compare && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-[color:var(--color-text-muted)]">Compare with</span>
              <Segmented
                label="Compare with"
                value={compare.mode}
                options={[
                  { id: 'same' as CompareMode, label: 'Same period' },
                  { id: 'full' as CompareMode, label: 'Full year' },
                ]}
                onChange={compare.onChange}
              />
            </div>
          )}
          <button
            type="button"
            onClick={onExport}
            className="interactive flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Export figures
          </button>
        </div>
      </div>

      <div className={`stagger-in grid gap-3 sm:grid-cols-2 ${LEAD_COLS[lead.length] ?? 'lg:grid-cols-3'}`}>
        {lead.map((kpi) => (
          <MetricCard
            key={kpi.key}
            kpi={kpi}
            icon={kpiIcon(kpi.key)}
            onExplore={explore(kpi)}
            snapshotLabel={snapshotLabel}
            snapshotNote={snapshotNote}
          />
        ))}
      </div>

      {stats.length > 0 && (
        <div className="panel overflow-hidden">
          <StatGrid count={stats.length}>
            {stats.map((kpi) => (
              <MetricCard
                key={kpi.key}
                kpi={kpi}
                variant="stat"
                onExplore={explore(kpi)}
                snapshotLabel={snapshotLabel}
                snapshotNote={snapshotNote}
              />
            ))}
          </StatGrid>
        </div>
      )}
    </section>
  )
}
