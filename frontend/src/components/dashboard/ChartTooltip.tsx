import { useCallback, useState, type ReactNode } from 'react'
import { TOOLTIP_STYLE, movement } from './format'

/** One line of a chart tooltip: what it is (with its colour as a small swatch) and its value. */
export type TipRow = {
  name?: string
  value: ReactNode
  color?: string
  muted?: ReactNode
  /** A sum of the rows above it: set apart by a rule. */
  total?: boolean
  /** The figure the pointer is on: its row is lifted so it is clear which one the note below is about. */
  active?: boolean
}

/**
 * The card every chart shows when you point at it: a title, then one row per figure, then an optional note.
 *
 * The colour of a series is carried by a swatch and never by the text. Chart colours are mid-tones picked to be seen as
 * shapes on either surface, and amber, lime or sky as text on a white card is close to invisible; the words and numbers
 * here always use the theme's own text colours, which are checked against the surface in every theme.
 */
export function TipCard({ title, rows, note, tone }: { title?: ReactNode; rows: TipRow[]; note?: ReactNode; tone?: 'positive' | 'negative' }) {
  return (
    <div style={{ ...TOOLTIP_STYLE, minWidth: 150, maxWidth: 280 }} className="leading-snug">
      {title && <p className="mb-1.5 text-[13px] font-semibold text-[color:var(--orion-text)]">{title}</p>}
      <div className="space-y-1">
        {rows.map((row, index) => (
          <div
            key={index}
            className={`flex items-baseline justify-between gap-5 ${row.total ? 'mt-1.5 border-t border-[color:var(--orion-border)] pt-1.5' : ''} ${
              row.active ? '-mx-1.5 rounded-md bg-[color:var(--orion-muted)] px-1.5 py-0.5' : ''
            }`}
          >
            <span className={`flex min-w-0 items-center gap-1.5 ${row.total || row.active ? 'font-semibold text-[color:var(--orion-text)]' : 'text-[color:var(--orion-text-muted)]'}`}>
              {row.color && <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-sm" style={{ background: row.color }} />}
              {row.name && <span className="truncate">{row.name}</span>}
            </span>
            <span className="shrink-0 text-right font-semibold tabular-nums text-[color:var(--orion-text)]">
              {row.value}
              {row.muted && <span className="ml-1.5 font-normal text-[color:var(--orion-text-muted)]">{row.muted}</span>}
            </span>
          </div>
        ))}
      </div>
      {note && (
        <p
          className={`mt-1.5 border-t border-[color:var(--orion-border)] pt-1.5 text-[11px] tabular-nums ${
            tone === 'positive' ? 'text-positive' : tone === 'negative' ? 'text-negative' : 'text-[color:var(--orion-text-muted)]'
          }`}
        >
          {note}
        </p>
      )}
    </div>
  )
}

/**
 * Which series of a chart the pointer is on, so a tooltip can be about that one. A chart tooltip is shared by the whole month,
 * so the chart itself has to say which bar, area or line is under the pointer: `bind(key)` goes on that series.
 */
export function useSeriesFocus() {
  const [focus, setFocus] = useState<string | null>(null)
  const bind = useCallback(
    (key: string) => ({
      onMouseEnter: () => setFocus(key),
      onMouseLeave: () => setFocus((current) => (current === key ? null : current)),
    }),
    [],
  )
  return { focus, bind }
}

export type TipSeries = { key: string; name: string; color?: string; value: number }

/**
 * A tooltip for a chart of several series over time. It lists them all and is about the one the pointer is on: that row is
 * lifted, and the note says how that series moved against the point before it and, where the series add up to a whole, its
 * share of it. With the pointer between the series (or none to point at) it is about the first.
 */
export function SeriesTip({
  title,
  items,
  focusKey,
  previous,
  previousLabel,
  format,
  isPercent,
  totalLabel,
}: {
  title?: ReactNode
  items: TipSeries[]
  focusKey?: string | null
  /** The same series a point earlier, by key; absent for the first point. */
  previous?: Record<string, number | null | undefined>
  previousLabel?: string
  format: (key: string, value: number) => string
  isPercent?: (key: string) => boolean
  /** Adds a total row, and the share of it that the focused series makes up. */
  totalLabel?: string
}) {
  const focused = items.find((item) => item.key === focusKey) ?? items[0]
  const total = totalLabel ? items.reduce((sum, item) => sum + (Number.isFinite(item.value) ? item.value : 0), 0) : null
  const rows: TipRow[] = items.map((item) => ({
    name: item.name,
    color: item.color,
    value: format(item.key, item.value),
    active: items.length > 1 && item.key === focused?.key,
  }))
  if (total !== null && totalLabel) rows.push({ name: totalLabel, value: format(items[0]?.key ?? '', total), total: true })

  const before = focused && previous ? previous[focused.key] : undefined
  const moved = focused && before !== undefined && before !== null ? movement(focused.value, Number(before), isPercent?.(focused.key) ? 'percent' : 'other') : null
  const share = total && focused && focused.value > 0 && items.length > 1 ? `${((focused.value / total) * 100).toFixed(1)}% of ${totalLabel?.toLowerCase()}` : null
  const flat = !moved && focused && before !== undefined && before !== null && Number.isFinite(Number(before)) && Number.isFinite(focused.value)
  const parts = [
    moved && focused ? `${focused.name} ${moved.up ? '▲' : '▼'} ${moved.text}${previousLabel ? ` vs ${previousLabel}` : ''}` : null,
    flat && focused ? `${focused.name} unchanged${previousLabel ? ` vs ${previousLabel}` : ''}` : null,
    share,
  ].filter(Boolean)
  return <TipCard title={title} rows={rows} tone={moved ? (moved.up ? 'positive' : 'negative') : undefined} note={parts.length ? parts.join(' · ') : undefined} />
}
