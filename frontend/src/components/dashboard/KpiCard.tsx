import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight } from 'lucide-react'
import type { DashboardKpi } from '../../types'

/** The tone only tints the icon. The card itself stays neutral so the figure is what reads. */
const ICON_TONE: Record<string, string> = {
  emerald: 'bg-positive-dim text-positive',
  blue: 'bg-accent-dim text-accent',
  teal: 'bg-accent-dim text-accent',
  rose: 'bg-negative-dim text-negative',
  violet: 'bg-violet-dim text-violet',
  amber: 'bg-warning-dim text-warning',
}

const DELTA_TONE = {
  positive: 'bg-positive-dim text-positive',
  negative: 'bg-negative-dim text-negative',
  neutral: 'text-[color:var(--color-text-muted)]',
} as const

export function KpiCard({ kpi, icon }: { kpi: DashboardKpi; icon?: ReactNode }) {
  const directional = kpi.delta_type !== 'neutral'

  return (
    <div title={kpi.hint} className="panel data-hot group flex min-w-0 flex-col p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium text-[color:var(--color-text-muted)]">{kpi.label}</p>
        {icon && (
          <span className={`hidden shrink-0 rounded-lg p-1.5 sm:inline-flex ${ICON_TONE[kpi.tone] ?? ICON_TONE.blue}`}>
            {icon}
          </span>
        )}
      </div>
      <p
        key={kpi.value}
        className="font-display page-enter mt-2 text-[1.45rem] font-bold leading-none tabular-nums text-[color:var(--color-text)]"
      >
        {kpi.value}
      </p>
      {kpi.delta && (
        <p
          className={`mt-2.5 inline-flex w-fit max-w-full items-center gap-0.5 text-xs font-medium ${
            directional ? 'rounded-full px-1.5 py-0.5' : ''
          } ${DELTA_TONE[kpi.delta_type]}`}
        >
          {kpi.delta_type === 'positive' && <ArrowUpRight className="h-3 w-3 shrink-0" />}
          {kpi.delta_type === 'negative' && <ArrowDownRight className="h-3 w-3 shrink-0" />}
          <span className="truncate">{kpi.delta}</span>
        </p>
      )}
    </div>
  )
}
