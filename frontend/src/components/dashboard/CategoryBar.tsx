import { useState, type ReactNode } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Category } from '../../types'
import { useNarrow, useChartMotion } from '../../hooks/useNarrow'
import { BAR_COLOR, axisInr } from './format'
import { TipCard } from './ChartTooltip'
import { useLumen } from '../../lumen/useLumen'

type ClickPayload = { payload?: Category }

function wrapLines(value: string, width: number): string[] {
  const text = value.trim()
  if (text.length <= width) return [text]
  const words = text.split(/\s+/)
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const next = current ? `${current} ${word}` : word
    if (next.length > width && current) {
      lines.push(current)
      current = word
      if (lines.length === 1) break
    } else {
      current = next
    }
  }
  if (current) lines.push(current)
  if (lines.length > 2) {
    const last = lines[1]
    lines[1] = last.length > width ? `${last.slice(0, width - 1)}…` : `${last}…`
    return lines.slice(0, 2)
  }
  if (lines[lines.length - 1].length > width) {
    lines[lines.length - 1] = `${lines[lines.length - 1].slice(0, width - 1)}…`
  }
  return lines
}

function AxisTick({
  x,
  y,
  payload,
  width,
}: {
  x?: number
  y?: number
  payload?: { value: string }
  width: number
}) {
  const chars = Math.max(10, Math.round(width / 7))
  const lines = wrapLines(String(payload?.value ?? ''), chars)
  return (
    <g transform={`translate(${x ?? 0},${y ?? 0})`}>
      <title>{payload?.value}</title>
      {lines.map((line, index) => (
        <text
          key={line + index}
          x={-4}
          y={index * 11 - (lines.length - 1) * 5}
          textAnchor="end"
          fontSize={10}
          fill="var(--orion-chart-tick)"
        >
          {line}
        </text>
      ))}
    </g>
  )
}

/**
 * Horizontal ranked bars, all one colour because they all measure the same thing.
 * The selected category stays fully saturated while the rest fade, which is how
 * Power BI signals a cross-filter is in effect.
 */
export function CategoryBar({
  data,
  selected,
  onSelect,
  format = axisInr,
  color,
  height = 260,
  labelWidth = 118,
  emptyMessage = 'Nothing in this selection.',
}: {
  data: Category[]
  selected?: string
  /** Omit to render a read-only chart. */
  onSelect?: (code: string) => void
  format?: (value: number) => string
  color?: string
  height?: number
  labelWidth?: number
  emptyMessage?: string
}) {
  const lumen = useLumen()
  const narrow = useNarrow()
  const motion = useChartMotion()
  const [hover, setHover] = useState<number | null>(null)
  const axisWidth = narrow ? Math.min(labelWidth, 88) : labelWidth
  const chartHeight = narrow ? Math.min(height, 240) : height

  if (!data.length) return <Empty height={chartHeight} message={emptyMessage} />

  const handleClick = (entry: ClickPayload) => {
    const code = entry?.payload?.code
    if (code) onSelect?.(code)
  }

  return (
    <Fill min={chartHeight}>
      <ResponsiveContainer width="100%" height="100%">
        {/* The room on the right is for the value at the end of the longest bar; with less it wraps ("₹1.62" over "Cr"). */}
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: narrow ? 54 : 62, bottom: 4, left: 4 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="label"
            axisLine={false}
            tickLine={false}
            width={axisWidth}
            tick={(props) => <AxisTick {...props} width={axisWidth} />}
            interval={0}
          />
          <Tooltip
            cursor={{ fill: 'var(--orion-chart-cursor)', radius: 6 }}
            content={({ active, payload }) => {
              const entry = payload?.[0]?.payload as Category | undefined
              if (!active || !entry) return null
              return <TipCard title={entry.label} rows={[{ value: format(entry.value), color: color ?? BAR_COLOR }]} />
            }}
          />
          <Bar
            dataKey="value"
            radius={lumen ? [0, 9, 9, 0] : [0, 5, 5, 0]}
            barSize={14}
            background={{ fill: 'var(--orion-muted)', radius: 5 }}
            onClick={handleClick}
            onMouseLeave={() => setHover(null)}
            cursor={onSelect ? 'pointer' : 'default'}
            isAnimationActive={motion.isAnimationActive}
            animationDuration={motion.animationDuration}
            label={(props: EndLabelProps) => <EndLabel {...props} format={format} />}
          >
            {data.map((entry, index) => (
              <Cell
                key={entry.code}
                fill={color ?? BAR_COLOR}
                fillOpacity={selected ? (selected === entry.code ? 1 : 0.22) : hover === null || hover === index ? 1 : 0.55}
                onMouseEnter={() => setHover(index)}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Fill>
  )
}

type EndLabelProps = { x?: number | string; y?: number | string; width?: number | string; height?: number | string; value?: number | string }

/**
 * The figure at the end of a bar. Drawn as one line of text: the library's own label wraps to the width of the bar, which
 * broke "₹1.62 Cr" over two lines on every bar of a narrow chart.
 */
function EndLabel({ x = 0, y = 0, width = 0, height = 0, value, format }: EndLabelProps & { format: (value: number) => string }) {
  const number = Number(value)
  if (value === undefined || !Number.isFinite(number)) return null
  return (
    <text x={Number(x) + Number(width) + 6} y={Number(y) + Number(height) / 2} dy="0.35em" fontSize={10} fill="var(--orion-chart-tick)" style={{ whiteSpace: 'pre' }}>
      {format(number)}
    </text>
  )
}

/**
 * Gives a chart the height of its card when the card is taller than the chart needs (it sits beside a taller visual and is
 * stretched to match), and never less than `min`. Without it the chart stops at its own height and leaves the rest of the
 * card empty.
 *
 * The chart is drawn in a layer taken out of the flow (`absolute inset-0`), and that is not optional. A chart that sizes
 * itself to 100% of its container is measured from the container, and if the chart is also what gives the container its
 * height (it is its content) the two chase each other: each measurement makes the container a little taller, which makes the
 * next measurement taller. On a whole-pixel screen it happens to settle; with display scaling (125%, 150%) the sizes are
 * fractional and it never does: opening a KPI's drill-down made every chart grow without end. With the chart out of the
 * flow the box's height comes only from `min` and from the card stretching it, so nothing the chart does can change it.
 *
 * `flex-1` makes it take the room left in a card that is a flex column (the drill-down's); `h-full` is for the dashboard
 * cards, whose body is the flex item. In neither case is the height ever taken from the chart.
 */
export function Fill({ min, children }: { min: number; children: ReactNode }) {
  return (
    <div className="relative h-full flex-1" style={{ minHeight: min }}>
      <div className="absolute inset-0">{children}</div>
    </div>
  )
}

/**
 * What a visual says when it has nothing to draw. It is a slim line, not a box the size of the chart it would have been, and
 * it is marked `data-empty` so the card around it can step aside (see ChartCard) rather than sit as a big empty panel.
 * `height` is the size of the chart it stands in for; it is no longer used to hold the space.
 */
export function Empty({ message }: { height?: number; message: string }) {
  return (
    <div data-empty="true" className="flex items-center px-3 py-3 text-xs text-[color:var(--color-text-faint)]">
      {message}
    </div>
  )
}
