import { useId, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Download, Info, TriangleAlert } from 'lucide-react'
import type { ForecastConfidence, ForecastHorizon, ForecastMetric, ForecastPayload, ForecastRow } from '../../types'
import { useChartMotion, useNarrow } from '../../hooks/useNarrow'
import { Segmented } from '../ui/Segmented'
import { Select } from '../ui/Field'
import { axisInr, inr, inrFull } from './format'
import { downloadCsv } from './csv'

export type ForecastScope = { key: string; label: string; all: string; options: { id: string; label: string }[] }

const MONTH = new Intl.DateTimeFormat('en-IN', { month: 'short', year: '2-digit' })
const label = (month: string) => {
  const [y, m] = month.split('-').map(Number)
  return MONTH.format(new Date(y, m - 1, 1))
}
const long = (month: string) => {
  const [y, m] = month.split('-').map(Number)
  return new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' }).format(new Date(y, m - 1, 1))
}

const CONFIDENCE: Record<ForecastConfidence, { text: string; tone: string }> = {
  high: { text: 'High confidence', tone: 'bg-positive-dim text-positive' },
  medium: { text: 'Medium confidence', tone: 'bg-accent-dim text-accent' },
  low: { text: 'Low confidence', tone: 'bg-warning-dim text-warning' },
  very_low: { text: 'Very low confidence', tone: 'bg-negative-dim text-negative' },
}

const formatter = (unit: 'inr' | 'count') => ({
  compact: (v: number) => (unit === 'count' ? Math.round(v).toLocaleString('en-IN') : inr(v)),
  full: (v: number) => (unit === 'count' ? Math.round(v).toLocaleString('en-IN') : inrFull(v)),
  axis: (v: number) => (unit === 'count' ? String(Math.round(v)) : axisInr(v)),
})

/** A forecast with the pace nudged: each month is scaled by (1 + x) to the power of the years ahead, so a nudge of 5% is 5% a year, building up with distance. */
function nudged(rows: ForecastRow[], pace: number): ForecastRow[] {
  if (!pace) return rows
  const growth = 1 + pace / 100
  return rows.map((r, i) => {
    const f = Math.pow(growth, (i + 1) / 12)
    return { ...r, expected: r.expected * f, p10: r.p10 * f, p90: r.p90 * f, p025: r.p025 * f, p975: r.p975 * f }
  })
}

function horizons(base: ForecastHorizon[], rows: ForecastRow[], original: ForecastRow[], pace: number): ForecastHorizon[] {
  if (!pace) return base
  return base.map((h) => {
    const now = rows.slice(0, h.months).reduce((s, r) => s + r.expected, 0)
    const was = original.slice(0, h.months).reduce((s, r) => s + r.expected, 0)
    const ratio = was ? now / was : 1
    return {
      ...h,
      expected: now,
      p10: h.p10 * ratio,
      p90: h.p90 * ratio,
      p025: h.p025 * ratio,
      p975: h.p975 * ratio,
      change_pct: h.previous ? (now / h.previous - 1) * 100 : null,
    }
  })
}

function Chart({ metric, rows, months, band }: { metric: ForecastMetric; rows: ForecastRow[]; months: number; band: '80' | '95' }) {
  const uid = useId().replace(/:/g, '')
  const narrow = useNarrow()
  const motion = useChartMotion()
  const f = formatter(metric.unit)
  const past = metric.history.slice(-(months <= 12 ? 24 : 36))
  const lastActual = past[past.length - 1]
  const data = [
    ...past.map((p, i) => ({
      month: p.month, label: label(p.month), actual: p.value,
      // the forecast line starts where the actuals end, so the two join
      expected: i === past.length - 1 ? p.value : undefined,
      range: i === past.length - 1 ? ([p.value, p.value] as [number, number]) : undefined,
      wide: i === past.length - 1 ? ([p.value, p.value] as [number, number]) : undefined,
    })),
    ...rows.slice(0, months).map((r) => ({
      month: r.month, label: label(r.month), actual: undefined, expected: r.expected,
      range: [r.p10, r.p90] as [number, number], wide: [r.p025, r.p975] as [number, number],
    })),
  ]
  return (
    <div className="px-1 pb-2">
      <ResponsiveContainer width="100%" height={narrow ? 260 : 360}>
        <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
          <defs>
            <linearGradient id={`wide-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--orion-s-info)" stopOpacity={0.12} />
              <stop offset="100%" stopColor="var(--orion-s-info)" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--orion-chart-grid)" />
          <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }} interval="preserveStartEnd" minTickGap={24} />
          <YAxis axisLine={false} tickLine={false} width={50} domain={[(min: number) => Math.max(0, Math.floor(min * 0.85)), (max: number) => Math.ceil(max * 1.04)]} tick={{ fontSize: 10, fill: 'var(--orion-chart-tick)' }} tickFormatter={f.axis} />
          <Tooltip
            cursor={{ stroke: 'var(--orion-chart-tick)', strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const point = payload[0].payload as (typeof data)[number]
              return (
                <div className="tip-surface rounded-lg border px-3 py-2 text-xs">
                  <p className="font-semibold">{long(point.month)}</p>
                  {point.actual !== undefined ? (
                    <p>Actual <span className="font-semibold tabular-nums">{f.full(point.actual)}</span></p>
                  ) : (
                    <>
                      <p>Expected <span className="font-semibold tabular-nums">{f.full(point.expected ?? 0)}</span></p>
                      {point.range && <p className="text-[color:var(--color-text-muted)]">Likely between {f.compact(point.range[0])} and {f.compact(point.range[1])}</p>}
                      {point.wide && <p className="text-[color:var(--color-text-faint)]">Very likely between {f.compact(point.wide[0])} and {f.compact(point.wide[1])}</p>}
                    </>
                  )}
                </div>
              )
            }}
          />
          {lastActual && <ReferenceLine x={label(lastActual.month)} stroke="var(--orion-chart-tick)" strokeDasharray="4 4" label={{ value: 'Now', position: 'insideTopLeft', fontSize: 10, fill: 'var(--orion-chart-tick)' }} />}
          {band === '95' && <Area dataKey="wide" stroke="none" fill={`url(#wide-${uid})`} isAnimationActive={motion.isAnimationActive} connectNulls />}
          <Area dataKey="range" stroke="none" fill="var(--orion-s-info)" fillOpacity={0.22} isAnimationActive={motion.isAnimationActive} connectNulls />
          <Line dataKey="actual" stroke="var(--orion-s-primary)" strokeWidth={2.2} dot={false} isAnimationActive={motion.isAnimationActive} connectNulls />
          <Line dataKey="expected" stroke="var(--orion-s-info)" strokeWidth={2.2} strokeDasharray="6 4" dot={false} isAnimationActive={motion.isAnimationActive} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 px-3 text-[11px] text-[color:var(--color-text-muted)]">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded-full" style={{ background: 'var(--orion-s-primary)' }} />What happened</span>
        <span className="flex items-center gap-1.5"><span className="w-4 border-t-2 border-dashed" style={{ borderColor: 'var(--orion-s-info)' }} />Expected</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm" style={{ background: 'var(--orion-s-info)', opacity: 0.35 }} />Likely range ({band === '80' ? '8 in 10' : '19 in 20'} months land inside)</span>
      </div>
    </div>
  )
}

function Seasonality({ metric }: { metric: ForecastMetric }) {
  const s = metric.seasonality
  if (!s) return null
  const top = Math.max(...s.index.map((i) => Math.abs(i.effect_pct)), 1)
  const names = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
  return (
    <div>
      <p className="t-label mb-2">Usual pattern through the year <span className="font-normal text-[color:var(--color-text-muted)]">· {Math.round(s.strength * 100)}% of the ups and downs follow it</span></p>
      <div className="flex h-24 items-center gap-1" role="img" aria-label="How each month usually compares with the year's average">
        {s.index.map((i) => (
          <div key={i.month} className="flex h-full flex-1 flex-col items-center justify-center" title={`${names[i.month - 1]}: ${i.effect_pct > 0 ? '+' : ''}${i.effect_pct.toFixed(1)}% against the year's average`}>
            <div className="flex h-1/2 w-full items-end"><div className="w-full rounded-t-sm" style={{ height: `${i.effect_pct > 0 ? (i.effect_pct / top) * 100 : 0}%`, background: 'var(--orion-s-pos)' }} /></div>
            <div className="flex h-1/2 w-full items-start"><div className="w-full rounded-b-sm" style={{ height: `${i.effect_pct < 0 ? (-i.effect_pct / top) * 100 : 0}%`, background: 'var(--orion-s-neg)' }} /></div>
          </div>
        ))}
      </div>
      <div className="flex gap-1 text-center text-[10px] text-[color:var(--color-text-faint)]">{names.map((n, i) => <span key={i} className="flex-1">{n}</span>)}</div>
    </div>
  )
}

function Stat({ title, value, note }: { title: string; value: string; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[color:var(--color-border)]/60 py-2 last:border-0">
      <dt className="text-sm text-[color:var(--color-text-muted)]">{title}</dt>
      <dd className="text-right text-sm font-semibold tabular-nums">{value}{note && <span className="block text-[11px] font-normal text-[color:var(--color-text-faint)]">{note}</span>}</dd>
    </div>
  )
}

const signed = (v: number | null | undefined, digits = 1) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`)

/**
 * The forecast page, shared by the Orion and Tally dashboards: for each figure, what the next month, three months, six months, a year and three years are
 * likely to bring, as a number and a range, with how sure Orion is and why. A figure is a business the person can nudge ("what if we run 5% faster") and
 * every number can be exported. The statistics are on the server (`app/forecast.py`); this page draws them and says plainly when the history is too short.
 */
export function ForecastBoard({
  payload,
  scopes,
  filters,
  onFilter,
  busy,
  exportName,
}: {
  payload: ForecastPayload
  scopes: ForecastScope[]
  filters: Record<string, string>
  onFilter: (key: string, value: string) => void
  busy: boolean
  exportName: string
}) {
  const [metricKey, setMetricKey] = useState<string | null>(null)
  const [reach, setReach] = useState(12)
  const [band, setBand] = useState<'80' | '95'>('80')
  const [pace, setPace] = useState(0)

  const metric = payload.metrics.find((m) => m.key === (metricKey ?? payload.default_metric)) ?? payload.metrics[0]
  const rows = useMemo(() => nudged(metric?.forecast ?? [], pace), [metric, pace])
  const cards = useMemo(() => (metric ? horizons(metric.horizons, rows, metric.forecast, pace) : []), [metric, rows, pace])
  if (!metric) return null
  const f = formatter(metric.unit)
  const conf = metric.confidence ? CONFIDENCE[metric.confidence.level] : null
  const shownReach = Math.min(reach, rows.length)

  const exportRows = () =>
    downloadCsv(
      `${exportName}-${metric.key}-${new Date().toISOString().slice(0, 10)}.csv`,
      ['Month', 'Kind', 'Value', 'Low (8 in 10)', 'High (8 in 10)', 'Low (19 in 20)', 'High (19 in 20)'],
      [
        ...metric.history.map((h) => [h.month, 'Actual', h.value, '', '', '', '']),
        ...rows.map((r) => [r.month, 'Forecast', Math.round(r.expected), Math.round(r.p10), Math.round(r.p90), Math.round(r.p025), Math.round(r.p975)]),
      ],
    )

  return (
    <div className={`space-y-4 transition-opacity ${busy ? 'opacity-60' : ''}`} aria-busy={busy}>
      <section aria-label="What to forecast" className="panel flex flex-wrap items-end gap-x-6 gap-y-3 p-4">
        <Segmented
          label="Figure"
          value={metric.key}
          onChange={(key) => setMetricKey(key)}
          options={payload.metrics.map((m) => ({ id: m.key, label: m.label }))}
        />
        {scopes.map((scope) => (
          <label key={scope.key} className="block min-w-[11rem] flex-1 text-xs sm:max-w-[16rem]">
            <span className="t-label mb-1 block">{scope.label}</span>
            <Select value={filters[scope.key] ?? ''} onChange={(e) => onFilter(scope.key, e.target.value)} aria-label={scope.label}>
              <option value="">{scope.all}</option>
              {scope.options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </Select>
          </label>
        ))}
      </section>

      {!metric.available ? (
        <div className="panel p-6 text-sm text-[color:var(--color-text-muted)]">
          <p className="font-medium text-[color:var(--color-text)]">{metric.label} cannot be forecast yet.</p>
          {metric.notes.map((n) => <p key={n} className="mt-1">{n}</p>)}
        </div>
      ) : (
        <>
          <section aria-label="How sure" className="panel flex flex-wrap items-start gap-x-4 gap-y-2 p-4">
            {conf && <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${conf.tone}`}>{conf.text}</span>}
            <div className="min-w-0 flex-1 text-sm">
              <p><span className="font-medium">{metric.label}.</span> <span className="text-[color:var(--color-text-muted)]">{metric.means}</span></p>
              <ul className="mt-1.5 space-y-0.5 text-[13px] text-[color:var(--color-text-muted)]">
                {[...(metric.confidence?.reasons ?? []), ...metric.notes].map((n) => (
                  <li key={n} className="flex items-start gap-1.5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />{n}</li>
                ))}
              </ul>
            </div>
          </section>

          <section aria-label="Horizons" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {cards.map((h) => {
              const active = h.months === shownReach
              const up = (h.change_pct ?? 0) >= 0
              const goodUp = metric.key !== 'cost' && metric.key !== 'credit_notes'
              return (
                <button
                  key={h.months}
                  type="button"
                  onClick={() => setReach(Math.max(12, h.months))}
                  aria-pressed={active}
                  className={`interactive panel p-4 text-left ${active ? 'ring-2 ring-[color:var(--orion-ring)]' : ''}`}
                >
                  <p className="t-label text-[color:var(--color-text-muted)]">{h.label}</p>
                  <p className="mt-1 text-xl font-semibold tabular-nums" title={f.full(h.expected)}>{f.compact(h.expected)}</p>
                  <p className="t-caption mt-1 tabular-nums">Likely {f.compact(h.p10)} to {f.compact(h.p90)}</p>
                  <p className={`mt-1.5 text-xs font-medium tabular-nums ${h.change_pct === null ? 'text-[color:var(--color-text-faint)]' : up === goodUp ? 'text-positive' : 'text-negative'}`}>
                    {h.change_pct === null ? 'No earlier period to compare' : `${signed(h.change_pct)} on ${h.previous_note}`}
                  </p>
                  <p className="t-caption mt-0.5">to {long(h.through)}</p>
                </button>
              )
            })}
          </section>

          <section aria-label="Forecast chart" className="panel pt-4">
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-2 sm:px-5">
              <div>
                <h2 className="t-h3">{metric.label}: what happened and what is expected</h2>
                <p className="t-caption mt-0.5">Through {long(metric.data_through ?? '')}, then {shownReach} month{shownReach === 1 ? '' : 's'} ahead. The shaded range widens with distance, because the further out, the less is known.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Segmented label="Months ahead" value={String(shownReach)} onChange={(v) => setReach(Number(v))} options={[{ id: '12', label: '1 year' }, { id: '24', label: '2 years' }, { id: '36', label: '3 years' }]} />
                <Segmented label="Range" value={band} onChange={setBand} options={[{ id: '80', label: '8 in 10' }, { id: '95', label: '19 in 20' }]} />
                <button type="button" onClick={exportRows} className="interactive inline-flex h-8 items-center gap-1.5 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-2.5 text-xs font-semibold shadow-card hover:bg-surface-hover">
                  <Download className="h-3.5 w-3.5 text-accent" aria-hidden="true" />Export
                </button>
              </div>
            </div>
            <Chart metric={metric} rows={rows} months={shownReach} band={band} />
          </section>

          <section aria-label="What if" className="panel flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
            <div className="min-w-[14rem] flex-1">
              <label htmlFor="pace" className="t-label block">What if the pace is different from the trend?</label>
              <p className="t-caption mt-0.5">A nudge of 5% means 5% a year faster, building up with distance. It changes the numbers above, not the history.</p>
            </div>
            <div className="flex min-w-[16rem] flex-1 items-center gap-3">
              <span className="text-xs text-[color:var(--color-text-muted)]">−20%</span>
              <input id="pace" type="range" min={-20} max={20} step={1} value={pace} onChange={(e) => setPace(Number(e.target.value))} className="h-2 flex-1 accent-[color:var(--orion-accent)]" aria-valuetext={`${pace}% a year`} />
              <span className="text-xs text-[color:var(--color-text-muted)]">+20%</span>
              <span className="w-16 rounded-md bg-muted px-2 py-1 text-center text-xs font-semibold tabular-nums">{pace > 0 ? '+' : ''}{pace}%</span>
              {pace !== 0 && <button type="button" onClick={() => setPace(0)} className="interactive text-xs text-accent hover:underline">Reset</button>}
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section aria-label="Financial years" className="panel p-4 sm:p-5">
              <h2 className="t-h3">By financial year</h2>
              <p className="t-caption mt-0.5">What has happened so far in the year plus what is expected for the rest of it.</p>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[26rem] text-sm">
                  <thead>
                    <tr className="border-b border-[color:var(--color-border)] text-left text-xs text-[color:var(--color-text-muted)]">
                      <th className="py-2 pr-3 font-medium">Year</th>
                      <th className="py-2 pr-3 text-right font-medium">Done</th>
                      <th className="py-2 pr-3 text-right font-medium">Expected for the year</th>
                      <th className="py-2 text-right font-medium">Likely range</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metric.years.map((y) => (
                      <tr key={y.fy} className="border-b border-[color:var(--color-border)]/60">
                        <td className="py-2 pr-3 font-medium">FY {y.fy}{!y.complete && <span className="ml-1 text-[11px] font-normal text-[color:var(--color-text-faint)]">(part)</span>}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{y.actual_months ? <>{f.compact(y.actual)} <span className="text-[11px] text-[color:var(--color-text-faint)]">{y.actual_months} mo</span></> : '—'}</td>
                        <td className="py-2 pr-3 text-right font-semibold tabular-nums">{f.compact(y.expected)}</td>
                        <td className="py-2 text-right tabular-nums text-[color:var(--color-text-muted)]">{f.compact(y.p10)} to {f.compact(y.p90)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {pace !== 0 && <p className="t-caption mt-2">The yearly figures do not include the nudge above.</p>}
            </section>

            <section aria-label="Drivers" className="panel p-4 sm:p-5">
              <h2 className="t-h3">What is behind it</h2>
              <dl className="mt-2">
                {metric.drivers && (
                  <>
                    <Stat title="Recent pace" value={`${f.compact(metric.drivers.run_rate_per_month)} a month`} note={`${f.compact(metric.drivers.run_rate_per_year)} a year at this rate (last 3 months)`} />
                    <Stat title="Growth on a year ago" value={signed(metric.drivers.growth_yoy_pct)} note={metric.drivers.growth_yoy_pct === null ? 'Needs two years of history' : 'Last 12 months against the 12 before'} />
                    <Stat title="Pace the forecast expects" value={`${signed(metric.drivers.pace_pct_per_year)} a year`} note="Next 12 months against the last 3" />
                    <Stat title="How much it moves month to month" value={metric.drivers.volatility_pct === null ? '—' : `${metric.drivers.volatility_pct.toFixed(1)}%`} note="Spread of the last 12 months against their average" />
                    {metric.drivers.contracted_per_month !== undefined && (
                      <Stat title="Contracted monthly billing" value={f.compact(metric.drivers.contracted_per_month)} note="Active cases today, for comparison with the forecast" />
                    )}
                  </>
                )}
              </dl>
              <div className="mt-4"><Seasonality metric={metric} /></div>
            </section>
          </div>

          <section aria-label="How it was worked out" className="panel p-4 sm:p-5">
            <h2 className="t-h3">How this was worked out, and how well it would have done</h2>
            {metric.model && !metric.model.derived ? (
              <div className="mt-2 grid gap-4 md:grid-cols-2">
                <div className="space-y-2 text-sm text-[color:var(--color-text-muted)]">
                  <p>
                    Orion tried several simple methods on {metric.model.history_months} months of history (from {long(metric.model.from)}), tested each by going back in time and asking
                    "what would you have said then?", and blended the best ones, weighted by how well they did:
                  </p>
                  <ul className="space-y-1">
                    {metric.model.components.map((c) => (
                      <li key={c.key} className="flex items-center gap-2">
                        <span className="h-2 flex-none rounded-sm" style={{ width: `${Math.max(6, c.weight * 120)}px`, background: 'var(--orion-s-info)' }} />
                        <span className="text-[color:var(--color-text)]">{c.name}</span> {Math.round(c.weight * 100)}%
                      </li>
                    ))}
                  </ul>
                </div>
                <dl>
                  <Stat title="Typical miss, looking back" value={metric.accuracy?.error_pct === null || metric.accuracy?.error_pct === undefined ? 'Not enough history to test' : `${metric.accuracy.error_pct.toFixed(1)}% of the level`} note="Average error over the next 6 months, at past months" />
                  <Stat title="Better than a simple guess?" value={metric.accuracy?.skill === null || metric.accuracy?.skill === undefined ? '—' : `${metric.accuracy.skill > 0 ? '+' : ''}${Math.round(metric.accuracy.skill * 100)}%`} note="Against 'same as this month' or 'the recent average', whichever did better" />
                  <Stat title="Did the range hold?" value={metric.accuracy?.coverage_80 === null || metric.accuracy?.coverage_80 === undefined ? '—' : `${Math.round(metric.accuracy.coverage_80 * 100)}% inside`} note="The 8 in 10 range should contain about 80% of past months" />
                  <Stat title="Starting months tested" value={String(metric.accuracy?.origins ?? 0)} />
                </dl>
              </div>
            ) : (
              <p className="mt-2 text-sm text-[color:var(--color-text-muted)]">This is worked out from the forecasts of its two parts, so it always agrees with them.</p>
            )}
            <p className="mt-3 flex items-start gap-2 text-xs text-[color:var(--color-text-faint)]">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              A forecast carries today's pace forward. It does not know about a contract about to be won or lost, a price change, or a change in the rules. The further ahead, the more that matters, which is why the range widens. Use the far end to see direction, not to commit to a number.
            </p>
          </section>
        </>
      )}
    </div>
  )
}
