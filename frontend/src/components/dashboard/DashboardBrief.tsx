import { useState } from 'react'
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  Info,
  Minus,
  Sparkles,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useAssistant } from '../../ai/AssistantContext'
import { useLumen } from '../../lumen/useLumen'
import type { DashboardFilterKey, DashboardKpi, Insight, InsightTone } from '../../types'

const TONE: Record<InsightTone, { text: string; soft: string; Icon: LucideIcon; label: string }> = {
  negative: { text: 'text-negative', soft: 'bg-negative-dim text-negative', Icon: TrendingDown, label: 'Declining' },
  warning: { text: 'text-warning', soft: 'bg-warning-dim text-warning', Icon: TriangleAlert, label: 'Worth a look' },
  positive: { text: 'text-positive', soft: 'bg-positive-dim text-positive', Icon: TrendingUp, label: 'Improving' },
  neutral: { text: 'text-[color:var(--color-text-muted)]', soft: 'bg-muted text-[color:var(--color-text-muted)]', Icon: Info, label: 'Note' },
}

const DELTA = {
  positive: 'bg-positive-dim text-positive',
  negative: 'bg-negative-dim text-negative',
  neutral: 'bg-muted text-[color:var(--color-text-muted)]',
} as const

/** How far a figure moved, as a number to rank by. The server sends it as text when it has no percentage. */
function size(kpi: DashboardKpi): number {
  if (typeof kpi.delta_pct === 'number') return Math.abs(kpi.delta_pct)
  const found = kpi.delta.match(/\d+(\.\d+)?/)
  return found ? Number(found[0]) : 0
}

function arrow(delta: string) {
  return delta.startsWith('+') ? ArrowUpRight : delta.startsWith('-') ? ArrowDownRight : Minus
}

function Column({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col p-4 sm:p-5">
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="eyebrow">{title}</h2>
        {hint && <span className="truncate text-[11px] text-[color:var(--color-text-faint)]">{hint}</span>}
      </header>
      {children}
    </section>
  )
}

/**
 * The first thing on a dashboard, answering three questions from what the server already worked out: what matters
 * (the findings that need attention, the worst first), what changed (the figures that moved most against the
 * comparison window), and what to do next (one step for each finding: open the tab that explains it, narrow the page
 * to it, or ask the Copilot why). Findings that are only good news or background wait behind "all findings".
 */
export function DashboardBrief({
  kpis,
  insights,
  range,
  comparison,
  tabLabel,
  onFilter,
  onOpenTab,
  onExplore,
  onCompare,
  canAsk = true,
}: {
  /** The figures shown on this tab, to find what moved. */
  kpis: DashboardKpi[]
  insights: Insight[]
  /** The span the page is showing, e.g. "Apr 26 – Sep 26". */
  range?: string
  /** What the changes are measured against, e.g. "vs prior 153 days". */
  comparison?: string
  /** Name of the tab an insight points to. */
  tabLabel?: (tab: string) => string | undefined
  onFilter: (key: DashboardFilterKey, value: string) => void
  onOpenTab: (tab: string) => void
  onExplore?: (kpi: DashboardKpi) => void
  /** Sets a period to compare, when nothing is being compared. */
  onCompare?: () => void
  /** False where the Copilot cannot read this dashboard's figures, so no step sends it a question. */
  canAsk?: boolean
}) {
  const lumen = useLumen()
  const assistant = useAssistant()
  const { ask } = assistant
  const enabled = assistant.enabled && canAsk
  const [all, setAll] = useState(false)

  // The server flags a finding only once it passes a watch level; the rest are notes and good news. Flagged ones lead,
  // then notes, then good news, each in the server's own order of importance.
  const RANK: Record<InsightTone, number> = { negative: 0, warning: 1, neutral: 2, positive: 3 }
  const ranked = [...insights].sort((a, b) => RANK[a.tone] - RANK[b.tone])
  const attention = ranked.filter((item) => item.tone === 'negative' || item.tone === 'warning')
  const lead = ranked[0]
  const flagged = Boolean(lead) && attention.includes(lead)
  const more = ranked.slice(1, 3)
  const movers = kpis
    .filter((kpi) => kpi.scope !== 'snapshot' && kpi.delta)
    .sort((a, b) => size(b) - size(a))
    .slice(0, 4)
  // With nothing flagged, the next steps are the notes that point somewhere.
  const pointsSomewhere = (item: Insight) => Boolean(item.action || item.tab)
  const steps = (attention.length ? attention : ranked.filter(pointsSomewhere))
    .filter((item) => canAsk || pointsSomewhere(item))
    .slice(0, 3)
  const hidden = ranked.filter((item) => item !== lead && !more.includes(item))

  const act = (item: Insight) => {
    if (item.tab) onOpenTab(item.tab)
    else if (item.action) onFilter(item.action.key, item.action.value)
    else ask(`Investigate this finding and tell me what is behind it: ${item.title}`)
  }
  const verb = (item: Insight) =>
    item.tab ? `Open ${tabLabel?.(item.tab) ?? 'the details'}` : item.action ? 'Narrow the page to this' : 'Ask the Copilot why'

  const LeadIcon = lead ? TONE[lead.tone].Icon : CheckCircle2
  const quiet = (
    <p className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-positive-dim px-2.5 py-1 text-xs font-medium text-positive">
      <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
      Nothing is flagged in this selection
    </p>
  )

  const hiddenFindings =
    hidden.length > 0 ? (
        <div className="border-t border-[color:var(--color-border)]">
          <button
            type="button"
            onClick={() => setAll((value) => !value)}
            aria-expanded={all}
            className="interactive flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-xs font-medium text-[color:var(--color-text-muted)] hover:bg-muted sm:px-5"
          >
            <span>
              {all ? 'Hide' : 'Show'} {hidden.length} more {hidden.length === 1 ? 'finding' : 'findings'}
            </span>
            <ChevronDown className={`h-4 w-4 transition-transform ${all ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>
          {all && (
            <ul className="grid gap-px border-t border-[color:var(--color-border)] bg-[color:var(--color-border)] md:grid-cols-2 xl:grid-cols-3">
              {hidden.map((item) => {
                const tone = TONE[item.tone]
                const Icon = tone.Icon
                return (
                  <li key={item.id} className="flex gap-3 bg-surface px-4 py-3">
                    <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone.text}`} aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium leading-snug text-[color:var(--color-text)]">
                        <span className="sr-only">{tone.label}: </span>
                        {item.title}
                      </p>
                      <p className="mt-0.5 text-xs leading-relaxed text-[color:var(--color-text-muted)]">{item.detail}</p>
                      {(item.action || item.tab) && (
                        <button type="button" onClick={() => act(item)} className="mt-1.5 text-xs font-medium text-accent hover:underline">
                          {verb(item)}
                        </button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      ) : null

  if (lumen) {
    const accent = 'bg-white/20 text-[color:var(--orion-on-primary)]'
    return (
      <section aria-label="Brief" className="panel overflow-hidden !p-0">
        <div className="relative overflow-hidden p-6 text-[color:var(--orion-on-primary)] sm:p-8" style={{ backgroundImage: 'var(--orion-highlight-fill)' }}>
          <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
          <div className="relative">
            <p className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] opacity-90">
              What matters {range && <span className="font-medium normal-case tracking-normal opacity-85">· {range}</span>}
            </p>
            {lead ? (
              <>
                <p className="font-display mt-2 max-w-3xl text-2xl font-semibold leading-snug sm:text-3xl">
                  <span className="sr-only">{TONE[lead.tone].label}: </span>
                  {lead.title}
                </p>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed opacity-90">{lead.detail}</p>
                {!flagged && <p className={`mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${accent}`}><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Nothing is flagged in this selection</p>}
                {more.length > 0 && (
                  <ul className="mt-4 flex flex-wrap gap-2">
                    {more.map((item) => {
                      const Icon = TONE[item.tone].Icon
                      return (
                        <li key={item.id} className={`inline-flex max-w-full items-center gap-1.5 rounded-full px-3 py-1.5 text-sm ${accent}`} title={item.detail}>
                          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          <span className="sr-only">{TONE[item.tone].label}: </span>
                          <span className="truncate">{item.title}</span>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </>
            ) : (
              <>
                <p className="font-display mt-2 text-2xl font-semibold sm:text-3xl">Nothing needs attention here</p>
                <p className="mt-2 text-sm opacity-90">No finding in this selection is declining or worth a second look.</p>
              </>
            )}
          </div>
        </div>

        <div className="grid gap-px bg-[color:var(--color-border)] lg:grid-cols-2">
          <div className="bg-[color:var(--orion-surface-fill)] p-5">
            <h2 className="eyebrow mb-3">What changed</h2>
            {movers.length > 0 ? (
              <>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {movers.map((kpi) => {
                    const Arrow = arrow(kpi.delta)
                    const open = onExplore && kpi.explore ? () => onExplore(kpi) : undefined
                    return (
                      <li key={kpi.key}>
                        <button type="button" onClick={open} disabled={!open} className={`interactive flex w-full flex-col items-start gap-1 rounded-2xl bg-muted/60 p-3 text-left ${open ? 'hover:bg-muted' : 'cursor-default'}`}>
                          <span className="block max-w-full truncate text-xs text-[color:var(--color-text-muted)]">{kpi.label}</span>
                          <span className="font-display text-lg font-semibold tabular-nums">{kpi.value}</span>
                          <span className={`inline-flex items-center gap-0.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${DELTA[kpi.delta_type]}`}>
                            <Arrow className="h-3 w-3" aria-hidden="true" />
                            {kpi.delta}
                            <span className="sr-only">, {kpi.delta_type === 'positive' ? 'favourable' : kpi.delta_type === 'negative' ? 'unfavourable' : 'no clear direction'}</span>
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
                {comparison && <p className="t-caption mt-2 text-[color:var(--color-text-faint)]">Change {comparison}</p>}
              </>
            ) : (
              <div className="space-y-3">
                <p className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">Nothing is being compared yet. Pick a period or a financial year and each figure shows how far it moved.</p>
                {onCompare && (
                  <button type="button" onClick={onCompare} className="interactive inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-border-strong)] px-4 py-2 text-sm font-semibold hover:bg-muted">
                    Compare the last 6 months <ArrowRight className="h-4 w-4 text-accent" aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="bg-[color:var(--orion-surface-fill)] p-5">
            <h2 className="eyebrow mb-3">What to do next</h2>
            <ol className="space-y-2">
              {steps.map((item, index) => (
                <li key={item.id}>
                  <button type="button" onClick={() => act(item)} className="interactive group flex w-full items-start gap-3 rounded-2xl bg-muted/60 p-3 text-left hover:bg-muted">
                    <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-dim text-xs font-bold text-accent">{index + 1}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1 text-sm font-semibold">
                        {verb(item)}
                        <ArrowRight className="h-3.5 w-3.5 text-accent transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-xs leading-snug text-[color:var(--color-text-muted)]">{item.title}</span>
                    </span>
                  </button>
                </li>
              ))}
              {steps.length === 0 && <li className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">No action is needed. Click any bar, slice or row to look closer, or open a figure to see it taken apart.</li>}
              {enabled && (
                <li>
                  <button type="button" onClick={() => ask("Summarize what I'm looking at and tell me what needs attention.")} className="interactive inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-accent hover:bg-accent-dim">
                    <Sparkles className="h-4 w-4 shrink-0" aria-hidden="true" /> Ask the Copilot for a summary
                  </button>
                </li>
              )}
            </ol>
          </div>
        </div>
        {hiddenFindings}
      </section>
    )
  }

  return (
    <section aria-label="Brief" className="panel overflow-hidden">
      <div className="grid divide-y divide-[color:var(--color-border)] lg:grid-cols-[1.45fr_1fr_1fr] lg:divide-x lg:divide-y-0">
        <Column title="What matters" hint={range}>
          {lead ? (
            <div className="space-y-3.5">
              {!flagged && quiet}
              <div className="flex gap-3">
                <span className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${TONE[lead.tone].soft}`}>
                  <LeadIcon className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-base font-semibold leading-snug text-[color:var(--color-text)]">
                    <span className="sr-only">{TONE[lead.tone].label}: </span>
                    {lead.title}
                  </p>
                  <p className="mt-1 line-clamp-3 text-sm leading-relaxed text-[color:var(--color-text-muted)]" title={lead.detail}>
                    {lead.detail}
                  </p>
                </div>
              </div>
              {more.length > 0 && (
                <ul className="space-y-2 border-t border-[color:var(--color-border)] pt-3">
                  {more.map((item) => {
                    const Icon = TONE[item.tone].Icon
                    return (
                      <li key={item.id} className="flex items-start gap-2.5 text-sm">
                        <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${TONE[item.tone].text}`} aria-hidden="true" />
                        <span className="min-w-0 leading-snug text-[color:var(--color-text)]" title={item.detail}>
                          <span className="sr-only">{TONE[item.tone].label}: </span>
                          {item.title}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          ) : (
            <div className="flex gap-3">
              <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-positive-dim text-positive">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <p className="text-base font-semibold leading-snug text-[color:var(--color-text)]">Nothing needs attention here</p>
                <p className="mt-1 text-sm leading-relaxed text-[color:var(--color-text-muted)]">
                  No finding in this selection is declining or worth a second look.
                </p>
              </div>
            </div>
          )}
        </Column>

        <Column title="What changed">
          {movers.length > 0 ? (
            <>
              {/* Figures sit two by two, so this column is no taller than the findings beside it. Its rows are a fixed
                  height and it keeps the height of two of them whether two, three or four figures moved: switching the
                  comparison changes how many did, and the page below must not move when it does. */}
              <ul className={movers.length >= 2 ? 'grid min-h-[9.5rem] auto-rows-[74px] grid-cols-2 content-start gap-x-1 gap-y-1' : 'space-y-1'}>
                {movers.map((kpi) => {
                  const Arrow = arrow(kpi.delta)
                  const open = onExplore && kpi.explore ? () => onExplore(kpi) : undefined
                  return (
                    <li key={kpi.key}>
                      <button
                        type="button"
                        onClick={open}
                        disabled={!open}
                        className={`interactive flex w-full gap-1.5 rounded-lg px-2 py-1.5 text-left ${
                          movers.length >= 2 ? 'flex-col items-start' : 'items-center justify-between gap-3'
                        } ${open ? 'hover:bg-muted' : 'cursor-default'}`}
                      >
                        <span className="min-w-0 max-w-full">
                          <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{kpi.label}</span>
                          <span className="block text-sm font-semibold tabular-nums text-[color:var(--color-text)]">{kpi.value}</span>
                        </span>
                        <span
                          className={`inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${DELTA[kpi.delta_type]}`}
                        >
                          <Arrow className="h-3 w-3" aria-hidden="true" />
                          {kpi.delta}
                          <span className="sr-only">
                            , {kpi.delta_type === 'positive' ? 'favourable' : kpi.delta_type === 'negative' ? 'unfavourable' : 'no clear direction'}
                          </span>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
              {comparison && (
                <p title={`Change ${comparison}`} className="truncate px-2 pt-1 text-[11px] text-[color:var(--color-text-faint)]">
                  Change {comparison}
                </p>
              )}
            </>
          ) : (
            <div className="space-y-3">
              <p className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">
                Nothing is being compared yet. Pick a period or a financial year and each figure shows how far it moved.
              </p>
              {onCompare && (
                <button
                  type="button"
                  onClick={onCompare}
                  className="interactive inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--color-border-strong)] px-3 py-1.5 text-xs font-semibold text-[color:var(--color-text)] hover:bg-muted"
                >
                  Compare the last 6 months
                  <ArrowRight className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                </button>
              )}
            </div>
          )}
        </Column>

        <Column title="What to do next">
          <ol className="flex flex-1 flex-col space-y-1.5">
            {steps.map((item, index) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => act(item)}
                  className="interactive group flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-muted"
                >
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-dim text-[11px] font-bold text-accent">
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 text-sm font-semibold text-[color:var(--color-text)]">
                      {verb(item)}
                      <ArrowRight className="h-3.5 w-3.5 text-accent transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                    </span>
                    <span className="mt-0.5 line-clamp-2 block text-xs leading-snug text-[color:var(--color-text-muted)]">{item.title}</span>
                  </span>
                </button>
              </li>
            ))}
            {steps.length === 0 && (
              <li className="px-2 py-1.5 text-sm leading-relaxed text-[color:var(--color-text-muted)]">
                No action is needed. Click any bar, slice or row to look closer, or open a figure to see it taken apart.
              </li>
            )}
            {enabled && (
              <li className="lg:!mt-auto lg:pt-3">
                <button
                  type="button"
                  onClick={() => ask("Summarize what I'm looking at and tell me what needs attention.")}
                  className="interactive flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm font-medium text-accent hover:bg-accent-dim"
                >
                  <Sparkles className="h-4 w-4 shrink-0" aria-hidden="true" />
                  Ask the Copilot for a summary
                </button>
              </li>
            )}
          </ol>
        </Column>
      </div>

      {hiddenFindings}
    </section>
  )
}
