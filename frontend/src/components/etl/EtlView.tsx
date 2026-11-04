import { CircleAlert, CircleCheck, CircleDashed, LoaderCircle, Radio, X } from 'lucide-react'
import { healthSummary } from '../../etl/format'
import { timeAgo } from '../../formatTime'
import type { EtlPipeline, EtlPipelineKey, EtlRun, EtlRunDetail } from '../../types'
import { WriteGate } from '../data/WriteGate'
import { Lineage } from './Lineage'
import { BackupPanel } from './BackupPanel'
import { PipelineCard } from './PipelineCard'
import { RunDrawer } from './RunDrawer'
import { RunTable, type RunFilters } from './RunTable'

export type TallyNote = { running: boolean; company?: string | null; warning?: string | null; error?: string | null }

const WHAT_IT_WRITES: Record<string, string> = {
  orion_dw:
    'This loads the Orion warehouse from operational data. New rows are inserted, changed rows get a new version, and rows deleted from operational data are marked expired.',
  tally_ods:
    'This reads the open company from Tally Prime and replaces the Tally working copy with it. New rows are inserted, changed rows are updated in place, and rows Tally no longer has are removed. Tally Prime must be open with the company loaded.',
  tally_dw:
    'This loads the Tally warehouse from the Tally working copy. New rows are inserted, changed rows get a new version, and rows no longer in the working copy are marked expired. Load the working copy first if Tally has changed.',
}

const TONE = {
  ok: { box: 'border-positive/30 bg-positive-dim text-[color:var(--color-text)]', icon: CircleCheck, color: 'text-positive' },
  running: { box: 'border-warning/30 bg-warning-dim text-[color:var(--color-text)]', icon: LoaderCircle, color: 'text-warning' },
  failed: { box: 'border-negative/30 bg-negative-dim text-[color:var(--color-text)]', icon: CircleAlert, color: 'text-negative' },
  idle: { box: 'border-[color:var(--color-border)] bg-muted text-[color:var(--color-text-muted)]', icon: CircleDashed, color: 'text-[color:var(--color-text-faint)]' },
}

export interface EtlViewProps {
  pipelines: EtlPipeline[] | null
  progress: Record<string, EtlRunDetail>
  runs: EtlRun[] | null
  total: number
  filters: RunFilters
  moreLoading: boolean
  tally: TallyNote | null
  /** When the data on screen was fetched, in ms, to say how fresh it is. */
  updatedAt: number | null
  now: number
  error: string
  started: number | null
  selectedPipeline: string
  openRun: { id: number | null; detail: EtlRunDetail | null; error: string }
  confirm: { pipeline: EtlPipeline; table?: string } | null
  onFilters: (next: RunFilters) => void
  onMore: () => void
  onOpenRun: (id: number | null) => void
  onRun: (pipeline: EtlPipeline, table?: string) => void
  onConfirm: () => void
  onCancelConfirm: () => void
  onDismissError: () => void
  onDismissStarted: () => void
  onSelectPipeline: (key: EtlPipelineKey) => void
}

/** The ETL page, drawn from what it is given. The page fetches and polls; this only shows. */
export function EtlView(props: EtlViewProps) {
  const { pipelines, progress, now } = props
  const ago = (iso: string) => timeAgo(iso, now)
  const health = pipelines && pipelines.length ? healthSummary(pipelines, ago) : null
  const tone = TONE[health?.tone ?? 'idle']
  const ToneIcon = tone.icon
  const labels = (pipelines ?? []).map((p) => ({ key: p.key, label: p.label }))
  const labelOf = (key: string) => labels.find((p) => p.key === key)?.label ?? key
  const anyRunning = (pipelines ?? []).some((p) => p.running)
  const runPipeline = pipelines?.find((p) => p.key === props.openRun.detail?.pipeline)

  return (
    <div className="etl-root space-y-5 pb-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <p className="eyebrow">Data</p>
          <h1 className="t-h1 text-[color:var(--color-text)]">ETL pipelines</h1>
          <p className="mt-1 max-w-2xl text-sm text-[color:var(--color-text-muted)]">
            How data moves into the warehouses. Every run is recorded here, whoever or whatever started it.
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          {health && (
            <p
              className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium ${tone.box}`}
              role="status"
              aria-live="polite"
            >
              <ToneIcon className={`h-4 w-4 shrink-0 ${tone.color} ${health.tone === 'running' ? 'animate-spin' : ''}`} aria-hidden="true" />
              {health.text}
            </p>
          )}
          {props.updatedAt !== null && (
            <p className="flex items-center gap-1.5 text-[11px] text-[color:var(--color-text-faint)]">
              <Radio className={`h-3 w-3 ${anyRunning ? 'etl-pulse text-warning' : 'text-positive'}`} aria-hidden="true" />
              {anyRunning ? 'Live, checking every 2 s' : 'Live'} · updated {timeAgo(new Date(props.updatedAt).toISOString(), now)}
            </p>
          )}
        </div>
      </header>

      {props.error && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-negative/30 bg-negative-dim px-4 py-3 text-sm">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-negative" aria-hidden="true" />
          <span className="min-w-0 flex-1 break-words text-[color:var(--color-text)]">{props.error}</span>
          <button type="button" onClick={props.onDismissError} aria-label="Dismiss" className="shrink-0 text-[color:var(--color-text-faint)] hover:text-[color:var(--color-text)]">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {props.started !== null && (
        <div role="status" className="flex items-start gap-3 rounded-xl border border-positive/30 bg-positive-dim px-4 py-3 text-sm">
          <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-positive" aria-hidden="true" />
          <span className="min-w-0 flex-1 text-[color:var(--color-text)]">
            Run #{props.started} has started. It runs on the server, so you can leave this page.{' '}
            <button type="button" className="font-semibold underline" onClick={() => props.onOpenRun(props.started)}>
              Watch it
            </button>
          </span>
          <button type="button" onClick={props.onDismissStarted} aria-label="Dismiss" className="shrink-0 text-[color:var(--color-text-faint)] hover:text-[color:var(--color-text)]">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {pipelines === null ? (
        <>
          <div className="shimmer h-44 rounded-2xl bg-muted" aria-busy="true" />
          <div className="grid gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="shimmer h-[34rem] rounded-2xl bg-muted" aria-busy="true" />
            ))}
          </div>
        </>
      ) : pipelines.length === 0 ? (
        <div className="panel px-6 py-12 text-center">
          <p className="text-sm font-semibold text-[color:var(--color-text)]">No pipelines to show</p>
          <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">Ask an admin for ETL access.</p>
        </div>
      ) : (
        <>
          <Lineage pipelines={pipelines} progress={progress} onSelect={props.onSelectPipeline} />

          <div className="stagger-in grid gap-4 lg:grid-cols-3">
            {pipelines.map((pipeline) => (
              <PipelineCard
                key={pipeline.key}
                pipeline={pipeline}
                progress={progress[pipeline.key]}
                selected={props.selectedPipeline === pipeline.key}
                now={now}
                note={
                  pipeline.key === 'tally_ods' && props.tally && (props.tally.running || pipeline.last_run?.status !== 'failed') ? (
                    <p
                      className={`rounded-lg px-3 py-2 text-xs ${
                        props.tally.running ? 'bg-positive-dim text-[color:var(--color-text)]' : 'bg-warning-dim text-[color:var(--color-text)]'
                      }`}
                    >
                      <span className="font-semibold">{props.tally.running ? 'Tally Prime is reachable' : 'Tally Prime is not reachable'}</span>
                      {props.tally.running && props.tally.company ? `, company ${props.tally.company}` : ''}
                      {!props.tally.running && props.tally.error ? `. ${props.tally.error}` : ''}
                      {props.tally.warning ? ` ${props.tally.warning}` : ''}
                    </p>
                  ) : null
                }
                onRun={(table) => props.onRun(pipeline, table)}
                onShowRuns={() => props.onFilters({ ...props.filters, pipeline: pipeline.key })}
                onOpenRun={(id) => props.onOpenRun(id)}
              />
            ))}
          </div>
        </>
      )}

      <BackupPanel now={now} />

      <RunTable
        runs={props.runs}
        total={props.total}
        filters={props.filters}
        pipelines={labels}
        loading={props.moreLoading}
        onFilters={props.onFilters}
        onOpen={(id) => props.onOpenRun(id)}
        onMore={props.onMore}
      />

      <RunDrawer
        open={props.openRun.id !== null}
        run={props.openRun.detail}
        error={props.openRun.error}
        pipelineLabel={labelOf}
        canRun={Boolean(runPipeline?.can_run)}
        onRunAgain={(key, table) => {
          const pipeline = pipelines?.find((p) => p.key === key)
          if (pipeline) props.onRun(pipeline, table)
        }}
        onClose={() => props.onOpenRun(null)}
      />

      <WriteGate
        open={props.confirm !== null}
        title={props.confirm?.table ? `Run ${props.confirm.table}` : `Run ${props.confirm?.pipeline.label ?? ''}`}
        body={`${props.confirm ? WHAT_IT_WRITES[props.confirm.pipeline.key] ?? '' : ''}${
          props.confirm?.table ? ` Only ${props.confirm.table}${props.confirm.pipeline.key === 'tally_ods' ? ', and what it needs first,' : ''} will be loaded.` : ''
        }`}
        confirmLabel={`I understand this writes to ${props.confirm?.pipeline.target ?? 'the target'}`}
        continueLabel="Start run"
        onCancel={props.onCancelConfirm}
        onContinue={props.onConfirm}
      />
    </div>
  )
}
