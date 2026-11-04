/**
 * Filters on the columns of a table: a condition on one column ("amount is more than 5,000", "status is one of Won, Open") or a pick of its values.
 *
 * The same rules are written for the server in backend/app/column_filters.py (a test compares the operators): the data tables send the filters
 * to the server (`encodeFilters`, in the query), which filters the whole table; the dashboards' tables already hold their rows, so
 * `matchesFilter` applies a filter to a row in the page.
 */

export type FilterKind = 'text' | 'number' | 'date' | 'bool'

export type FilterOp =
  | 'contains'
  | 'not_contains'
  | 'equals'
  | 'not_equals'
  | 'starts'
  | 'ends'
  | 'in'
  | 'eq'
  | 'ne'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'between'
  | 'empty'
  | 'not_empty'

export interface ColumnFilter {
  column: string
  op: FilterOp
  value?: string
  value2?: string
  /** A pick (op "in"): the values ticked. */
  values?: string[]
  /** A pick that also takes the rows with nothing in the column. */
  empty?: boolean
}

/** What can be asked of a column of each kind, the first being where the menu starts. Written the same in backend/app/column_filters.py. */
export const OPS: Record<FilterKind, FilterOp[]> = {
  text: ['contains', 'not_contains', 'equals', 'not_equals', 'starts', 'ends', 'in', 'empty', 'not_empty'],
  number: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', 'in', 'empty', 'not_empty'],
  date: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between', 'empty', 'not_empty'],
  bool: ['in', 'empty', 'not_empty'],
}

export const OP_LABEL: Record<FilterKind, Partial<Record<FilterOp, string>>> = {
  text: {
    contains: 'contains',
    not_contains: 'does not contain',
    equals: 'is',
    not_equals: 'is not',
    starts: 'starts with',
    ends: 'ends with',
    in: 'is one of…',
    empty: 'is empty',
    not_empty: 'is not empty',
  },
  number: {
    eq: 'equals',
    ne: 'does not equal',
    gt: 'is more than',
    gte: 'is at least',
    lt: 'is less than',
    lte: 'is at most',
    between: 'is between',
    in: 'is one of…',
    empty: 'is empty',
    not_empty: 'is not empty',
  },
  date: {
    eq: 'is on',
    ne: 'is not on',
    gt: 'is after',
    gte: 'is on or after',
    lt: 'is before',
    lte: 'is on or before',
    between: 'is between',
    empty: 'is empty',
    not_empty: 'is not empty',
  },
  bool: { in: 'is…', empty: 'is empty', not_empty: 'is not empty' },
}

export const takesValue = (op: FilterOp): boolean => !['in', 'empty', 'not_empty'].includes(op)

export const MAX_PICK = 200

/** True when the filter says enough to be applied (a condition with its value, or a pick with something ticked). */
export function isComplete(filter: ColumnFilter): boolean {
  if (filter.op === 'empty' || filter.op === 'not_empty') return true
  if (filter.op === 'in') return Boolean(filter.values?.length) || Boolean(filter.empty)
  if (filter.op === 'between') return Boolean(filter.value?.trim()) && Boolean(filter.value2?.trim())
  return Boolean(filter.value?.trim())
}

/** What the server is sent: only the complete filters. */
export function encodeFilters(filters: ColumnFilter[]): string | undefined {
  const complete = filters.filter(isComplete)
  return complete.length ? JSON.stringify(complete) : undefined
}

export function setFilter(filters: ColumnFilter[], column: string, next: ColumnFilter | null): ColumnFilter[] {
  const rest = filters.filter((f) => f.column !== column)
  return next && isComplete(next) ? [...rest, next] : rest
}

const clip = (text: string, max = 24) => (text.length > max ? `${text.slice(0, max - 1)}…` : text)

/** The filter in words, for the chip: `Status is one of Won, Open`. */
export function describeFilter(filter: ColumnFilter, label: string, kind: FilterKind): string {
  const op = OP_LABEL[kind][filter.op] ?? filter.op
  if (filter.op === 'empty' || filter.op === 'not_empty') return `${label} ${op}`
  if (filter.op === 'in') {
    const shown = (filter.values ?? []).slice(0, 3).map((v) => clip(v))
    const more = (filter.values?.length ?? 0) - shown.length
    const parts = [...shown, ...(filter.empty ? ['(empty)'] : [])]
    return kind === 'bool' ? `${label} is ${parts.join(' or ')}` : `${label} is one of ${parts.join(', ')}${more > 0 ? ` +${more}` : ''}`
  }
  if (filter.op === 'between') return `${label} ${op} ${filter.value} and ${filter.value2}`
  return `${label} ${op} ${clip(filter.value ?? '', 30)}`
}

// --- applying a filter to a row that is already in the page ---------------------------------------------------------------

const blank = (value: unknown): boolean => value === null || value === undefined || value === ''

/**
 * Whether a row passes. `raw` is the value the column holds, `shown` the text the person sees (a formatted amount, a bill number):
 * conditions on text look at what is shown, numbers at the value.
 */
export function matchesFilter(filter: ColumnFilter, raw: unknown, shown: string, kind: FilterKind): boolean {
  const empty = blank(raw)
  switch (filter.op) {
    case 'empty':
      return empty
    case 'not_empty':
      return !empty
    case 'in': {
      if (empty) return Boolean(filter.empty)
      return (filter.values ?? []).includes(String(raw))
    }
  }
  const needle = (filter.value ?? '').trim().toLowerCase()
  if (kind === 'text' || kind === 'bool') {
    const text = (blank(shown) ? '' : shown).toLowerCase()
    switch (filter.op) {
      case 'contains':
        return text.includes(needle)
      case 'not_contains':
        return !text.includes(needle)
      case 'equals':
        return text === needle
      case 'not_equals':
        return text !== needle
      case 'starts':
        return text.startsWith(needle)
      case 'ends':
        return text.endsWith(needle)
    }
    return true
  }
  if (empty) return filter.op === 'ne'
  const number = (value: unknown) => (kind === 'date' ? String(value).slice(0, 10) : Number(String(value).replace(/,/g, '')))
  const here = number(raw)
  const low = number(filter.value ?? '')
  if (typeof here === 'number' && (Number.isNaN(here) || Number.isNaN(low as number))) return false
  switch (filter.op) {
    case 'eq':
      return here === low
    case 'ne':
      return here !== low
    case 'gt':
      return here > low
    case 'gte':
      return here >= low
    case 'lt':
      return here < low
    case 'lte':
      return here <= low
    case 'between': {
      const high = number(filter.value2 ?? '')
      const [a, b] = low <= high ? [low, high] : [high, low]
      return here >= a && here <= b
    }
  }
  return true
}

export interface PickValue {
  /** The value as text; null is "nothing in the column". */
  value: string | null
  count: number
}

export interface PickList {
  values: PickValue[]
  /** More values exist than are listed: search to find the others. */
  truncated: boolean
}

/** The values of a column that are in the page, most common first, for the pick list of a table that already holds its rows. */
export function valuesFromRows(rows: Record<string, unknown>[], key: string, contains: string, limit = 100): PickList {
  const counts = new Map<string | null, number>()
  for (const row of rows) {
    const raw = row[key]
    const value = blank(raw) ? null : String(raw)
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  const needle = contains.trim().toLowerCase()
  const all = [...counts.entries()]
    .filter(([value]) => !needle || (value ?? '').toLowerCase().includes(needle))
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || (a.value ?? '￿').localeCompare(b.value ?? '￿', undefined, { numeric: true }))
  return { values: all.slice(0, limit), truncated: all.length > limit }
}

/** The kind of a column of rows already in the page, from what it holds: numbers only is a number column. */
export function kindFromRows(rows: Record<string, unknown>[], key: string): FilterKind {
  let seen = 0
  for (const row of rows.slice(0, 300)) {
    const value = row[key]
    if (blank(value)) continue
    seen += 1
    if (typeof value === 'boolean') return 'bool'
    const numeric = typeof value === 'number' || (typeof value === 'string' && /^-?\d+(\.\d+)?$/.test(value.trim()))
    if (!numeric) return 'text'
  }
  return seen > 0 ? 'number' : 'text'
}
