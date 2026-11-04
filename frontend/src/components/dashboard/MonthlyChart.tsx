import { useId, useState } from 'react'
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SeriesPoint } from '../../types'
import { useNarrow, useChartMotion } from '../../hooks/useNarrow'
import { axisInr, count, inr } from './format'
import { SeriesTip, useSeriesFocus } from './ChartTooltip'
import { Empty } from './CategoryBar'
import { useLumen } from '../../lumen/useLumen'

export type SeriesDef = {
  key: string
  label: string
  color: string
  /** Bars sharing a stackId stack; leave unset for side by side. */
  stackId?: string
  axis?: 'left' | 'right'
  format?: 'money' | 'number' | 'percent'
}

type ChartMoveState = { activeTooltipIndex?: number }

const FORMATTERS = {
  money: inr,
  number: count,
  percent: (value: number) => `${value.toFixed(1)}%`,
}

function formatValue(value: number, format: SeriesDef['format'] = 'money'): string {
  return FORMATTERS[format](value)
}

/**
 * Every time series on the dashboard. Bars, areas, and lines can be mixed on two
 * axes; clicking anywhere in a month column filters the page to that month while
 * the chart keeps all months so the click can be undone.
 *
 * Moving over a month lifts it. The tooltip is about the series the pointer is on (the bar, the stack, the line): that row is
 * lifted and the note says how that series moved against the month before. The legend toggles a series off and on, for
 * looking at one thing without the others.
 */
export function MonthlyChart({
  data,
  bars = [],
  areas = [],
  lines = [],
  selected,
  onSelect,
  height = 290,
  leftFormat = 'money',
  rightFormat = 'percent',
  emptyMessage = 'Nothing in this selection.',
  average,
  totalLabel,
}: {
  data: SeriesPoint[]
  bars?: SeriesDef[]
  areas?: SeriesDef[]
  lines?: SeriesDef[]
  selected?: string
  onSelect?: (code: string) => void
  height?: number
  leftFormat?: 'money' | 'number' | 'percent'
  rightFormat?: 'money' | 'number' | 'percent'
  emptyMessage?: string
  /** Draws a dashed line at the mean of this series, so a month reads as above or below usual. */
  average?: { key: string; label: string }
  /** Adds a total row to the tooltip. Meant for stacked bars, where the parts sum to a whole. */
  totalLabel?: string
}) {
  const lumen = useLumen()
  const narrow = useNarrow()
  const motion = useChartMotion()
  const uid = useId().replace(/:/g, '')
  const [hover, setHover] = useState<number | null>(null)
  const [off, setOff] = useState<Set<string>>(() => new Set())
  const { focus, bind } = useSeriesFocus()
  const chartHeight = narrow ? Math.min(height, 220) : height

  if (!data.length) return <Empty height={chartHeight} message={emptyMessage} />

  const all = [...bars, ...areas, ...lines]
  const live = (series: SeriesDef) => !off.has(series.key)
  const shownBars = bars.filter(live)
  const shownAreas = areas.filter(live)
  const shownLines = lines.filter(live)
  const shown = [...shownBars, ...shownAreas, ...shownLines]
  const hasRight = shown.some((series) => series.axis === 'right')
  // Recharts matches a series to an axis by id, and passing `undefined` counts
  // as specifying one rather than falling back to the default. Every axis and
  // every series therefore names its axis explicitly.
  const axisOf = (series: SeriesDef) => (series.axis === 'right' ? 'right' : 'left')

  const toggle = (key: string) =>
    setOff((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else if (all.length - next.size > 1) next.add(key)
      return next
    })

  const handleClick = (state: ChartMoveState) => {
    if (!onSelect) return
    const index = state?.activeTooltipIndex
    if (index === undefined || index < 0) return
    const point = data[index]
    if (point) onSelect(point.code)
  }

  const handleMove = (state: ChartMoveState) => {
    const index = state?.activeTooltipIndex
    setHover(index === undefined || index < 0 ? null : index)
  }

  const mean = average
    ? data.reduce((sum, point) => sum + (Number(point[average.key]) || 0), 0) / data.length
    : null

  const opacity = (code: string, index: number, key: string) => {
    if (selected) return selected === code ? 1 : 0.2
    if (hover === null) return 1
    // In the month under the pointer the series it is on stands out from the rest of the stack.
    if (hover === index) return focus && focus !== key ? 0.6 : 1
    return 0.55
  }
  const axisTick = { fontSize: 10, fill: 'var(--orion-chart-tick)' }

  return (
    <>
      <div className="mb-1 flex flex-wrap items-center gap-x-1 gap-y-1 px-3">
        {all.map((series) => {
          const hidden = off.has(series.key)
          return (
            <button
              key={series.key}
              type="button"
              onClick={() => toggle(series.key)}
              aria-pressed={!hidden}
              title={hidden ? `Show ${series.label}` : `Hide ${series.label}`}
              className={`interactive flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] hover:bg-muted ${
                hidden ? 'text-[color:var(--color-text-faint)] line-through' : 'text-[color:var(--color-text-muted)]'
              }`}
            >
              <span
                className={lines.includes(series) ? 'h-0.5 w-4 rounded-full' : 'h-2 w-2 rounded-sm'}
                style={{ background: series.color, opacity: hidden ? 0.35 : 1 }}
              />
              {series.label}
            </button>
          )
        })}
        {mean !== null && average && (
          <span className="flex items-center gap-1.5 px-1.5 text-[11px] text-[color:var(--color-text-muted)]">
            <span className="w-4 border-t-2 border-dashed border-[color:var(--orion-chart-tick)]" />
            {average.label} {formatValue(mean, leftFormat)}
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={chartHeight}>
        <ComposedChart
          data={data}
          margin={{ top: 12, right: hasRight ? 4 : 12, bottom: 4, left: 0 }}
          onClick={handleClick}
          onMouseMove={handleMove}
          onMouseLeave={() => setHover(null)}
          barGap={1}
          barCategoryGap="22%"
          style={{ cursor: onSelect ? 'pointer' : 'default' }}
        >
          <defs>
            {areas.map((series) => (
              <linearGradient key={series.key} id={`fill-${uid}-${series.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={series.color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={series.color} stopOpacity={0.02} />
              </linearGradient>
            ))}
            {bars.map((series) => (
              <linearGradient key={series.key} id={`bar-${uid}-${series.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={series.color} stopOpacity={1} />
                <stop offset="100%" stopColor={series.color} stopOpacity={0.72} />
              </linearGradient>
            ))}
          </defs>

          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--orion-chart-grid)" />
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }}
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="left"
            axisLine={false}
            tickLine={false}
            tick={axisTick}
            width={48}
            tickFormatter={leftFormat === 'money' ? axisInr : leftFormat === 'percent' ? (value: number) => `${Math.round(value)}%` : count}
          />
          {hasRight && (
            <YAxis
              yAxisId="right"
              orientation="right"
              axisLine={false}
              tickLine={false}
              tick={axisTick}
              width={44}
              tickFormatter={
                rightFormat === 'percent'
                  ? (value: number) => `${Math.round(value)}%`
                  : rightFormat === 'money'
                    ? axisInr
                    : count
              }
            />
          )}
          <Tooltip
            cursor={shownBars.length ? { fill: 'var(--orion-chart-cursor)', radius: 6 } : { stroke: 'var(--orion-chart-tick)', strokeDasharray: '3 3' }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const index = data.findIndex((point) => point.label === label)
              const before = index > 0 ? data[index - 1] : undefined
              const formatOf = (key: string) => all.find((candidate) => candidate.key === key)?.format ?? (leftFormat as SeriesDef['format'])
              return (
                <SeriesTip
                  title={label}
                  focusKey={focus}
                  items={payload.map((item) => ({
                    key: String(item.dataKey),
                    name: String(item.name ?? ''),
                    color: item.color ?? all.find((candidate) => candidate.key === item.dataKey)?.color,
                    value: Number(item.value),
                  }))}
                  previous={before ? Object.fromEntries(all.map((series) => [series.key, Number(before[series.key])])) : undefined}
                  previousLabel={before ? String(before.label) : undefined}
                  format={(key, value) => formatValue(value, formatOf(key))}
                  isPercent={(key) => formatOf(key) === 'percent'}
                  totalLabel={totalLabel}
                />
              )
            }}
          />
          {mean !== null && average && (
            <ReferenceLine
              yAxisId="left"
              y={mean}
              stroke="var(--orion-chart-tick)"
              strokeDasharray="4 4"
              strokeOpacity={0.8}
              ifOverflow="extendDomain"
            />
          )}

          {shownBars.map((series) => (
            <Bar
              key={series.key}
              dataKey={series.key}
              name={series.label}
              stackId={series.stackId}
              yAxisId={axisOf(series)}
              radius={series.stackId ? 0 : lumen ? [9, 9, 0, 0] : [4, 4, 0, 0]}
              isAnimationActive={motion.isAnimationActive}
              animationDuration={motion.animationDuration}
              {...bind(series.key)}
            >
              {data.map((point, index) => (
                <Cell key={point.code} fill={`url(#bar-${uid}-${series.key})`} fillOpacity={opacity(point.code, index, series.key)} />
              ))}
            </Bar>
          ))}

          {shownAreas.map((series) => (
            <Area
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              stackId={series.stackId}
              yAxisId={axisOf(series)}
              stroke={series.color}
              strokeWidth={2}
              fill={`url(#fill-${uid}-${series.key})`}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--orion-surface)' }}
              isAnimationActive={motion.isAnimationActive}
              animationDuration={motion.animationDuration}
              {...bind(series.key)}
            />
          ))}

          {shownLines.map((series) => (
            <Line
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              yAxisId={axisOf(series)}
              stroke={series.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--orion-surface)' }}
              isAnimationActive={motion.isAnimationActive}
              animationDuration={motion.animationDuration}
              {...bind(series.key)}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </>
  )
}
