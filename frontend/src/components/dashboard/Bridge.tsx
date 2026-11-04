import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useChartMotion, useNarrow } from '../../hooks/useNarrow'
import type { Category } from '../../types'
import { Empty } from './CategoryBar'
import { SERIES, axisInr, inr } from './format'
import { TipCard } from './ChartTooltip'

type Step = { label: string; base: number; value: number; total: number; tone: 'start' | 'down' | 'end' | 'loss' }

/**
 * Revenue walked down to margin: what is billed, the payroll and running costs taken out of it, and what is left.
 * Takes the three parts as categories (payroll, expenses, margin) and adds them up for the starting bar.
 */
export function Bridge({ parts, height = 280 }: { parts: Category[]; height?: number }) {
  const narrow = useNarrow()
  const motion = useChartMotion()
  const chartHeight = narrow ? Math.min(height, 240) : height
  const get = (code: string) => parts.find((p) => p.code === code)?.value ?? 0
  const payroll = get('payroll')
  const costs = get('expenses')
  const margin = get('margin')
  const revenue = payroll + costs + margin
  if (!revenue) return <Empty height={chartHeight} message="No revenue in this selection." />

  const steps: Step[] = [
    { label: 'Revenue', base: 0, value: revenue, total: revenue, tone: 'start' },
    { label: 'Payroll', base: revenue - payroll, value: payroll, total: -payroll, tone: 'down' },
    { label: 'Running costs', base: revenue - payroll - costs, value: costs, total: -costs, tone: 'down' },
    { label: 'Margin', base: 0, value: Math.max(margin, 0), total: margin, tone: margin >= 0 ? 'end' : 'loss' },
  ]
  const colour = { start: SERIES.revenue, down: SERIES.expense, end: SERIES.margin, loss: 'var(--orion-s-unpaid)' }

  return (
    <ResponsiveContainer width="100%" height={chartHeight}>
      <BarChart data={steps} margin={{ top: 22, right: 12, bottom: 4, left: 0 }}>
        <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: 'var(--orion-chart-tick)' }} />
        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }} tickFormatter={axisInr} width={48} />
        <Tooltip
          cursor={{ fill: 'var(--orion-chart-cursor)' }}
          content={({ active, payload }) => {
            const step = payload?.find((item) => item.dataKey === 'value')?.payload as Step | undefined
            if (!active || !step) return null
            const shown = step.total < 0 ? `−${inr(-step.total)}` : inr(step.total)
            return <TipCard title={step.label} rows={[{ value: shown, color: colour[step.tone] }]} />
          }}
        />
        <Bar dataKey="base" stackId="bridge" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="value" stackId="bridge" radius={[4, 4, 0, 0]} isAnimationActive={motion.isAnimationActive} animationDuration={motion.animationDuration}>
          {steps.map((s) => (
            <Cell key={s.label} fill={colour[s.tone]} />
          ))}
          <LabelList
            dataKey="total"
            position="top"
            formatter={(v: number) => (v < 0 ? `−${inr(-v)}` : inr(v))}
            style={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
