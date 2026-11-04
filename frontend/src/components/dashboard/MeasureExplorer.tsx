import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, X } from 'lucide-react'
import { api } from '../../api/client'
import type { ExploreView, FilterChip } from '../../types'
import { Drawer } from '../ui/Drawer'
import { CategoryBar } from './CategoryBar'
import { MonthlyChart } from './MonthlyChart'
import { RecordTable } from './RecordTable'
import { SERIES, count, inr } from './format'

export type ExploreTarget = { key: string; label: string; value: string; snapshot: boolean }
export type ExploreSource = 'orion' | 'tally'

const FORMAT = {
  money: inr,
  number: (value: number) => count(value),
  percent: (value: number) => `${value.toFixed(1)}%`,
}

function cleaned(filters: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== undefined && value !== ''))
}

/**
 * A key figure taken apart. Open a tile and see it by financial year; pick a year and see its months; and beside them the
 * same figure by every dimension that applies (capability, domain, state, client...). Every bar is a filter: pick one and the
 * other charts and the table of raw rows narrow to it; pick it again to undo. "Show on the dashboard" carries the picks back.
 */
export function MeasureExplorer({
  source,
  target,
  baseFilters,
  baseChips,
  onApply,
  onClose,
}: {
  source: ExploreSource
  target: ExploreTarget | null
  /** The dashboard's own filters when the tile was opened (without the period, for a figure that is a position today). */
  baseFilters: Record<string, string>
  baseChips: FilterChip[]
  /** Carry the picks made here back to the dashboard. */
  onApply?: (picks: Record<string, string>) => void
  onClose: () => void
}) {
  const [picks, setPicks] = useState<Record<string, string>>({})
  const [view, setView] = useState<ExploreView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('')
  const request = useRef(0)

  const merged = useMemo(() => cleaned({ ...baseFilters, ...picks }), [baseFilters, picks])
  const mergedKey = JSON.stringify(merged)
  const key = target?.key

  useEffect(() => {
    setPicks({})
    setView(null)
    setError('')
    setTab('')
  }, [key])

  useEffect(() => {
    if (!key) return
    const id = ++request.current
    setBusy(true)
    api
      .exploreMeasure(source, key, merged)
      .then((result) => {
        if (id !== request.current) return
        setView(result)
        setError('')
      })
      .catch((e: Error) => id === request.current && setError(e.message))
      .finally(() => id === request.current && setBusy(false))
    // merged is compared by value through mergedKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, key, mergedKey])

  const toggle = (dim: string, code: string) =>
    setPicks((current) => {
      const next = { ...current }
      if (next[dim] === code) delete next[dim]
      else next[dim] = code
      return next
    })

  // A year or a month decides the period, so it sets aside any from/to range the dashboard had.
  const pickYear = (code: string) =>
    setPicks((current) => {
      const next = { ...current }
      if (next.fy === code) {
        delete next.fy
        delete next.from
        delete next.to
      } else {
        next.fy = code
        next.from = ''
        next.to = ''
        delete next.month
      }
      return next
    })
  const pickMonth = (code: string) =>
    setPicks((current) => {
      const next = { ...current }
      if (next.month === code) {
        delete next.month
        if (!next.fy) {
          delete next.from
          delete next.to
        }
      } else {
        next.month = code
        next.fy = ''
        next.from = ''
        next.to = ''
      }
      return next
    })
  const removePick = (dim: string) =>
    setPicks((current) => {
      const next = { ...current }
      delete next[dim]
      if (dim === 'fy' || dim === 'month') {
        delete next.from
        delete next.to
      }
      return next
    })

  const fmt = FORMAT[view?.format ?? 'money']
  const picked = Object.entries(picks).filter(([, value]) => value !== '')
  const dataset = tab || view?.records[0]?.dataset || ''
  const loadRecords = (query: Parameters<typeof api.dashboardRecords>[2]) =>
    // The rows are the ones that count towards this figure (only won, only credit notes...), not the whole table.
    source === 'orion'
      ? api.dashboardRecords(dataset, merged, { ...query, measure: key })
      : api.tallyRecords(dataset, merged, { ...query, measure: key })

  const chips: (FilterChip & { removable: boolean })[] = (view?.chips ?? baseChips).map((chip) => ({ ...chip, removable: chip.key in picks }))
  const empty = view && !view.total && !view.years.length && !view.breakdowns.length

  return (
    <Drawer
      open={target !== null}
      onClose={onClose}
      title={target?.label ?? ''}
      subtitle={
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-2xl font-semibold tabular-nums text-[color:var(--color-text)]">{view ? fmt(view.total) : target?.value}</span>
          <span className="text-xs">
            {view?.snapshot ? 'as at the last warehouse load' : view ? 'for the selection below' : 'loading…'}
          </span>
        </span>
      }
      footer={
        <>
          {picked.length > 0 && (
            <button
              type="button"
              onClick={() => setPicks({})}
              className="rounded-lg px-3 py-2 text-sm font-medium text-[color:var(--color-text-muted)] hover:bg-muted"
            >
              Clear my picks
            </button>
          )}
          {onApply && picked.length > 0 && (
            <button
              type="button"
              onClick={() => {
                onApply(Object.fromEntries(picked))
                onClose()
              }}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-on-primary hover:opacity-90"
            >
              Show on the dashboard
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </>
      }
    >
      <div className={`space-y-5 transition-opacity ${busy ? 'opacity-60' : ''}`} aria-busy={busy}>
        <div className="flex flex-wrap items-center gap-2" aria-label="What this is narrowed to">
          {chips.length === 0 && <span className="text-xs text-[color:var(--color-text-muted)]">All of it. Click any bar to narrow.</span>}
          {chips.map((chip) =>
            chip.removable ? (
              <button
                key={chip.key}
                type="button"
                onClick={() => removePick(chip.key)}
                className="flex items-center gap-1.5 rounded-full bg-accent-dim py-1 pl-2.5 pr-1.5 text-xs text-accent hover:opacity-80"
              >
                <span className="opacity-70">{chip.label}</span>
                <span className="max-w-[200px] truncate font-medium">{chip.display}</span>
                <X className="h-3 w-3" aria-label="Remove" />
              </button>
            ) : (
              <span key={chip.key} className="rounded-full bg-muted py-1 pl-2.5 pr-2.5 text-xs text-[color:var(--color-text-muted)]">
                <span className="opacity-70">{chip.label}</span> <span className="font-medium">{chip.display}</span>
              </span>
            ),
          )}
        </div>

        {error && (
          <p role="alert" className="rounded-lg border border-negative/30 bg-negative-dim px-3 py-2 text-sm text-[color:var(--color-text)]">
            {error}
          </p>
        )}
        {view?.note && <p className="text-xs text-[color:var(--color-text-muted)]">{view.note}</p>}
        {!view && !error && <div className="shimmer h-72 rounded-xl bg-muted" aria-busy="true" />}
        {empty && <p className="rounded-xl border border-dashed border-[color:var(--color-border)] px-6 py-10 text-center text-sm text-[color:var(--color-text-muted)]">Nothing is recorded for this figure in the selection.</p>}

        {view && view.years.length > 0 && (
          <section className="rounded-xl border border-[color:var(--color-border)] bg-surface pt-3" aria-label="By financial year">
            <h3 className="px-4 text-sm font-semibold text-[color:var(--color-text)]">By financial year</h3>
            <p className="px-4 text-xs text-[color:var(--color-text-muted)]">Click a year to narrow everything below to it, and again to undo.</p>
            <MonthlyChart
              data={view.years.map((y) => ({ code: y.code, label: y.label, value: y.value }))}
              bars={[{ key: 'value', label: view.label, color: SERIES.revenue, format: view.format }]}
              leftFormat={view.format}
              selected={merged.fy}
              onSelect={pickYear}
              height={230}
            />
          </section>
        )}

        {view && view.months.length > 1 && (
          <section className="rounded-xl border border-[color:var(--color-border)] bg-surface pt-3" aria-label="By month">
            <h3 className="px-4 text-sm font-semibold text-[color:var(--color-text)]">By month</h3>
            <p className="px-4 text-xs text-[color:var(--color-text-muted)]">
              {merged.fy ? `Months of the year you picked.` : 'The last three years, month by month.'} Click a month to narrow to it.
            </p>
            <MonthlyChart
              data={view.months.map((m) => ({ code: m.code, label: m.label, value: m.value }))}
              bars={[{ key: 'value', label: view.label, color: SERIES.km, format: view.format }]}
              leftFormat={view.format}
              selected={merged.month}
              onSelect={pickMonth}
              height={210}
            />
          </section>
        )}

        {view && view.breakdowns.length > 0 && (
          <section aria-label="By dimension" className="space-y-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="t-h3 text-[color:var(--color-text)]">Taken apart</h3>
              <p className="text-xs text-[color:var(--color-text-muted)]">
                {view.additive ? 'Each chart adds up to the figure above.' : 'Each bar is the figure for that group; they do not add up to the total.'} Click any bar to narrow.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {view.breakdowns.map((b) => (
                <div key={b.key} className="flex flex-col rounded-xl border border-[color:var(--color-border)] bg-surface pt-3">
                  <div className="flex items-baseline justify-between gap-2 px-4">
                    <h4 className="text-[13px] font-semibold text-[color:var(--color-text)]">{b.label}</h4>
                    {picks[b.key] && (
                      <button type="button" onClick={() => removePick(b.key)} className="text-[11px] font-medium text-accent hover:underline">
                        Clear
                      </button>
                    )}
                  </div>
                  <CategoryBar
                    data={b.items}
                    selected={picks[b.key]}
                    onSelect={(code) => toggle(b.key, code)}
                    format={fmt}
                    labelWidth={140}
                    height={Math.max(110, b.items.length * 28 + 12)}
                    color={view.format === 'percent' ? SERIES.margin : undefined}
                  />
                  {b.more > 0 && <p className="px-4 pb-2 text-[11px] text-[color:var(--color-text-faint)]">Top {b.items.length} shown; {b.more} more. Narrow the selection to see them.</p>}
                </div>
              ))}
            </div>
          </section>
        )}

        {view && view.records.length > 0 && dataset && (
          <section aria-label="The records" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="t-h3 text-[color:var(--color-text)]">The records behind it</h3>
              {view.records.length > 1 && (
                <div role="tablist" className="flex gap-1 rounded-lg bg-muted p-0.5">
                  {view.records.map((r) => (
                    <button
                      key={r.dataset}
                      type="button"
                      role="tab"
                      aria-selected={dataset === r.dataset}
                      onClick={() => setTab(r.dataset)}
                      className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                        dataset === r.dataset ? 'bg-surface text-[color:var(--color-text)] shadow-card' : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'
                      }`}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {view.population_note && (
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-[color:var(--color-text-muted)]">
                <span className="font-medium text-[color:var(--color-text)]">What is listed: </span>
                {view.population_note}
              </p>
            )}
            <RecordTable load={loadRecords} resetKey={`${source}|${dataset}|${mergedKey}`} fileName={`${view.measure}-${dataset}`} />
          </section>
        )}
      </div>
    </Drawer>
  )
}
