import type { ReactNode } from 'react'
import { ArrowDownRight, ArrowUpRight, ChevronRight, Info, Minus } from 'lucide-react'
import type { DashboardKpi, KpiChange } from '../../types'
import { count, inr } from './format'
import { HoverCard } from './HoverCard'
import { Sparkline } from './Sparkline'
import { AnimatedFigure } from '../../lumen/AnimatedFigure'
import { useLumen } from '../../lumen/useLumen'

const DELTA_STYLE = {
  positive: 'bg-positive-dim text-positive',
  negative: 'bg-negative-dim text-negative',
  neutral: 'bg-muted text-[color:var(--color-text-muted)]',
} as const

const VERDICT = { positive: 'favourable', negative: 'unfavourable', neutral: 'no clear direction' } as const

/** Arrow follows the sign of the number; colour follows whether that is good news. */
function direction(delta: string): 'up' | 'down' | 'flat' {
  if (delta.startsWith('+')) return 'up'
  if (delta.startsWith('-')) return 'down'
  return 'flat'
}

function Heading({ children }: { children: ReactNode }) {
  return (
    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[color:var(--color-text-muted)]">
      {children}
    </p>
  )
}

/** What the figure is, in business terms, and exactly how it is worked out. */
function AboutCard({ kpi }: { kpi: DashboardKpi }) {
  const about = kpi.about
  return (
    <div className="space-y-2.5">
      <p className="text-sm font-semibold text-[color:var(--color-text)]">{kpi.label}</p>
      <div>
        <Heading>What it means</Heading>
        <p>{about?.means || kpi.hint}</p>
      </div>
      {about?.calc && (
        <div>
          <Heading>How it is calculated</Heading>
          <p>{about.calc}</p>
        </div>
      )}
      {about?.scope && (
        <p className="border-t border-[color:var(--color-border)] pt-2 text-[11px] text-[color:var(--color-text-faint)]">
          {about.scope}
        </p>
      )}
    </div>
  )
}

function Row({ name, value, range }: { name: string; value?: string; range?: string }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] items-baseline gap-x-2 py-1">
      <span className="text-[color:var(--color-text-faint)]">{name}</span>
      <span>
        <span className="font-semibold tabular-nums text-[color:var(--color-text)]">{value ?? '—'}</span>
        {range && <span className="block text-[11px] text-[color:var(--color-text-faint)]">{range}</span>}
      </span>
    </div>
  )
}

/** The other comparison, kept beside the one that leads: the figure it is set against, its dates and the change. */
function AlsoBlock({ kpi, change }: { kpi: DashboardKpi; change: KpiChange }) {
  return (
    <div className="border-t border-[color:var(--color-border)] pt-2">
      <Heading>Also {change.compare}</Heading>
      <Row name="This selection" value={kpi.detail?.current_value ?? kpi.value} range={kpi.detail?.current_range} />
      <Row name="Earlier" value={change.value} range={change.range} />
      <p className="mt-0.5 border-t border-[color:var(--color-border)] pt-1.5">
        Change <span className="font-semibold tabular-nums text-[color:var(--color-text)]">{change.delta}</span>
        <span className="text-[color:var(--color-text-faint)]"> · {VERDICT[change.delta_type]}</span>
      </p>
    </div>
  )
}

/** Both sides of a comparison: the figure now, the figure it is measured against, and the dates of each. */
function ComparisonCard({ kpi, which }: { kpi: DashboardKpi; which: 'previous' | 'yoy' | 'both' }) {
  const d = kpi.detail
  const hasPrev = Boolean(d?.previous_value)
  const hasYoy = Boolean(d?.yoy_value)
  const showPrev = which !== 'yoy' && hasPrev
  const showYoy = which !== 'previous' && hasYoy

  // Older API responses carry the change but not the figures behind it. Say what is known
  // rather than claim there is no comparison.
  if (!showPrev && !showYoy && kpi.delta && kpi.compare) {
    return (
      <div className="space-y-1.5">
        <p className="text-sm font-semibold text-[color:var(--color-text)]">Compared with {kpi.compare.replace(/^vs /, '')}</p>
        <p>
          Change{' '}
          <span className="font-semibold tabular-nums text-[color:var(--color-text)]">{kpi.delta}</span>
          <span className="text-[color:var(--color-text-faint)]"> · {VERDICT[kpi.delta_type]}</span>
        </p>
        <p className="text-[11px] text-[color:var(--color-text-faint)]">
          The earlier figure and its dates are not in this response. Reload the page, or restart the API if this keeps
          showing.
        </p>
      </div>
    )
  }

  if (!showPrev && !showYoy) {
    return (
      <div className="space-y-1.5">
        <p className="text-sm font-semibold text-[color:var(--color-text)]">No comparison</p>
        <p>{d?.note || 'This figure is not compared with an earlier period.'}</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {showPrev && (
        <div>
          <Heading>Compared with {d?.compare?.replace(/^vs /, '')}</Heading>
          <Row name="This selection" value={d?.current_value ?? kpi.value} range={d?.current_range} />
          <Row name="Earlier" value={d?.previous_value} range={d?.previous_range} />
          {kpi.delta ? (
            <p className="mt-0.5 border-t border-[color:var(--color-border)] pt-1.5">
              Change{' '}
              <span className="font-semibold tabular-nums text-[color:var(--color-text)]">{kpi.delta}</span>
              <span className="text-[color:var(--color-text-faint)]"> · {VERDICT[kpi.delta_type]}</span>
            </p>
          ) : (
            <p className="mt-0.5 border-t border-[color:var(--color-border)] pt-1.5 text-[11px] text-[color:var(--color-text-faint)]">
              No percentage change: there was nothing to set it against in that period.
            </p>
          )}
        </div>
      )}
      {which !== 'yoy' && kpi.also && <AlsoBlock kpi={kpi} change={kpi.also} />}
      {showYoy && (
        <div className={showPrev ? 'border-t border-[color:var(--color-border)] pt-2' : ''}>
          <Heading>Year on year, {d?.yoy_label?.replace(/^vs /, '')}</Heading>
          <Row name="This selection" value={d?.current_value ?? kpi.value} range={d?.current_range} />
          <Row name="Last year" value={d?.yoy_value} range={d?.yoy_range} />
          {typeof kpi.yoy_pct === 'number' && (
            <p className="mt-0.5 border-t border-[color:var(--color-border)] pt-1.5">
              Change{' '}
              <span className="font-semibold tabular-nums text-[color:var(--color-text)]">
                {kpi.yoy_pct > 0 ? '+' : ''}
                {kpi.yoy_pct.toFixed(1)}%
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function sparkLabel(kpi: DashboardKpi): string {
  const labels = kpi.spark_labels ?? []
  const values = kpi.spark ?? []
  if (values.length < 3 || labels.length !== values.length) return `${kpi.label} trend by month`
  const format = kpi.spark_kind === 'number' ? count : inr
  return `${kpi.label} by month, ${labels[0]} to ${labels[labels.length - 1]}: from ${format(values[0])} to ${format(values[values.length - 1])}.`
}

/** How the figure moved, or why it did not: the pill, what it is measured against, and the pop-over that shows both sides. */
function Change({
  kpi,
  snapshotLabel,
  snapshotNote,
  brief = false,
}: {
  kpi: DashboardKpi
  snapshotLabel: string
  snapshotNote: string
  /** Just the pill; what it is measured against stays in the pop-over. For a tile with little room. */
  brief?: boolean
}) {
  const dir = kpi.delta ? direction(kpi.delta) : null
  const Arrow = dir === 'up' ? ArrowUpRight : dir === 'down' ? ArrowDownRight : Minus

  if (kpi.scope === 'snapshot') {
    return (
      <HoverCard
        label={`About the ${kpi.label} snapshot`}
        trigger={
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-[color:var(--color-text-muted)]">
            {snapshotLabel}
          </span>
        }
      >
        <div className="space-y-1.5">
          <p className="text-sm font-semibold text-[color:var(--color-text)]">Not compared</p>
          <p>{snapshotNote}</p>
        </div>
      </HoverCard>
    )
  }

  if (kpi.delta) {
    return (
      <HoverCard
        label={`${kpi.label} changed ${kpi.delta} ${kpi.compare ?? ''}. Show what it is compared with`}
        trigger={
          <span className="inline-flex min-w-0 max-w-full items-center gap-1.5">
            <span
              className={`inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs font-semibold tabular-nums ${DELTA_STYLE[kpi.delta_type]}`}
            >
              <Arrow className="h-3 w-3" aria-hidden="true" />
              {kpi.delta}
              <span className="sr-only">, {VERDICT[kpi.delta_type]}</span>
            </span>
            {kpi.compare && !brief && (
              <span className="min-w-0 truncate text-[11px] text-[color:var(--color-text-faint)] underline decoration-dotted underline-offset-2">
                {kpi.compare}
              </span>
            )}
          </span>
        }
      >
        <ComparisonCard kpi={kpi} which={kpi.detail?.previous_value ? 'previous' : 'both'} />
      </HoverCard>
    )
  }

  return (
    <HoverCard
      label={`Why ${kpi.label} has no comparison`}
      trigger={
        <span className="text-[11px] text-[color:var(--color-text-faint)] underline decoration-dotted underline-offset-2">
          No comparison
        </span>
      }
    >
      <ComparisonCard kpi={kpi} which="both" />
    </HoverCard>
  )
}

/**
 * One figure. `lead` is a headline: a large value, how it moved and a trend with room to read it. `stat` is a
 * supporting figure, set quietly in a shared panel so a row of them does not shout. Either can be asked what it means
 * (the (i)), what it is compared with (the change) and, where the figure allows it, taken apart (a click).
 * Colour is reserved for the change; a headline that moved the wrong way also gets a thin red edge so it is seen first.
 */
export function MetricCard({
  kpi,
  icon,
  onExplore,
  variant = 'lead',
  snapshotLabel = 'Books snapshot',
  snapshotNote = 'A balance as at the last warehouse load. It is not set against an earlier period, and the period and billing filters do not change it.',
}: {
  kpi: DashboardKpi
  icon?: ReactNode
  /** Makes the tile a doorway: clicking it opens the figure taken apart. */
  onExplore?: () => void
  variant?: 'lead' | 'stat'
  /** What to call a figure that ignores the period. Tally says books snapshot; Orion says position today. */
  snapshotLabel?: string
  snapshotNote?: string
}) {
  const snapshot = kpi.scope === 'snapshot'
  const yoy = kpi.yoy_pct
  const labels = kpi.spark_labels ?? []
  const hasSpark = (kpi.spark?.length ?? 0) >= 3
  const stat = variant === 'stat'
  const worse = !snapshot && kpi.delta_type === 'negative' && Boolean(kpi.delta)

  const open = onExplore
    ? (event: { target: EventTarget }) => {
        // The (i) and the comparison pills have their own pop-overs; only the rest of the tile opens the drill-down.
        if ((event.target as HTMLElement).closest('button, a')) return
        onExplore()
      }
    : undefined

  const lumen = useLumen()
  const figure = lumen ? <AnimatedFigure text={kpi.value} /> : kpi.value

  const value = onExplore ? (
    <button
      type="button"
      onClick={onExplore}
      aria-label={`Explore ${kpi.label}: ${kpi.value}. Opens it by year and by every dimension.`}
      className={`${lumen ? 'lumen-figure ' : ''}block text-left font-semibold leading-none tracking-tight text-[color:var(--color-text)] tabular-nums focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[color:var(--color-accent)] ${
        stat ? 'text-[1.35rem]' : 'text-[2rem]'
      }`}
    >
      {figure}
    </button>
  ) : (
    <p className={`${lumen ? 'lumen-figure ' : ''}font-semibold leading-none tracking-tight text-[color:var(--color-text)] tabular-nums ${stat ? 'text-[1.35rem]' : 'text-[2rem]'}`}>
      {figure}
    </p>
  )

  const about = (
    <HoverCard
      label={`What does ${kpi.label} mean?`}
      trigger={<Info className="h-3.5 w-3.5" aria-hidden="true" />}
      className="shrink-0 p-0.5 text-[color:var(--color-text-faint)] hover:text-accent"
      width={310}
    >
      <AboutCard kpi={kpi} />
    </HoverCard>
  )

  if (stat) {
    return (
      <article
        className={`group/tile relative flex min-w-0 items-center justify-between gap-3 px-4 py-3.5 ${
          onExplore ? 'cursor-pointer transition-colors hover:bg-muted/60' : ''
        }`}
        onClick={open}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h3 className="truncate text-xs font-medium text-[color:var(--color-text-muted)]">{kpi.label}</h3>
            {about}
          </div>
          <div className="mt-1.5">{value}</div>
          <div className="mt-2 min-h-[1.25rem]">
            <Change kpi={kpi} snapshotLabel={snapshotLabel} snapshotNote={snapshotNote} brief />
          </div>
        </div>
        {hasSpark && (
          <Sparkline className="hidden w-20 shrink-0 sm:block" values={kpi.spark ?? []} labels={labels} kind={kpi.spark_kind} percent={kpi.value.trim().endsWith('%')} label={sparkLabel(kpi)} />
        )}
      </article>
    )
  }

  return (
    <article
      data-tone={kpi.tone}
      className={`panel group/tile lumen-kpi relative flex min-w-0 flex-col overflow-hidden p-5 ${
        onExplore ? 'cursor-pointer transition-[border-color,box-shadow] hover:border-[color:var(--color-accent)] hover:shadow-raised' : ''
      }`}
      onClick={open}
    >
      {worse && <span aria-hidden="true" className="absolute inset-x-0 top-0 h-0.5 bg-negative" />}
      <header className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {icon && (
            <span className="inline-flex shrink-0 rounded-lg bg-accent-dim p-1.5 text-accent" aria-hidden="true">
              {icon}
            </span>
          )}
          <h3 className="truncate text-sm font-medium text-[color:var(--color-text-muted)]">{kpi.label}</h3>
        </div>
        {about}
      </header>

      <div className="mt-3">{value}</div>

      <div className="mt-3 flex min-h-[1.375rem] min-w-0 items-center gap-x-2">
        <Change kpi={kpi} snapshotLabel={snapshotLabel} snapshotNote={snapshotNote} />
      </div>

      {/* Where a year can be compared two ways the second line keeps its place even when this figure has nothing to put
          in it, so switching the comparison does not make the card, and everything below it, change height. */}
      {!kpi.also && !snapshot && (kpi.full || kpi.detail?.full_label) && <p className="mt-1 min-h-[17px]" aria-hidden="true" />}

      {kpi.also && !snapshot && (
        <p className="mt-1 min-h-[17px] truncate text-[11px] text-[color:var(--color-text-faint)]">
          <HoverCard
            label={`${kpi.label} ${kpi.also.delta} ${kpi.also.compare}. Show what it is compared with`}
            trigger={
              <span className="underline decoration-dotted underline-offset-2">
                <span
                  className={`font-medium tabular-nums ${
                    kpi.also.delta_type === 'positive' ? 'text-positive' : kpi.also.delta_type === 'negative' ? 'text-negative' : 'text-[color:var(--color-text-muted)]'
                  }`}
                >
                  {kpi.also.delta}
                </span>{' '}
                {kpi.also.compare}
              </span>
            }
          >
            <AlsoBlock kpi={kpi} change={kpi.also} />
          </HoverCard>
        </p>
      )}

      {typeof yoy === 'number' && !snapshot && !kpi.also && (
        <p className="mt-1 text-[11px] text-[color:var(--color-text-faint)]">
          <HoverCard
            label={`${kpi.label} year on year ${yoy.toFixed(1)} percent. Show what it is compared with`}
            trigger={
              <span className="underline decoration-dotted underline-offset-2">
                <span className="font-medium tabular-nums text-[color:var(--color-text-muted)]">
                  {yoy > 0 ? '+' : ''}
                  {yoy.toFixed(1)}%
                </span>{' '}
                {kpi.yoy_label || 'vs last year'}
              </span>
            }
          >
            <ComparisonCard kpi={kpi} which="yoy" />
          </HoverCard>
        </p>
      )}

      {/* A headline with no trend to draw says what it is instead, so the card is not left half empty beside one that has. */}
      {!hasSpark && kpi.hint && <p className="mt-auto pt-4 text-xs leading-snug text-[color:var(--color-text-muted)]">{kpi.hint}</p>}

      {hasSpark && (
        <div className="mt-4">
          <Sparkline tall values={kpi.spark ?? []} labels={labels} kind={kpi.spark_kind} percent={kpi.value.trim().endsWith('%')} label={sparkLabel(kpi)} />
          {labels.length >= 3 && (
            <p className="mt-1 text-[10px] text-[color:var(--color-text-faint)]">
              Monthly · {labels[0]} – {labels[labels.length - 1]}
            </p>
          )}
        </div>
      )}
      {onExplore && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute right-10 top-[1.3rem] flex items-center gap-0.5 text-[11px] font-medium text-accent opacity-0 transition-opacity group-hover/tile:opacity-100"
        >
          Explore
          <ChevronRight className="h-3 w-3" />
        </span>
      )}
    </article>
  )
}
