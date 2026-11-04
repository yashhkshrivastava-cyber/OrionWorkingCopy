import { useId, useState } from 'react'
import { count, inr, movement } from './format'

/**
 * A trend with no axes, for scanning a KPI card. Drawn as one SVG path rather
 * than a chart, so a row of them costs almost nothing to render. Moving over it
 * reads out the month and value under the pointer, and how that month moved against the one before.
 */
export function Sparkline({
  values,
  labels = [],
  kind = 'money',
  label,
  percent = false,
  tall = false,
  className = '',
}: {
  values: number[]
  labels?: string[]
  kind?: 'money' | 'number'
  /** Accessible description of what the line is. */
  label?: string
  /** The figure is itself a percentage, so a change is in points, not a percentage of a percentage. */
  percent?: boolean
  /** A taller line, for a headline figure where the shape is worth reading. */
  tall?: boolean
  className?: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const gradient = `spark-${useId().replace(/:/g, '')}`
  if (values.length < 3) return null

  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = 100 / (values.length - 1)
  const y = (value: number) => 26 - ((value - min) / span) * 22
  const line = values
    .map((value, index) => `${index === 0 ? 'M' : 'L'}${(index * step).toFixed(2)},${y(value).toFixed(2)}`)
    .join(' ')
  const area = `${line} L100,30 L0,30 Z`
  const format = kind === 'number' ? count : inr
  const moved = hover !== null && hover > 0 ? movement(values[hover], values[hover - 1], percent ? 'percent' : 'other') : null

  const at = (event: { clientX: number; currentTarget: HTMLElement }) => {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left) / box.width
    setHover(Math.max(0, Math.min(values.length - 1, Math.round(ratio * (values.length - 1)))))
  }

  return (
    <div
      role="img"
      aria-label={label}
      className={`relative ${className}`}
      onPointerMove={at}
      onPointerLeave={() => setHover(null)}
    >
      <svg
        viewBox="0 0 100 30"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
        className={`${tall ? 'h-14' : 'h-8'} w-full overflow-visible`}
      >
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--hue, var(--orion-accent))" stopOpacity={0.34} />
            <stop offset="100%" stopColor="var(--hue, var(--orion-accent))" stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradient})`} />
        <path
          d={line}
          fill="none"
          stroke="var(--hue, var(--orion-accent))"
          strokeWidth={1.6}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {hover === null && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[color:var(--hue,var(--orion-accent))]"
          style={{ left: '100%', top: `${(y(values[values.length - 1]) / 30) * 100}%` }}
        />
      )}
      {hover !== null && (
        <>
          <span
            aria-hidden="true"
            className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-[color:var(--hue,var(--orion-accent))]"
            style={{ left: `${hover * step}%`, top: `${(y(values[hover]) / 30) * 100}%` }}
          />
          <span
            role="status"
            className="pointer-events-none absolute bottom-full z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-md border border-[color:var(--color-border)] bg-surface px-2 py-1 text-[11px] text-[color:var(--color-text)] shadow-md"
            style={{ left: `${Math.min(80, Math.max(20, hover * step))}%` }}
          >
            {labels[hover] && <span className="text-[color:var(--color-text-muted)]">{labels[hover]} · </span>}
            <span className="font-semibold tabular-nums">{format(values[hover])}</span>
            {moved && (
              <span className={`ml-1.5 tabular-nums ${moved.up ? 'text-positive' : 'text-negative'}`}>
                {moved.up ? '▲' : '▼'} {moved.text}
              </span>
            )}
          </span>
        </>
      )}
    </div>
  )
}
