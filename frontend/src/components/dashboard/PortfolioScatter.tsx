import { CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { useChartMotion, useNarrow } from '../../hooks/useNarrow'
import { Empty } from './CategoryBar'
import { axisInr, inr } from './format'
import { TipCard } from './ChartTooltip'

export type PortfolioPoint = { code: string; label: string; revenue: number; margin_pct: number; margin: number; payroll?: number }

/**
 * Every case as a dot: how much it bills across, how much of that is left down. The line at zero separates the cases
 * that earn from the ones that lose. Big dots high and to the right carry the business; low dots to the left are
 * candidates for repricing or exit. Clicking a dot filters the page to that case.
 */
export function PortfolioScatter({
  data,
  selected,
  onSelect,
  height = 340,
}: {
  data: PortfolioPoint[]
  selected?: string
  onSelect?: (code: string) => void
  height?: number
}) {
  const narrow = useNarrow()
  const motion = useChartMotion()
  const points = data.filter((p) => p.revenue > 0)
  const chartHeight = narrow ? Math.min(height, 260) : height
  if (!points.length) return <Empty height={chartHeight} message="No cases with revenue in this selection." />

  return (
    <ResponsiveContainer width="100%" height={chartHeight}>
      <ScatterChart margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--orion-chart-grid)" />
        <XAxis
          type="number"
          dataKey="revenue"
          name="Revenue"
          tickFormatter={axisInr}
          tick={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }}
          axisLine={false}
          tickLine={false}
          label={{ value: 'Revenue', position: 'insideBottom', offset: -2, fontSize: 10, fill: 'var(--orion-chart-tick)' }}
        />
        <YAxis
          type="number"
          dataKey="margin_pct"
          name="Margin"
          tickFormatter={(v: number) => `${Math.round(v)}%`}
          tick={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }}
          axisLine={false}
          tickLine={false}
          width={44}
        />
        <ZAxis type="number" dataKey="payroll" range={[40, 220]} />
        <ReferenceLine y={0} stroke="var(--orion-chart-tick)" strokeDasharray="4 3" />
        <Tooltip
          cursor={{ strokeDasharray: '3 3' }}
          content={({ active, payload }) => {
            const p = payload?.[0]?.payload as PortfolioPoint | undefined
            if (!active || !p) return null
            return (
              <TipCard
                title={p.label}
                rows={[
                  { name: 'Revenue', value: inr(p.revenue) },
                  { name: 'Margin', value: inr(p.margin), muted: `${p.margin_pct.toFixed(1)}%` },
                ]}
              />
            )
          }}
        />
        <Scatter
          data={points}
          onClick={(entry: { payload?: PortfolioPoint } | PortfolioPoint) => {
            const code = (entry as { payload?: PortfolioPoint }).payload?.code ?? (entry as PortfolioPoint).code
            if (code) onSelect?.(code)
          }}
          cursor={onSelect ? 'pointer' : 'default'}
          isAnimationActive={motion.isAnimationActive}
        >
          {points.map((p) => (
            <Cell
              key={p.code}
              fill={p.margin < 0 ? 'var(--orion-s-neg)' : 'var(--orion-s-primary)'}
              fillOpacity={!selected || selected === p.code ? 0.8 : 0.15}
              stroke={selected === p.code ? 'var(--orion-text)' : 'none'}
            />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}
