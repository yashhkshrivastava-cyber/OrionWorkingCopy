import { ArrowRight, CalendarClock, History, Play, TriangleAlert } from 'lucide-react'
import { count, formatDuration, percent } from '../../etl/format'
import { formatDateTime, timeAgo } from '../../formatTime'
import type { EtlPipeline, EtlRunDetail } from '../../types'
import { Button } from '../ui/Button'
import { SearchSelect } from '../ui/SearchSelect'
import { OutcomeCounts, RunBars, StepStrip } from './primitives'
import { StatusBadge } from './StatusBadge'

const GROUP_CHIP: Record<string, string> = {
  Orion: 'bg-accent-dim text-accent',
  Tally: 'bg-violet-dim text-violet',
}

function Stat({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div title={hint}>
      <dt className="text-[11px] font-medium text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className="mt-0.5 text-[15px] font-semibold tabular-nums text-[color:var(--color-text)]">{children}</dd>
    </div>
  )
}

/** In how many minutes a time is, or how long ago it was: "in 23 min", "just now". */
function until(iso: string | null, now: number): string {
  if (!iso) return ''
  const minutes = Math.round((new Date(iso).getTime() - now) / 60000)
  if (minutes <= 0) return 'any moment'
  if (minutes < 60) return `in ${minutes} min`
  return `in ${Math.round(minutes / 60)} h`
}

/** One pipeline: how it last went, how it usually goes, what it left behind, and a way to run it. */
export function PipelineCard({
  pipeline,
  progress,
  selected,
  note,
  now,
  onRun,
  onShowRuns,
  onOpenRun,
}: {
  pipeline: EtlPipeline
  progress?: EtlRunDetail | null
  selected?: boolean
  /** Something worth saying about the source, such as whether Tally Prime is reachable. */
  note?: React.ReactNode
  now: number
  onRun: (table?: string) => void
  onShowRuns: () => void
  onOpenRun: (id: number) => void
}) {
  const last = pipeline.last_run
  const running = pipeline.running
  // While a run is going its totals are still zero, so show how the last one that finished did.
  const finished = running ? pipeline.last_full_success : last
  const steps = progress?.steps ?? []
  const done = steps.filter((s) => s.status === 'succeeded').length
  const current = steps.find((s) => s.status === 'running')
  const failedRuns = pipeline.recent_runs.filter((r) => r.status === 'failed').length
  const tables = pipeline.steps.filter((s) => s.kind !== 'generated').map((s) => ({ id: s.name, label: s.name }))

  return (
    <article
      id={`pipeline-${pipeline.key}`}
      className={`panel flex flex-col transition-shadow ${selected ? 'ring-2 ring-accent/40' : ''}`}
    >
      <header className="flex items-start justify-between gap-3 px-5 pb-3 pt-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${GROUP_CHIP[pipeline.group] ?? 'bg-muted'}`}>
              {pipeline.group}
            </span>
            <h3 className="t-h3 truncate text-[color:var(--color-text)]">{pipeline.label}</h3>
          </div>
          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-[color:var(--color-text-muted)]">
            {pipeline.source}
            <ArrowRight className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="font-mono">{pipeline.target}</span>
          </p>
        </div>
        <StatusBadge status={running ? 'running' : last ? last.status : null} />
      </header>

      <div className="space-y-4 px-5 pb-4">
        {/* The headline: how long ago, and how it went. */}
        {running ? (
          <div>
            <p className="font-display text-[26px] font-bold leading-none tracking-tight text-[color:var(--color-text)]">
              {done}
              <span className="text-[color:var(--color-text-faint)]"> / {progress?.steps_total ?? pipeline.steps.length}</span>
              <span className="ml-2 text-sm font-medium tracking-normal text-[color:var(--color-text-muted)]">tables</span>
            </p>
            <div className="mt-3">
              <StepStrip steps={steps.length ? steps : pipeline.steps.map((s) => ({ name: s.name, status: 'pending' as const }))} />
            </div>
            <p className="mt-2 flex items-center justify-between gap-3 text-xs text-[color:var(--color-text-muted)]">
              <span className="truncate">{current ? `Loading ${current.name}` : 'Starting'}</span>
              {progress && (
                <button type="button" className="shrink-0 font-medium text-accent hover:underline" onClick={() => onOpenRun(progress.id)}>
                  Watch live
                </button>
              )}
            </p>
          </div>
        ) : last ? (
          <div>
            <p className="font-display text-[26px] font-bold leading-none tracking-tight text-[color:var(--color-text)]" title={formatDateTime(last.started_timestamp)}>
              {timeAgo(last.started_timestamp)}
            </p>
            <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">
              <button type="button" className="font-medium text-accent hover:underline" onClick={() => onOpenRun(last.id)}>
                Run #{last.id}
              </button>{' '}
              · took {formatDuration(last.duration_ms)} · {last.steps_succeeded} of {last.steps_total} tables
              {last.scope !== 'all' ? ` · only ${last.scope}` : ''}
              {' · '}
              {last.trigger === 'scheduled' ? 'scheduled' : `by ${last.started_by_name ?? 'a former user'}`}
            </p>
          </div>
        ) : (
          <div>
            <p className="font-display text-[26px] font-bold leading-none tracking-tight text-[color:var(--color-text-faint)]">Not yet</p>
            <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">This pipeline has not run. Run it to fill {pipeline.target}.</p>
          </div>
        )}

        {!running && last?.status === 'failed' && last.error && (
          <div className="flex gap-2.5 rounded-lg border border-negative/25 bg-negative-dim px-3 py-2.5">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-negative" aria-hidden="true" />
            <div className="min-w-0 text-xs">
              <p className="line-clamp-3 break-words text-[color:var(--color-text)]">{last.error}</p>
              <button type="button" className="mt-1 font-semibold text-negative hover:underline" onClick={() => onOpenRun(last.id)}>
                See what happened
              </button>
            </div>
          </div>
        )}

        {note}

        {pipeline.recent_runs.length > 0 && (
          <div>
            <RunBars runs={pipeline.recent_runs} onOpen={onOpenRun} />
            <p className="mt-1.5 flex items-center justify-between text-[11px] text-[color:var(--color-text-faint)]">
              <span>Last {pipeline.recent_runs.length} runs · taller is slower</span>
              {failedRuns > 0 && (
                <span className="inline-flex items-center gap-1">
                  <span aria-hidden="true" className="inline-block h-2 w-2 rounded-sm bg-negative" /> {failedRuns} failed
                </span>
              )}
            </p>
          </div>
        )}

        {finished && (
          <div className="space-y-2">
            <p className="text-[11px] font-medium text-[color:var(--color-text-muted)]">
              {running ? 'What the last finished run did to rows' : 'What the last run did to rows'}
            </p>
            <OutcomeCounts size="sm" withRead counts={{ read: finished.rows_read, inserted: finished.rows_inserted, updated: finished.rows_updated, deleted: finished.rows_deleted, unchanged: finished.rows_unchanged }} />
          </div>
        )}

        <dl className="grid grid-cols-3 gap-3 border-t border-[color:var(--color-border)] pt-3">
          <Stat label="30-day success" hint={`${pipeline.runs_30d} runs in the last 30 days`}>
            <span>{percent(pipeline.success_rate_30d)}</span>
            {pipeline.success_rate_30d !== null && (
              <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-positive-dim" aria-hidden="true">
                <span className="block h-full rounded-full bg-positive" style={{ width: `${Math.round(pipeline.success_rate_30d * 100)}%` }} />
              </span>
            )}
          </Stat>
          <Stat label="Usual full run" hint="Average of successful full runs in the last 30 days">
            {formatDuration(pipeline.avg_duration_ms_30d)}
          </Stat>
          <Stat label="Rows held" hint="Every version, in the tables the last full run loaded">
            {pipeline.footprint ? count(pipeline.footprint.rows) : '–'}
          </Stat>
        </dl>

        <p className="flex items-start gap-2 text-xs text-[color:var(--color-text-muted)]">
          <CalendarClock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            {pipeline.schedule}
            {pipeline.next_run && <span className="font-medium text-[color:var(--color-text)]"> · next check {until(pipeline.next_run, now)}</span>}
          </span>
        </p>
      </div>

      <footer className="mt-auto flex flex-wrap items-center gap-2 border-t border-[color:var(--color-border)] bg-[color:var(--color-surface-hover)]/60 px-5 py-3">
        {pipeline.can_run ? (
          <>
            <Button size="sm" disabled={running} onClick={() => onRun()}>
              <Play className="h-3.5 w-3.5" /> Run pipeline
            </Button>
            <div className="w-44">
              <SearchSelect
                value=""
                options={tables}
                placeholder={running ? 'Running…' : 'One table…'}
                allowEmpty={false}
                onChange={(table) => table && !running && onRun(table)}
              />
            </div>
          </>
        ) : (
          <p className="text-xs text-[color:var(--color-text-muted)]">You can see its runs but not start it.</p>
        )}
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onShowRuns}>
          <History className="h-3.5 w-3.5" /> Runs
        </Button>
      </footer>
    </article>
  )
}
