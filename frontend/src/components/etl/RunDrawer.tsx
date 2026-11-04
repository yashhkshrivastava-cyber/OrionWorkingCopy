import { useState } from 'react'
import { ChevronDown, ChevronRight, CircleAlert, CircleCheck, Copy, LoaderCircle, Play } from 'lucide-react'
import { api } from '../../api/client'
import { changeSentence, clock, count, describeSource, formatDuration, OUTCOMES } from '../../etl/format'
import { formatDateTime } from '../../formatTime'
import type { EtlRunDetail, EtlStep } from '../../types'
import { AiButton, AiNotice, AiProvenance, useAiTask } from '../ai/AiTask'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Drawer } from '../ui/Drawer'
import { Key, OutcomeCounts, Who } from './primitives'
import { StatusBadge } from './StatusBadge'

const KIND: Record<string, string> = { generated: 'Calendar', dimension: 'Dimension', fact: 'Fact', master: 'Master', transaction: 'Transaction' }

function Fact({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`min-w-0 ${wide ? 'col-span-2' : ''}`}>
      <dt className="text-[11px] font-medium text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className="mt-0.5 break-words text-[13px] font-medium text-[color:var(--color-text)]">{children}</dd>
    </div>
  )
}

/**
 * A plain-English reading of why a load failed: what happened, the likely cause and what to try. The AI is given only the
 * run's name and its error messages (never table contents), and what it says is advice, not an action.
 */
function ExplainFailure({ runId }: { runId: number }) {
  const task = useAiTask<{ text: string }>()
  return (
    <div className="mt-2 space-y-2">
      <AiButton
        disabled={task.busy}
        title="Explains the error in plain words. Only the error messages are sent, no data."
        onClick={() => task.run((cloudOnce) => api.etlExplainAi(runId, cloudOnce))}
      >
        Explain this failure
      </AiButton>
      <AiNotice task={task} />
      {task.phase === 'ok' && task.result && (
        <div className="space-y-1.5 rounded-lg bg-muted/60 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <p className="eyebrow">In plain words</p>
            <AiProvenance where={task.result.where} provider={task.result.provider} />
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{task.result.text}</p>
          <p className="text-[11px] text-[color:var(--color-text-faint)]">An AI reading of the error. Check it before acting on it.</p>
        </div>
      )}
    </div>
  )
}

/** The one-line answer to "how did it go?" that heads the drawer. */
function verdict(run: EtlRunDetail): { tone: 'ok' | 'running' | 'failed'; title: string; detail: string } {
  const counts = { inserted: run.rows_inserted, updated: run.rows_updated, deleted: run.rows_deleted }
  const loaded = run.steps_succeeded
  const noun = (n: number) => `${n} ${n === 1 ? 'table' : 'tables'}`
  if (run.status === 'running') {
    return { tone: 'running', title: `Loading… ${loaded} of ${run.steps_total} tables`, detail: `${formatDuration(run.duration_ms)} so far` }
  }
  if (run.status === 'failed') {
    return loaded === 0 && run.steps_failed === 0
      ? { tone: 'failed', title: 'It could not start', detail: `Nothing was loaded. ${noun(run.steps_skipped)} skipped.` }
      : {
          tone: 'failed',
          title: `Stopped after ${noun(loaded)}`,
          detail: `${run.steps_failed ? `${noun(run.steps_failed)} failed, ` : ''}${noun(run.steps_skipped)} skipped. What loaded first was kept.`,
        }
  }
  return { tone: 'ok', title: `Loaded ${noun(loaded)} in ${formatDuration(run.duration_ms)}`, detail: `${changeSentence(counts)}.` }
}

function StepRows({ run }: { run: EtlRunDetail }) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const startMs = new Date(run.started_timestamp).getTime()
  const total = Math.max(1, run.duration_ms ?? Date.now() - startMs)
  const slowest = Math.max(0, ...run.steps.filter((s) => s.status === 'succeeded').map((s) => s.duration_ms ?? 0))
  const toggle = (seq: number) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(seq)) next.delete(seq)
      else next.add(seq)
      return next
    })
  const head = 'px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-[color:var(--color-text-faint)]'

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead>
          <tr className="text-left">
            <th className={head}>Table</th>
            <th className={`${head} w-[34%]`}>Timeline</th>
            <th className={`${head} text-right`}>Took</th>
            <th className={`${head} text-right`}>
              <span className="inline-flex items-center gap-1.5"><Key color="var(--etl-inserted)" />Ins</span>
            </th>
            <th className={`${head} text-right`}>
              <span className="inline-flex items-center gap-1.5"><Key color="var(--etl-updated)" />Upd</span>
            </th>
            <th className={`${head} text-right`}>
              <span className="inline-flex items-center gap-1.5"><Key color="var(--etl-deleted)" />Del</span>
            </th>
            <th className={`${head} text-right`}>Same</th>
          </tr>
        </thead>
        <tbody>
          {run.steps.map((step) => {
            const expanded = open.has(step.seq)
            const offset = step.started_timestamp ? Math.max(0, new Date(step.started_timestamp).getTime() - startMs) : null
            const width = step.duration_ms ?? 0
            const color =
              step.status === 'failed' ? 'var(--orion-negative)' : step.status === 'running' ? 'var(--orion-accent)' : step.status === 'succeeded' && width === slowest && slowest > 0 ? 'var(--orion-accent)' : 'var(--etl-bar)'
            return (
              <StepRow
                key={step.seq}
                step={step}
                expanded={expanded}
                onToggle={() => toggle(step.seq)}
                bar={
                  offset === null ? null : (
                    <span
                      className={`absolute top-1/2 h-2.5 -translate-y-1/2 rounded-[4px] ${step.status === 'running' ? 'etl-pulse' : ''}`}
                      style={{ left: `${Math.min(99, (offset / total) * 100)}%`, width: `max(4px, ${Math.min(100, (width / total) * 100)}%)`, background: color }}
                      title={`${step.name}: starts ${formatDuration(offset)} in, takes ${formatDuration(step.duration_ms)}`}
                    />
                  )
                }
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function StepRow({ step, expanded, onToggle, bar }: { step: EtlStep; expanded: boolean; onToggle: () => void; bar: React.ReactNode }) {
  const muted = step.status === 'skipped' || step.status === 'pending'
  const Chevron = expanded ? ChevronDown : ChevronRight
  const num = (value: number) => (
    <span className={muted || value === 0 ? 'text-[color:var(--color-text-faint)]' : 'font-semibold text-[color:var(--color-text)]'}>{muted ? '–' : count(value)}</span>
  )
  return (
    <>
      <tr className="border-t border-[color:var(--color-border)]">
        <td className="px-3 py-2">
          <button type="button" onClick={onToggle} aria-expanded={expanded} className="flex items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <Chevron className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
            <span className="min-w-0">
              <span className={`block truncate text-[13px] font-medium ${muted ? 'text-[color:var(--color-text-muted)]' : 'text-[color:var(--color-text)]'}`}>{step.name}</span>
              <span className="mt-0.5 flex items-center gap-1.5">
                <StatusBadge status={step.status} size="sm" />
                <span className="text-[11px] text-[color:var(--color-text-faint)]">{KIND[step.kind ?? ''] ?? step.kind}</span>
              </span>
            </span>
          </button>
        </td>
        <td className="px-3 py-2">
          <span className="relative block h-6 rounded-md bg-muted/60" aria-hidden={bar === null}>
            {bar}
          </span>
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-right text-[13px] tabular-nums text-[color:var(--color-text)]">{formatDuration(step.duration_ms)}</td>
        <td className="px-3 py-2 text-right tabular-nums">{num(step.rows_inserted)}</td>
        <td className="px-3 py-2 text-right tabular-nums">{num(step.rows_updated)}</td>
        <td className="px-3 py-2 text-right tabular-nums">{num(step.rows_deleted)}</td>
        <td className="px-3 py-2 text-right tabular-nums text-[color:var(--color-text-muted)]">{muted ? '–' : count(step.rows_unchanged)}</td>
      </tr>
      {expanded && (
        <tr className="bg-[color:var(--color-surface-hover)]/60">
          <td colSpan={7} className="px-3 py-3 pl-10">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
              <Fact label="Target table">
                <span className="font-mono">{step.target_table ?? '–'}</span>
              </Fact>
              <Fact label="Rows in target">
                {step.target_rows_before === null && step.target_rows_after === null ? '–' : `${count(step.target_rows_before)} → ${count(step.target_rows_after)}`}
              </Fact>
              {step.stats?.current_rows !== undefined && <Fact label="Current versions">{count(step.stats.current_rows)}</Fact>}
              <Fact label="Rows read">{count(step.rows_read)}</Fact>
              <Fact label="Started">{step.started_timestamp ? `${clock(step.started_timestamp)}` : '–'}</Fact>
              <Fact label="Finished">{step.finished_timestamp ? `${clock(step.finished_timestamp)}` : '–'}</Fact>
            </dl>
            {step.error && <p className="mt-3 rounded-lg bg-negative-dim px-3 py-2 text-xs text-negative">{step.error}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

/**
 * One run in full. It leads with how it went, then what it did to the rows, who and what and where, and the timeline of
 * every table. A run still going refreshes itself.
 */
export function RunDrawer({
  open,
  run,
  error,
  pipelineLabel,
  canRun,
  onRunAgain,
  onClose,
}: {
  open: boolean
  run: EtlRunDetail | null
  error: string
  pipelineLabel: (key: string) => string
  canRun: boolean
  onRunAgain: (pipeline: string, table?: string) => void
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  const v = run ? verdict(run) : null
  const VerdictIcon = v?.tone === 'failed' ? CircleAlert : v?.tone === 'running' ? LoaderCircle : CircleCheck
  const tone = {
    ok: 'border-positive/25 bg-positive-dim text-positive',
    running: 'border-warning/25 bg-warning-dim text-warning',
    failed: 'border-negative/25 bg-negative-dim text-negative',
  }

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* the fingerprint is still on screen to select */
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={run ? `Run #${run.id}` : 'Run'}
      badge={run ? <StatusBadge status={run.status} /> : null}
      subtitle={run ? `${pipelineLabel(run.pipeline)}${run.scope !== 'all' ? `, only ${run.scope}` : ''}` : undefined}
      footer={
        <>
          {run && canRun && run.status !== 'running' && (
            <Button variant="secondary" onClick={() => onRunAgain(run.pipeline, run.scope === 'all' ? undefined : run.scope)}>
              <Play className="h-4 w-4" /> Run again
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error && <Alert variant="error">{error}</Alert>}
        {!run && !error && <div className="shimmer h-56 rounded-xl bg-muted" aria-busy="true" />}

        {run && v && (
          <>
            <div className={`flex items-start gap-3 rounded-xl border px-4 py-3.5 ${tone[v.tone]}`}>
              <VerdictIcon className={`mt-0.5 h-5 w-5 shrink-0 ${v.tone === 'running' ? 'animate-spin' : ''}`} aria-hidden="true" />
              <div className="min-w-0">
                <p className="font-display text-base font-bold tracking-tight text-[color:var(--color-text)]">{v.title}</p>
                <p className="mt-0.5 text-sm text-[color:var(--color-text-muted)]">{v.detail}</p>
              </div>
            </div>

            {run.error && (
              <div className="rounded-xl border border-negative/25 bg-surface px-4 py-3">
                <p className="eyebrow !text-negative">What went wrong</p>
                <p className="mt-1.5 break-words text-sm text-[color:var(--color-text)]">{run.error}</p>
                <ExplainFailure key={run.id} runId={run.id} />
              </div>
            )}
            {!run.error && run.steps_failed > 0 && (
              <div className="rounded-xl border border-negative/25 bg-surface px-4 py-3">
                <p className="eyebrow !text-negative">
                  {run.steps_failed === 1 ? 'One table failed' : `${run.steps_failed} tables failed`}
                </p>
                <ExplainFailure key={run.id} runId={run.id} />
              </div>
            )}

            <section className="panel px-5 py-4">
              <p className="eyebrow mb-3">What it did to the rows</p>
              <OutcomeCounts
                withRead
                counts={{ read: run.rows_read, inserted: run.rows_inserted, updated: run.rows_updated, deleted: run.rows_deleted, unchanged: run.rows_unchanged }}
              />
              <details className="mt-3 text-xs text-[color:var(--color-text-muted)]">
                <summary className="cursor-pointer font-medium text-accent hover:underline">What do these mean?</summary>
                <ul className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
                  {OUTCOMES.map((o) => (
                    <li key={o.key} className="flex items-start gap-1.5">
                      <Key color={o.color} className="mt-1" />
                      <span>
                        <span className="font-medium text-[color:var(--color-text)]">{o.label}.</span> {o.hint}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] text-[color:var(--color-text-faint)]">The calendar table is built by the load, not read from a source, so it is left out of these totals.</p>
              </details>
            </section>

            <section className="panel px-5 py-4">
              <p className="eyebrow mb-3">Details</p>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
                <Fact label="Started by">
                  <Who run={run} />
                </Fact>
                <Fact label="Started">{formatDateTime(run.started_timestamp)}</Fact>
                <Fact label="Finished">{run.finished_timestamp ? formatDateTime(run.finished_timestamp) : 'Still running'}</Fact>
                <Fact label="Duration">{formatDuration(run.duration_ms)}</Fact>
                <Fact label="Scope">{run.scope === 'all' ? 'Every table' : run.scope}</Fact>
                <Fact label="Ran on">
                  {run.runner_host ?? 'Unknown'}
                  {run.app_env ? ` · ${run.app_env}` : ''}
                </Fact>
                <Fact label="Target">
                  <span className="font-mono">{run.target ?? ''}</span>
                </Fact>
                <Fact label="Read from" wide>
                  {describeSource(run.source)}
                </Fact>
                {run.source_fingerprint && (
                  <Fact label="Source fingerprint" wide>
                    <span className="flex items-center gap-2">
                      <span className="break-all font-mono text-xs text-[color:var(--color-text-muted)]">{run.source_fingerprint}</span>
                      <button
                        type="button"
                        onClick={() => copy(run.source_fingerprint ?? '')}
                        className="interactive shrink-0 rounded-md p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
                        aria-label="Copy fingerprint"
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                      {copied && <span className="text-[11px] text-positive">Copied</span>}
                    </span>
                  </Fact>
                )}
              </dl>
            </section>

            <section className="panel overflow-hidden">
              <div className="flex items-baseline justify-between gap-3 px-5 pb-1 pt-4">
                <p className="eyebrow">Tables, in the order they loaded</p>
                <p className="text-[11px] text-[color:var(--color-text-faint)]">The slowest is highlighted. Open a table for more.</p>
              </div>
              <StepRows run={run} />
            </section>
          </>
        )}
      </div>
    </Drawer>
  )
}
