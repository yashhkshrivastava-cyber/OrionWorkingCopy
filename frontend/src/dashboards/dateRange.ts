/** Calendar helpers that stay on the local calendar, not UTC. */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export type DateBounds = { min: string; max: string }

export type RangePreset = {
  id: string
  label: string
  range: (today: Date, bounds: DateBounds) => { from?: string; to?: string }
}

function iso(day: Date): string {
  const year = day.getFullYear()
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${year}-${month}-${date}`
}

function parse(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, (month || 1) - 1, day || 1)
}

export function todayIso(): string {
  return iso(new Date())
}

export function prettyDay(value: string): string {
  const day = parse(value)
  if (Number.isNaN(day.getTime())) return value
  return `${day.getDate()} ${MONTHS[day.getMonth()]} ${String(day.getFullYear()).slice(2)}`
}

function lastMonths(count: number, today: Date): { from: string; to: string } {
  const from = new Date(today.getFullYear(), today.getMonth() - (count - 1), 1)
  return { from: iso(from), to: iso(today) }
}

/** Indian financial year: 1 April to 31 March. */
function fyStartYear(day: Date): number {
  return day.getMonth() >= 3 ? day.getFullYear() : day.getFullYear() - 1
}

export const RANGE_PRESETS: RangePreset[] = [
  {
    id: 'this_month',
    label: 'This month',
    range: (today) => ({ from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today) }),
  },
  {
    id: '3m',
    label: 'Last 3 months',
    range: (today) => lastMonths(3, today),
  },
  {
    id: '6m',
    label: 'Last 6 months',
    range: (today) => lastMonths(6, today),
  },
  {
    id: '12m',
    label: 'Last 12 months',
    range: (today) => lastMonths(12, today),
  },
  {
    id: 'this_fy',
    label: 'This financial year',
    range: (today) => ({ from: iso(new Date(fyStartYear(today), 3, 1)), to: iso(today) }),
  },
  {
    id: 'last_fy',
    label: 'Last financial year',
    range: (today) => ({
      from: iso(new Date(fyStartYear(today) - 1, 3, 1)),
      to: iso(new Date(fyStartYear(today), 2, 31)),
    }),
  },
  {
    id: 'ytd',
    label: 'Calendar year to date',
    range: (today) => ({ from: iso(new Date(today.getFullYear(), 0, 1)), to: iso(today) }),
  },
  {
    id: 'all',
    label: 'All time',
    range: () => ({}),
  },
]

export function matchingPreset(
  from: string | undefined,
  to: string | undefined,
  bounds: DateBounds,
): RangePreset | undefined {
  const today = new Date()
  return RANGE_PRESETS.find((preset) => {
    const range = preset.range(today, bounds)
    return (range.from ?? '') === (from ?? '') && (range.to ?? '') === (to ?? '')
  })
}

/** The span itself in dates, whether or not it has a preset name: "1 May 26 – 10 Oct 26". With no span, what the data covers. */
export function exactLabel(from: string | undefined, to: string | undefined, bounds: DateBounds): string {
  const start = from || bounds.min
  const end = to || bounds.max
  if (start && end) return `${prettyDay(start)} – ${prettyDay(end)}`
  return rangeLabel(from, to, bounds)
}

export function rangeLabel(from: string | undefined, to: string | undefined, bounds: DateBounds): string {
  const preset = matchingPreset(from, to, bounds)
  if (preset) return preset.label
  if (from && to) return `${prettyDay(from)} – ${prettyDay(to)}`
  if (from) return `From ${prettyDay(from)}`
  if (to) return `Until ${prettyDay(to)}`
  return 'All time'
}
