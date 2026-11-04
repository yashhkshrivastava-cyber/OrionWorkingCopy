import { useState, type CSSProperties } from 'react'

/** Whole calendar days from today to a closing time (negative once it has closed), or null when no date is given. Counted on this computer, as the plain page does. */
export function daysLeft(iso: string | null): number | null {
  if (!iso) return null
  const end = new Date(iso)
  if (end.getTime() <= Date.now()) return -1
  const midnight = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  return Math.round((midnight(end) - midnight(new Date())) / 86400000)
}

/**
 * The thing that decides whether a tender can still be bid for, as a tile: how many days are left, hot when it is close. Closed and undated bids say so.
 * The exact closing time is written beside it on the card.
 */
export function ClosingTile({ iso }: { iso: string | null }) {
  const days = daysLeft(iso)
  const [hue, big, small] =
    days === null ? ['slate', '—', 'no date'] : days < 0 ? ['slate', 'Closed', ''] : days === 0 ? ['coral', 'Today', 'closes'] : days === 1 ? ['coral', '1', 'day left'] : [days <= 3 ? 'coral' : days <= 7 ? 'amber' : 'teal', String(days), 'days left']
  return (
    <span style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="lumen-chip inline-flex h-20 w-20 shrink-0 flex-col items-center justify-center rounded-3xl text-center leading-none" aria-hidden="true">
      <span className={`font-display font-semibold tabular-nums ${big.length > 3 ? 'text-lg' : 'text-3xl'}`}>{big}</span>
      {small && <span className="mt-1.5 text-[10px] font-bold uppercase tracking-wider">{small}</span>}
    </span>
  )
}

/** The terms of a search as chips, the first few and "+N more": a search may name a hundred cities. */
export function TermChips({ terms, limit = 8 }: { terms: string[]; limit?: number }) {
  const [all, setAll] = useState(false)
  const shown = all ? terms : terms.slice(0, limit)
  return (
    <>
      {shown.map((term) => (
        <dd key={term} className="rounded-full bg-muted px-2 py-0.5 font-medium">
          {term}
        </dd>
      ))}
      {terms.length > limit && (
        <dd>
          <button type="button" onClick={() => setAll((v) => !v)} className="interactive rounded-full px-2 py-0.5 font-semibold text-accent hover:underline">
            {all ? 'Show fewer' : `+${terms.length - limit} more`}
          </button>
        </dd>
      )}
    </>
  )
}
