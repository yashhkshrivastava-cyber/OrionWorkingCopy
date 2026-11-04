/** Indian numbering: crores and lakhs rather than millions. */
export function inr(value: number, decimals = 1): string {
  const sign = value < 0 ? '-' : ''
  const abs = Math.abs(value)
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(decimals + 1)} Cr`
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(decimals)} L`
  if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(decimals)} K`
  return `${sign}₹${Math.round(abs).toLocaleString('en-IN')}`
}

/** Compact axis labels: no currency symbol, no decimals where avoidable. */
export function axisInr(value: number): string {
  const abs = Math.abs(value)
  if (abs >= 1e7) return `${(value / 1e7).toFixed(abs >= 1e8 ? 0 : 1)}Cr`
  if (abs >= 1e5) return `${(value / 1e5).toFixed(0)}L`
  if (abs >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return String(Math.round(value))
}

/** Exact rupees for detail tables, where a rounded "₹9.2 L" would hide the figure being checked. */
export function inrFull(value: number): string {
  const sign = value < 0 ? '-' : ''
  return `${sign}₹${Math.round(Math.abs(value)).toLocaleString('en-IN')}`
}

/** How a figure moved against the one before it: "+3.0%" for money and counts, "+0.4 pts" for a percentage. Null when flat. */
export function movement(now: number, before: number, kind: 'percent' | 'other' = 'other'): { text: string; up: boolean } | null {
  if (!Number.isFinite(now) || !Number.isFinite(before)) return null
  if (kind === 'percent') {
    const points = now - before
    if (Math.abs(points) < 0.05) return null
    return { text: `${points > 0 ? '+' : ''}${points.toFixed(1)} pts`, up: points > 0 }
  }
  if (!before) return null
  const pct = ((now - before) / Math.abs(before)) * 100
  if (Math.abs(pct) < 0.05) return null
  return { text: `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`, up: pct > 0 }
}

/** One line of text for screen readers: the largest few entries of a ranked chart. */
export function summarizeRanked(
  data: { label: string; value: number }[],
  format: (value: number) => string = inr,
  take = 3,
): string {
  if (!data.length) return 'No data in this selection.'
  const top = data
    .slice(0, take)
    .map((entry) => `${entry.label} ${format(entry.value)}`)
    .join(', ')
  return `${data.length} items. Largest: ${top}.`
}

/** One line of text for screen readers: range and extremes of a monthly series. */
export function summarizeSeries(
  data: { label: string; [key: string]: string | number }[],
  key: string,
  format: (value: number) => string = inr,
): string {
  if (!data.length) return 'No data in this selection.'
  const values = data.map((point) => Number(point[key]) || 0)
  const high = values.indexOf(Math.max(...values))
  const low = values.indexOf(Math.min(...values))
  return `${data.length} months from ${data[0].label} to ${data[data.length - 1].label}. Highest ${data[high].label} at ${format(values[high])}, lowest ${data[low].label} at ${format(values[low])}.`
}

export function count(value: number): string {
  return Math.round(value).toLocaleString('en-IN')
}

export function percent(value: number): string {
  return `${value.toFixed(1)}%`
}

/**
 * The chart palette. Mid-tones chosen to read on both the light and the dark surface.
 * The accent leads (teal in the Default theme) because it is the product colour; the rest are spaced around the wheel
 * so neighbouring slices never look alike. They are CSS variables (--orion-s-*, set by the theme engine and defaulted
 * in index.css), so a chart follows the theme's accent without being redrawn by hand.
 */
const TEAL = 'var(--orion-s-primary)'
const BLUE = 'var(--orion-s-info)'
const AMBER = 'var(--orion-s-warn)'
const ROSE = 'var(--orion-s-neg)'
const VIOLET = 'var(--orion-s-violet)'
const GREEN = 'var(--orion-s-pos)'
const SLATE = 'var(--orion-s-neutral)'
const tint = (color: string, share: number) => `color-mix(in srgb, ${color} ${share}%, var(--orion-surface))`

/** For a ranked bar chart, where every bar measures the same thing. */
export const BAR_COLOR = TEAL

/** For slices and stacks, where colour tells categories apart. */
export const CHART_COLORS = [
  TEAL,
  BLUE,
  AMBER,
  ROSE,
  VIOLET,
  GREEN,
  'var(--orion-s-sky)',
  'var(--orion-s-orange)',
  'var(--orion-s-lilac)',
  SLATE,
  'var(--orion-s-pink)',
  'var(--orion-s-lime)',
]

/** Stable colours so a measure looks the same on every dashboard. */
export const SERIES = {
  revenue: TEAL,
  expense: ROSE,
  payroll: AMBER,
  margin: BLUE,
  km: BLUE,
  committed: TEAL,
  prospective: tint(TEAL, 48),
  cancelled: tint(ROSE, 58),
  base: TEAL,
  tax: VIOLET,
  gst: AMBER,
  actual: TEAL,
  expected: SLATE,
  recurring: ROSE,
  adhoc: tint(ROSE, 38),
  unpaid: 'var(--orion-s-unpaid)',
  joiners: GREEN,
  leavers: ROSE,
  pipeline: BLUE,
  late: GREEN,
  cost: ROSE,
  trips: SLATE,
  days: VIOLET,
  rate: GREEN,
}

export const TOOLTIP_STYLE = {
  background: 'var(--orion-surface)',
  border: '1px solid var(--orion-border)',
  borderRadius: '10px',
  fontSize: '12px',
  color: 'var(--orion-text)',
  boxShadow: 'var(--orion-shadow-raised)',
  padding: '8px 12px',
}
