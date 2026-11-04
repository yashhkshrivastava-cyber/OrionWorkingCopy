import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { Category } from '../../types'
import { useNarrow, useChartMotion } from '../../hooks/useNarrow'
import { CHART_COLORS, axisInr } from './format'
import { TipCard } from './ChartTooltip'
import { Empty } from './CategoryBar'

type ClickPayload = { payload?: Category }

/** Donut with a live total in the hole. Slices act as filter toggles. */
export function CategoryDonut({
  data,
  selected,
  onSelect,
  format = axisInr,
  centerLabel,
  height = 264,
  colors = CHART_COLORS,
}: {
  data: Category[]
  selected?: string
  /** Omit to render a read-only chart. */
  onSelect?: (code: string) => void
  format?: (value: number) => string
  centerLabel?: string
  height?: number
  colors?: string[]
}) {
  const narrow = useNarrow()
  const motion = useChartMotion()
  const chartHeight = narrow ? Math.min(height, 220) : height

  if (!data.length) return <Empty height={chartHeight} message="Nothing in this selection." />

  const total = data.reduce((sum, entry) => sum + entry.value, 0)
  const active = data.find((entry) => entry.code === selected)

  const handleClick = (entry: ClickPayload) => {
    const code = entry?.payload?.code
    if (code) onSelect?.(code)
  }

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={chartHeight}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius="58%"
            outerRadius="82%"
            paddingAngle={2}
            onClick={handleClick}
            cursor={onSelect ? 'pointer' : 'default'}
            isAnimationActive={motion.isAnimationActive}
            animationDuration={motion.animationDuration}
            stroke="var(--orion-surface)"
            strokeWidth={2}
          >
            {data.map((entry, index) => (
              <Cell
                key={entry.code}
                fill={colors[index % colors.length]}
                fillOpacity={!selected || selected === entry.code ? 1 : 0.22}
              />
            ))}
          </Pie>
          {/* Above the total in the hole, which is a later sibling and would otherwise be drawn across the tooltip. */}
          <Tooltip
            wrapperStyle={{ zIndex: 30 }}
            content={({ active, payload }) => {
              const entry = payload?.[0]?.payload as Category | undefined
              if (!active || !entry) return null
              const index = data.findIndex((slice) => slice.code === entry.code)
              const share = total > 0 ? `${((entry.value / total) * 100).toFixed(1)}%` : undefined
              return <TipCard title={entry.label} rows={[{ value: format(entry.value), muted: share, color: colors[index % colors.length] }]} />
            }}
          />
        </PieChart>
      </ResponsiveContainer>

      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <p className="font-display text-xl font-bold tabular-nums text-[color:var(--color-text)]">
          {format(active ? active.value : total)}
        </p>
        <p className="text-[11px] text-[color:var(--color-text-muted)]">{active ? active.label : centerLabel ?? 'Total'}</p>
      </div>

      <ul className="mt-1 flex flex-wrap justify-center gap-x-3 gap-y-1 px-3 pb-1">
        {data.map((entry, index) => {
          const isDim = selected && selected !== entry.code
          return (
            <li key={entry.code}>
              <button
                type="button"
                onClick={() => onSelect?.(entry.code)}
                disabled={!onSelect}
                className={`flex items-center gap-1.5 text-[11px] transition-opacity ${isDim ? 'opacity-40' : 'opacity-100'} ${onSelect ? 'hover:opacity-100' : 'cursor-default'}`}
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: colors[index % colors.length] }}
                />
                <span className="text-[color:var(--color-text-muted)]">{entry.label}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
