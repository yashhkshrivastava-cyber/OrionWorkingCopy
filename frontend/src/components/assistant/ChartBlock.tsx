import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useChartMotion } from '../../hooks/useNarrow'
import { CHART_COLORS, count, inr } from '../dashboard/format'
import { SeriesTip, useSeriesFocus } from '../dashboard/ChartTooltip'
import type { AiBlock } from '../../types'
import { Frame } from './Frame'

/*
 * A chart in an answer. It is its own file because the chart library is large: the assistant loads this only when an answer
 * actually holds a chart (see Blocks.tsx), so the library is not part of what every page of Orion downloads.
 */

type Block<K extends AiBlock['kind']> = Extract<AiBlock, { kind: K }>

// ------------------------------------------------------------------------------------------------- charts

const MONTH = /^(\d{4})-(\d{2})$/

/** "2026-09" reads better as "Sep 26" under a column. */
function monthLabel(label: string): string {
  const found = MONTH.exec(label)
  if (!found) return label
  const name = new Date(Number(found[1]), Number(found[2]) - 1, 1).toLocaleString('en-IN', { month: 'short' })
  return `${name} ${found[1].slice(2)}`
}

/** Axis numbers for money, with a decimal only where the steps are small enough to need one ("-1.5L", not "-2L" twice). */
function axisMoney(value: number): string {
  const abs = Math.abs(value)
  const trim = (n: number) => String(Math.round(n * 10) / 10)
  if (abs >= 1e7) return `${trim(value / 1e7)}Cr`
  if (abs >= 1e5) return `${trim(value / 1e5)}L`
  if (abs >= 1e3) return `${trim(value / 1e3)}K`
  return String(Math.round(value))
}

const clip = (text: string, n: number) => (text.length > n ? text.slice(0, n - 1) + '…' : text)

export function ChartBlock({ block }: { block: Block<'chart'> }) {
  const motion = useChartMotion()
  const { focus, bind } = useSeriesFocus()
  const unit = block.unit ?? 'count'
  const format = unit === 'inr' ? inr : unit === 'pct' ? (v: number) => `${v.toFixed(1)}%` : count
  const axis = unit === 'inr' ? axisMoney : unit === 'pct' ? (v: number) => `${Math.round(v)}%` : count
  const data = block.x.map((label, at) => {
    const point: Record<string, string | number | null> = { label: monthLabel(label) }
    block.series.forEach((series) => {
      point[series.name] = series.values[at] ?? null
    })
    return point
  })
  // A ranking by name (clients, cases) reads as horizontal bars; a run of months reads as columns.
  const ranked = block.type === 'bar' && block.x.length <= 12 && !block.x.every((label) => MONTH.test(label)) && block.x.some((label) => label.length > 6)
  const tick = { fontSize: 10, fill: 'var(--orion-chart-tick)' }
  const tooltip = (
    <Tooltip
      key="tip"
      cursor={{ fill: 'var(--orion-chart-cursor)' }}
      content={({ active, payload, label }) => {
        if (!active || !payload?.length) return null
        // A run of months has a point before this one to say how the series moved; a ranking by name does not.
        const index = ranked ? -1 : data.findIndex((point) => point.label === label)
        const before = index > 0 ? data[index - 1] : undefined
        return (
          <SeriesTip
            title={label}
            focusKey={focus}
            items={payload
              .filter((item) => typeof item.value === 'number')
              .map((item) => ({ key: String(item.dataKey), name: String(item.name ?? ''), color: item.color ?? item.stroke, value: item.value as number }))}
            previous={before ? Object.fromEntries(block.series.map((series) => [series.name, before[series.name] as number | null])) : undefined}
            previousLabel={before ? String(before.label) : undefined}
            format={(_key, value) => format(value)}
            isPercent={() => unit === 'pct'}
          />
        )
      }}
    />
  )
  // Arrays, not fragments: the chart library only finds axes that are direct children.
  const horizontal = [
    <CartesianGrid key="grid" strokeDasharray="3 3" horizontal={false} stroke="var(--orion-chart-grid)" />,
    <XAxis key="x" type="number" axisLine={false} tickLine={false} tick={tick} tickFormatter={axis} />,
    <YAxis key="y" type="category" dataKey="label" axisLine={false} tickLine={false} tick={tick} width={92} tickFormatter={(v: string) => clip(v, 15)} interval={0} />,
    tooltip,
  ]
  const columns = [
    <CartesianGrid key="grid" strokeDasharray="3 3" vertical={false} stroke="var(--orion-chart-grid)" />,
    <XAxis key="x" dataKey="label" axisLine={false} tickLine={false} tick={tick} interval="preserveStartEnd" minTickGap={14} />,
    <YAxis key="y" axisLine={false} tickLine={false} tick={tick} width={46} tickFormatter={axis} />,
    tooltip,
  ]
  const margin = { top: 8, right: 12, bottom: 0, left: 0 }
  const summary = `${block.title ?? 'Chart'}: ${block.series.map((s) => s.name).join(', ')} across ${block.x.length} ${ranked ? 'items' : 'points'}.`
  return (
    <Frame title={block.title} link={block.link}>
      <div role="img" aria-label={summary} className="px-1 pb-2 pt-1">
        {block.series.length > 1 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 pb-1">
            {block.series.map((series, at) => (
              <span key={series.name} className="flex items-center gap-1.5 text-[11px] text-[color:var(--color-text-muted)]">
                <span className="h-2 w-2 rounded-sm" style={{ background: CHART_COLORS[at % CHART_COLORS.length] }} />
                {series.name}
              </span>
            ))}
          </div>
        )}
        <ResponsiveContainer width="100%" height={ranked ? Math.max(150, 30 * data.length * block.series.length + 34) : 190}>
          {ranked ? (
            <BarChart data={data} layout="vertical" margin={margin} barCategoryGap="22%">
              {horizontal}
              {block.series.map((series, at) => (
                <Bar key={series.name} dataKey={series.name} fill={CHART_COLORS[at % CHART_COLORS.length]} radius={[0, 3, 3, 0]} {...bind(series.name)} {...motion} />
              ))}
            </BarChart>
          ) : block.type === 'line' ? (
            <LineChart data={data} margin={margin}>
              {columns}
              {block.series.map((series, at) => (
                <Line key={series.name} dataKey={series.name} stroke={CHART_COLORS[at % CHART_COLORS.length]} strokeWidth={2} dot={false} connectNulls {...bind(series.name)} {...motion} />
              ))}
            </LineChart>
          ) : block.type === 'area' ? (
            <AreaChart data={data} margin={margin}>
              {columns}
              {block.series.map((series, at) => (
                <Area
                  key={series.name}
                  dataKey={series.name}
                  stroke={CHART_COLORS[at % CHART_COLORS.length]}
                  fill={CHART_COLORS[at % CHART_COLORS.length]}
                  fillOpacity={0.15}
                  strokeWidth={2}
                  connectNulls
                  {...bind(series.name)}
                  {...motion}
                />
              ))}
            </AreaChart>
          ) : (
            <BarChart data={data} margin={margin} barGap={1} barCategoryGap="18%">
              {columns}
              {block.series.map((series, at) => (
                <Bar key={series.name} dataKey={series.name} fill={CHART_COLORS[at % CHART_COLORS.length]} radius={[3, 3, 0, 0]} {...bind(series.name)} {...motion} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </Frame>
  )
}
