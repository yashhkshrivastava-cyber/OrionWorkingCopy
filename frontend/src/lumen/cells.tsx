import type { ReactNode } from 'react'
import type { FilterKind } from '../tables/columnFilter'

const HUES = ['indigo', 'blue', 'cyan', 'teal', 'green', 'amber', 'orange', 'coral', 'pink', 'violet']
const GOOD = /^(active|won|closed won|paid|posted|approved|done|complete[d]?|received|settled|yes|available|current|ok|in stock|reconciled|cleared)$/i
const BAD = /^(inactive|lost|closed lost|rejected|overdue|cancel+ed|failed|declined|expired|void(ed)?|no|blocked|bounced|unpaid|disputed)$/i
const WAIT = /^(pending|draft|open|prospective|committed|submitted|in progress|on hold|partial|partially paid|review|in review|new|planned)$/i

/** A word's colour: what it means where it is a well-known status, otherwise one that stays the same for the same word everywhere. */
export function hueFor(word: string): string {
  if (GOOD.test(word)) return 'green'
  if (BAD.test(word)) return 'coral'
  if (WAIT.test(word)) return 'amber'
  let hash = 0
  for (let i = 0; i < word.length; i++) hash = (hash * 31 + word.charCodeAt(i)) >>> 0
  return HUES[hash % HUES.length]
}

const STATUSY = /(^|_)(status|stage|state|type|category|kind|priority|mode|method|frequency|gender|role|source|channel|result|outcome|tier|grade|level|active|is_[a-z_]+)$/
const CODE = /^[A-Z]{2,6}-\d{2,}$/
const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ].*)?$/
/** A figure written for reading: with commas, a rupee sign or a minus, or a dash for nothing. */
const FIGURE = /^[−-]?₹?\s?[\d,]+(\.\d+)?%?$|^[—–-]$/

/** Which columns hold a short list of words (a status, a type) that read best as coloured pills: by name, or by how few different words the rows use. */
export function pillColumns(columns: string[], rows: Record<string, unknown>[], kinds: Record<string, FilterKind>): Set<string> {
  const out = new Set<string>()
  for (const column of columns) {
    if (kinds[column] !== 'text') continue
    const values = new Set<string>()
    let long = false
    for (const row of rows.slice(0, 200)) {
      const value = row[column]
      if (value == null || value === '') continue
      const text = String(value)
      if (text.length > 24 || CODE.test(text) || ISO_DATE.test(text) || FIGURE.test(text)) {
        long = true
        break
      }
      values.add(text)
      if (values.size > 9) break
    }
    if (long || values.size === 0 || values.size > 9) continue
    if (STATUSY.test(column) || (values.size <= 6 && rows.length >= 8)) out.add(column)
  }
  return out
}

/** Columns whose values are figures written with commas and signs (the table was given text), so they line up on the right like numbers do. */
export function figureColumns(columns: string[], rows: Record<string, unknown>[]): Set<string> {
  const out = new Set<string>()
  for (const column of columns) {
    let seen = 0
    let figures = 0
    for (const row of rows.slice(0, 200)) {
      const value = row[column]
      if (value == null || value === '') continue
      seen += 1
      if (FIGURE.test(String(value).trim())) figures += 1
    }
    if (seen >= 2 && figures / seen >= 0.8) out.add(column)
  }
  return out
}

/** One cell of a table, drawn for what it holds. The text is exactly what the plain table would show. */
export function LumenCell({ value, kind, pill }: { value: unknown; kind: FilterKind; pill: boolean }): ReactNode {
  if (value == null || value === '') return <span className="text-[color:var(--color-text-faint)]">—</span>
  const text = String(value)
  if (kind === 'bool' || typeof value === 'boolean') {
    const on = value === true || /^(true|yes|1)$/i.test(text)
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${on ? 'bg-positive' : 'bg-[color:var(--color-border-strong)]'}`} aria-hidden="true" />
        {on ? 'Yes' : 'No'}
      </span>
    )
  }
  if (CODE.test(text)) {
    return <span className="inline-flex rounded-lg bg-muted px-2 py-0.5 text-xs font-semibold tracking-wide text-[color:var(--color-text-muted)] tabular-nums">{text}</span>
  }
  if (pill) {
    const hue = hueFor(text)
    return (
      <span
        style={{ '--hue': `var(--lumen-${hue})` } as React.CSSProperties}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold [background:color-mix(in_srgb,var(--hue)_14%,transparent)] [color:color-mix(in_srgb,var(--hue)_80%,var(--orion-text))]"
      >
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--hue)' }} aria-hidden="true" />
        {text}
      </span>
    )
  }
  if (kind === 'date' || ISO_DATE.test(text)) return <span className="tabular-nums text-[color:var(--color-text-muted)]">{text.slice(0, 10)}</span>
  return <>{text}</>
}
