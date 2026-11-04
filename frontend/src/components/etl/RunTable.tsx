import { Fragment } from 'react'
import { ChevronRight, Inbox } from 'lucide-react'
import { clock, count, dayLabel, formatDuration, OUTCOMES } from '../../etl/format'
import { timeAgo } from '../../formatTime'
import type { EtlRun } from '../../types'
import { Button } from '../ui/Button'
import { Segmented } from '../ui/Segmented'
import { Key, Who } from './primitives'
import { StatusBadge } from './StatusBadge'

export interface RunFilters {
  pipeline: string
  status: string
  trigger: string
}

const RAIL: Record<EtlRun['status'], string> = {
  succeeded: 'bg-positive',
  failed: 'bg-negative',
  running: 'bg-warning etl-pulse',
}

function Count({ value }: { value: number }) {
  return <span className={value === 0 ? 'text-[color:var(--color-text-faint)]' : 'font-semibold text-[color:var(--color-text)]'}>{count(value)}</span>
}

/** Every run, newest first and grouped by day. A row opens that run. */
export function RunTable({
  runs,
  total,
  filters,
  pipelines,
  loading,
  onFilters,
  onOpen,
  onMore,
}: {
  runs: EtlRun[] | null
  total: number
  filters: RunFilters
  pipelines: { key: string; label: string }[]
  loading: boolean
  onFilters: (next: RunFilters) => void
  onOpen: (id: number) => void
  onMore: () => void
}) {
  const label = (key: string) => pipelines.find((p) => p.key === key)?.label ?? key
  const longest = Math.max(1, ...(runs ?? []).map((run) => run.duration_ms ?? 0))
  const head = 'px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-faint)]'
  const filtered = Boolean(filters.pipeline || filters.status || filters.trigger)

  return (
    <section className="panel overflow-hidden" aria-label="Run history">
      <header className="space-y-3 border-b border-[color:var(--color-border)] px-5 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h3 className="t-h3 text-[color:var(--color-text)]">Activity</h3>
            <p className="text-xs text-[color:var(--color-text-muted)]" aria-live="polite">
              {runs === null ? 'Loading…' : `${count(total)} ${total === 1 ? 'run' : 'runs'}${filtered ? ' match' : ''}. Open one to see every table.`}
            </p>
          </div>
          {filtered && (
            <button type="button" className="text-xs font-medium text-accent hover:underline" onClick={() => onFilters({ pipeline: '', status: '', trigger: '' })}>
              Clear filters
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Segmented
            label="Pipeline"
            value={filters.pipeline}
            onChange={(pipeline) => onFilters({ ...filters, pipeline })}
            options={[{ id: '', label: 'All pipelines' }, ...pipelines.map((p) => ({ id: p.key, label: p.label }))]}
          />
          <Segmented
            label="Status"
            value={filters.status}
            onChange={(status) => onFilters({ ...filters, status })}
            options={[
              { id: '', label: 'Any status' },
              { id: 'succeeded', label: 'Succeeded' },
              { id: 'failed', label: 'Failed' },
              { id: 'running', label: 'Running' },
            ]}
          />
          <Segmented
            label="Trigger"
            value={filters.trigger}
            onChange={(trigger) => onFilters({ ...filters, trigger })}
            options={[
              { id: '', label: 'Any trigger' },
              { id: 'manual', label: 'Manual' },
              { id: 'scheduled', label: 'Scheduled' },
            ]}
          />
        </div>
      </header>

      {runs === null ? (
        <div className="shimmer m-5 h-48 rounded-lg bg-muted" aria-busy="true" />
      ) : runs.length === 0 ? (
        <div className="flex flex-col items-center px-6 py-14 text-center">
          <span className="grid h-11 w-11 place-items-center rounded-full bg-muted text-[color:var(--color-text-faint)]">
            <Inbox className="h-5 w-5" aria-hidden="true" />
          </span>
          <p className="mt-3 text-sm font-semibold text-[color:var(--color-text)]">{filtered ? 'No run matches these filters' : 'Nothing has run yet'}</p>
          <p className="mt-1 max-w-sm text-sm text-[color:var(--color-text-muted)]">
            {filtered ? 'Try another pipeline or status.' : 'Runs appear here the moment a pipeline starts, whether a person or its schedule started it.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] text-sm">
            <thead>
              <tr className="text-left">
                <th className={`${head} w-1.5 p-0`} aria-label="State" />
                <th className={head}>Pipeline</th>
                <th className={head}>When</th>
                <th className={head}>Took</th>
                <th className={head}>Started by</th>
                <th className={`${head} text-right`}>
                  <span className="inline-flex items-center gap-1.5"><Key color="var(--etl-inserted)" />Inserted</span>
                </th>
                <th className={`${head} text-right`}>
                  <span className="inline-flex items-center gap-1.5"><Key color="var(--etl-updated)" />Updated</span>
                </th>
                <th className={`${head} text-right`}>
                  <span className="inline-flex items-center gap-1.5"><Key color="var(--etl-deleted)" />Deleted</span>
                </th>
                <th className={`${head} text-right`} title={OUTCOMES[3].hint}>
                  Unchanged
                </th>
                <th className={`${head} text-right`}>Tables</th>
                <th className={head} aria-label="Open" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run, index) => {
                const day = dayLabel(run.started_timestamp)
                const newDay = index === 0 || dayLabel(runs[index - 1].started_timestamp) !== day
                return (
                  <Fragment key={run.id}>
                    {newDay && (
                      <tr>
                        <td colSpan={11} className="bg-[color:var(--color-surface-hover)]/70 px-5 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-muted)]">
                          {day}
                        </td>
                      </tr>
                    )}
                    <tr
                      tabIndex={0}
                      onClick={() => onOpen(run.id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') onOpen(run.id)
                      }}
                      title="Open this run"
                      className="group cursor-pointer border-t border-[color:var(--color-border)] transition-colors hover:bg-[color:var(--color-surface-hover)] focus-visible:bg-[color:var(--color-surface-hover)] focus-visible:outline-none"
                    >
                      <td className="p-0">
                        <span aria-hidden="true" className={`block h-12 w-1.5 ${RAIL[run.status]}`} />
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="block font-medium text-[color:var(--color-text)]">{label(run.pipeline)}</span>
                        <span className="mt-0.5 flex items-center gap-1.5">
                          <StatusBadge status={run.status} size="sm" />
                          <span className="text-[11px] text-[color:var(--color-text-muted)]">
                            #{run.id}
                            {run.scope !== 'all' ? ` · only ${run.scope}` : ''}
                          </span>
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5">
                        <span className="block text-[13px] font-medium text-[color:var(--color-text)]">{timeAgo(run.started_timestamp)}</span>
                        <span className="block text-[11px] text-[color:var(--color-text-muted)]">{clock(run.started_timestamp)}</span>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="block whitespace-nowrap text-[13px] tabular-nums text-[color:var(--color-text)]">{formatDuration(run.duration_ms)}</span>
                        <span aria-hidden="true" className="mt-1 block h-1 w-20 rounded-full bg-muted">
                          <span
                            className={`block h-full rounded-full ${run.status === 'failed' ? 'bg-negative' : 'bg-[color:var(--etl-bar-hover)]'}`}
                            style={{ width: `${Math.max(6, Math.round(((run.duration_ms ?? 0) / longest) * 100))}%` }}
                          />
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <Who run={run} />
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums"><Count value={run.rows_inserted} /></td>
                      <td className="px-3 py-2.5 text-right tabular-nums"><Count value={run.rows_updated} /></td>
                      <td className="px-3 py-2.5 text-right tabular-nums"><Count value={run.rows_deleted} /></td>
                      <td className="px-3 py-2.5 text-right tabular-nums text-[color:var(--color-text-muted)]">{count(run.rows_unchanged)}</td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-[color:var(--color-text-muted)]">
                        <span className={run.steps_failed ? 'font-semibold text-negative' : ''}>
                          {run.steps_succeeded}/{run.steps_total}
                        </span>
                      </td>
                      <td className="pr-4 text-right">
                        <ChevronRight className="inline h-4 w-4 text-[color:var(--color-text-faint)] transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                      </td>
                    </tr>
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {runs !== null && runs.length < total && (
        <div className="border-t border-[color:var(--color-border)] px-5 py-3 text-center">
          <Button variant="secondary" size="sm" onClick={onMore} loading={loading}>
            Show older runs ({count(total - runs.length)} more)
          </Button>
        </div>
      )}
    </section>
  )
}
