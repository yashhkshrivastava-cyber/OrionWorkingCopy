import type { CSSProperties } from 'react'
import { useLumen } from '../../lumen/useLumen'

/** What the tone words the money pages already use mean in colour. */
function hueOf(tone: string): string {
  if (tone.includes('positive')) return 'green'
  if (tone.includes('warning')) return 'amber'
  if (tone.includes('negative')) return 'coral'
  return 'indigo'
}

/**
 * One figure with its caption and a line under it, the tile the billing pages (Outstanding, TDS, GST, Credit notes) open with. The text arrives already
 * formatted. In Lumen it sits on a pool of the colour its tone means (green good, amber to look at, red late) and the figure is set large.
 */
export function StatTile({ label, text, hint, tone = '' }: { label: string; text: string; hint?: string; tone?: string }) {
  const lumen = useLumen()
  // A figure that is a list ("Q1 2,17,035.00 · Q2 3,23,969.00") is shown as rows, one to a line.
  const rows = text.includes(' · ') ? text.split(' · ').map((part) => [part.slice(0, part.indexOf(' ')), part.slice(part.indexOf(' ') + 1)] as const) : null
  if (lumen) {
    return (
      <div style={{ '--hue': `var(--lumen-${hueOf(tone)})` } as CSSProperties} className="panel lumen-kpi relative flex flex-col gap-1 overflow-hidden !p-5">
        <p className="t-caption relative font-semibold text-[color:var(--color-text-muted)]">{label}</p>
        {rows ? (
          <dl className="lumen-kpi-rows relative text-sm">
            {rows.map(([name, value]) => (
              <div key={name} className="flex items-baseline justify-between gap-3">
                <dt className="text-[color:var(--color-text-muted)]">{name}</dt>
                <dd className="font-display font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="lumen-figure relative font-display font-semibold tabular-nums">{text}</p>
        )}
        {hint && <p className="t-caption relative text-[color:var(--color-text-faint)]">{hint}</p>}
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
      <p className="text-xs font-medium text-[color:var(--color-text-muted)]">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${tone || 'text-[color:var(--color-text)]'}`}>{text}</p>
      {hint && <p className="mt-0.5 text-[11px] text-[color:var(--color-text-faint)]">{hint}</p>}
    </div>
  )
}
