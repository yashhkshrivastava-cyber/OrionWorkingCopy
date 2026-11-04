import { Clock } from 'lucide-react'
import { clock, count, formatDuration, initials, OUTCOMES, startedBy } from '../../etl/format'
import { timeAgo } from '../../formatTime'
import type { EtlRecentRun, EtlRun, EtlStep } from '../../types'

/** A small filled circle that marks a kind of row. The word always sits beside it. */
export function Key({ color, className = '' }: { color: string; className?: string }) {
  return <span aria-hidden="true" className={`inline-block h-2 w-2 shrink-0 rounded-full ${className}`} style={{ background: color }} />
}

type Counts = { read?: number; inserted: number; updated: number; deleted: number; unchanged: number }

/**
 * What a run did to the rows, each count beside a coloured key and its name. A zero is shown quieter than a number,
 * so the eye lands on what actually changed.
 */
export function OutcomeCounts({ counts, withRead = false, size = 'md' }: { counts: Counts; withRead?: boolean; size?: 'sm' | 'md' }) {
  const text = size === 'sm' ? 'text-xs' : 'text-[13px]'
  return (
    <dl className={`flex flex-wrap items-center gap-x-4 gap-y-1.5 ${text}`}>
      {withRead && counts.read !== undefined && (
        <div className="flex items-baseline gap-1.5" title="Rows the source had: new, changed or the same.">
          <dt className="text-[color:var(--color-text-muted)]">Read</dt>
          <dd className="font-semibold tabular-nums text-[color:var(--color-text)]">{count(counts.read)}</dd>
        </div>
      )}
      {OUTCOMES.map((outcome) => {
        const value = counts[outcome.key]
        return (
          <div key={outcome.key} className="flex items-center gap-1.5" title={outcome.hint}>
            <Key color={outcome.color} />
            <dt className="text-[color:var(--color-text-muted)]">{outcome.label}</dt>
            <dd className={`font-semibold tabular-nums ${value === 0 ? 'text-[color:var(--color-text-faint)]' : 'text-[color:var(--color-text)]'}`}>
              {count(value)}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

/**
 * The last runs of a pipeline as bars, oldest to newest: taller is slower, a failed run is red, the latest is the accent.
 * Each bar opens its run. Empty slots keep the strip the same width before a pipeline has a full set of runs.
 */
export function RunBars({ runs, slots = 24, onOpen }: { runs: EtlRecentRun[]; slots?: number; onOpen: (id: number) => void }) {
  const longest = Math.max(1, ...runs.map((run) => run.duration_ms ?? 0))
  const padding = Math.max(0, slots - runs.length)
  const last = runs.length - 1
  return (
    <div className="flex h-12 items-end gap-[2px]" role="list" aria-label={`Last ${runs.length} runs, oldest first`}>
      {Array.from({ length: padding }).map((_, i) => (
        <span key={`empty-${i}`} aria-hidden="true" className="h-[3px] flex-1 rounded-sm bg-[color:var(--color-border)]" />
      ))}
      {runs.map((run, index) => {
        const failed = run.status === 'failed'
        const running = run.status === 'running'
        const height = failed || running ? Math.max(18, scale(run.duration_ms, longest)) : scale(run.duration_ms, longest)
        const color = failed ? 'var(--orion-negative)' : index === last || running ? 'var(--orion-accent)' : 'var(--etl-bar)'
        return (
          <div key={run.id} role="listitem" className="group relative flex h-full flex-1 items-end">
            <button
              type="button"
              onClick={() => onOpen(run.id)}
              aria-label={`Run ${run.id}, ${run.status}, ${formatDuration(run.duration_ms)}`}
              className={`w-full rounded-t-[4px] transition-opacity hover:opacity-80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--orion-accent)] ${running ? 'etl-pulse' : ''}`}
              style={{ height, background: color }}
            />
            <span
              role="tooltip"
              className="pointer-events-none invisible absolute bottom-full left-1/2 z-20 mb-2 w-max -translate-x-1/2 rounded-lg bg-[color:var(--color-text)] px-2.5 py-1.5 text-[11px] leading-snug text-[color:var(--color-bg)] opacity-0 shadow-raised transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
            >
              <span className="block font-semibold">
                Run #{run.id} · {formatDuration(run.duration_ms)}
              </span>
              <span className="block opacity-80">
                {timeAgo(run.started_timestamp)} · {run.status}
                {run.scope !== 'all' ? ` · only ${run.scope}` : ''}
              </span>
              <span className="block opacity-80">
                +{count(run.rows_inserted)} new · {count(run.rows_updated)} updated · {count(run.rows_deleted)} deleted
              </span>
            </span>
          </div>
        )
      })}
    </div>
  )
}

function scale(ms: number | null, longest: number): number {
  return Math.max(5, Math.round(((ms ?? 0) / longest) * 44))
}

/** One small segment per table of a running pipeline: done, loading now, waiting, failed. */
export function StepStrip({ steps }: { steps: Pick<EtlStep, 'name' | 'status'>[] }) {
  const paint: Record<EtlStep['status'], string> = {
    succeeded: 'bg-positive',
    running: 'bg-accent etl-pulse',
    pending: 'bg-[color:var(--color-border-strong)]/60',
    failed: 'bg-negative',
    skipped: 'bg-[color:var(--color-border)]',
  }
  return (
    <div className="flex h-2 gap-[2px]" role="progressbar" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={steps.filter((s) => s.status === 'succeeded').length} aria-label="Tables loaded">
      {steps.map((step) => (
        <span key={step.name} title={`${step.name}: ${step.status}`} className={`h-full flex-1 rounded-full ${paint[step.status]}`} />
      ))}
    </div>
  )
}

/** Who started a run: a person's initials, or a clock for the schedule. */
export function Who({ run, withTime = false }: { run: Pick<EtlRun, 'trigger' | 'started_by_name' | 'started_by' | 'started_timestamp'>; withTime?: boolean }) {
  const name = startedBy(run)
  const scheduled = run.trigger === 'scheduled'
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] font-bold ${
          scheduled ? 'bg-muted text-[color:var(--color-text-muted)]' : 'bg-accent-dim text-accent'
        }`}
      >
        {scheduled ? <Clock className="h-3 w-3" /> : initials(name)}
      </span>
      <span className="min-w-0 leading-tight">
        <span className="block truncate text-[13px] font-medium text-[color:var(--color-text)]">{name}</span>
        <span className="block text-[11px] text-[color:var(--color-text-muted)]">
          {scheduled ? 'Scheduled' : 'Manual'}
          {withTime ? ` · ${clock(run.started_timestamp)}` : ''}
        </span>
      </span>
    </span>
  )
}
