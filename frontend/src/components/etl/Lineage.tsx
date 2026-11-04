import { BookOpenText, ChevronRight, CircleAlert, CircleCheck, CircleDashed, Database, Lock, LoaderCircle, Warehouse, type LucideIcon } from 'lucide-react'
import { count, formatDuration } from '../../etl/format'
import { timeAgo } from '../../formatTime'
import type { EtlPipeline, EtlPipelineKey, EtlRunDetail } from '../../types'

type Node = { id: string; title: string; note: string; schema: string; icon: LucideIcon; target?: EtlPipelineKey }

const LANES: { group: string; tint: string; nodes: Node[]; edges: EtlPipelineKey[] }[] = [
  {
    group: 'Orion',
    tint: 'bg-accent-dim text-accent',
    nodes: [
      { id: 'orion_ods', title: 'Orion ODS', note: 'Operational records', schema: 'orion_ods', icon: Database },
      { id: 'orion_dw', title: 'Orion warehouse', note: 'History of every record', schema: 'orion_dw', icon: Warehouse, target: 'orion_dw' },
    ],
    edges: ['orion_dw'],
  },
  {
    group: 'Tally',
    tint: 'bg-violet-dim text-violet',
    nodes: [
      { id: 'tally', title: 'Tally Prime', note: 'XML server, port 9000', schema: 'live books', icon: BookOpenText },
      { id: 'tally_ods', title: 'Tally working copy', note: 'Latest masters and vouchers', schema: 'tally_ods', icon: Database, target: 'tally_ods' },
      { id: 'tally_dw', title: 'Tally warehouse', note: 'Versioned history', schema: 'tally_dw', icon: Warehouse, target: 'tally_dw' },
    ],
    edges: ['tally_ods', 'tally_dw'],
  },
]

function stateOf(pipeline: EtlPipeline | undefined): 'running' | 'failed' | 'ok' | 'never' | 'locked' {
  if (!pipeline) return 'locked'
  if (pipeline.running) return 'running'
  if (!pipeline.last_run) return 'never'
  return pipeline.last_run.status === 'failed' ? 'failed' : 'ok'
}

function Chip({ pipeline, progress, onSelect }: { pipeline?: EtlPipeline; progress?: EtlRunDetail | null; onSelect: () => void }) {
  const state = stateOf(pipeline)
  const done = progress ? progress.steps.filter((s) => s.status === 'succeeded').length : 0
  const body = {
    running: { Icon: LoaderCircle, spin: true, tone: 'text-warning', main: progress ? `Loading ${done} of ${progress.steps_total}` : 'Starting', sub: 'in progress' },
    failed: { Icon: CircleAlert, spin: false, tone: 'text-negative', main: 'Failed', sub: pipeline?.last_run ? timeAgo(pipeline.last_run.started_timestamp) : '' },
    ok: {
      Icon: CircleCheck,
      spin: false,
      tone: 'text-positive',
      main: pipeline?.last_run ? timeAgo(pipeline.last_run.started_timestamp) : '',
      sub: pipeline?.last_run ? formatDuration(pipeline.last_run.duration_ms) : '',
    },
    never: { Icon: CircleDashed, spin: false, tone: 'text-[color:var(--color-text-faint)]', main: 'Never run', sub: 'waiting for a first load' },
    locked: { Icon: Lock, spin: false, tone: 'text-[color:var(--color-text-faint)]', main: 'No access', sub: 'ask an admin' },
  }[state]
  const Icon = body.Icon
  const inner = (
    <>
      <Icon className={`h-4 w-4 shrink-0 ${body.tone} ${body.spin ? 'animate-spin' : ''}`} aria-hidden="true" />
      <span className="min-w-0 text-left leading-tight">
        <span className="block truncate text-xs font-semibold text-[color:var(--color-text)]">{body.main}</span>
        <span className="block truncate text-[11px] text-[color:var(--color-text-muted)]">{body.sub}</span>
      </span>
    </>
  )
  const box = 'relative z-10 flex max-w-full items-center gap-2 rounded-full border border-[color:var(--color-border)] bg-surface py-1.5 pl-2.5 pr-3.5 shadow-card'
  return state === 'locked' ? (
    <span className={`${box} opacity-70`}>{inner}</span>
  ) : (
    <button
      type="button"
      onClick={onSelect}
      title={`${pipeline?.label}: show its card`}
      className={`${box} interactive hover:border-[color:var(--color-border-strong)] hover:shadow-raised focus-visible:ring-2 focus-visible:ring-accent`}
    >
      {inner}
    </button>
  )
}

/** The route data takes from each source to each store, with how every hop last went. A running hop moves. */
export function Lineage({
  pipelines,
  progress,
  onSelect,
}: {
  pipelines: EtlPipeline[]
  progress: Record<string, EtlRunDetail>
  onSelect: (key: EtlPipelineKey) => void
}) {
  const byKey = new Map(pipelines.map((p) => [p.key, p]))
  const lanes = LANES.filter((lane) => lane.edges.some((key) => byKey.has(key)))

  return (
    <section className="panel px-5 py-4" aria-label="How data flows">
      <p className="eyebrow mb-3">How data flows</p>
      <div className="space-y-5">
        {lanes.map((lane) => (
          <div key={lane.group} className="flex flex-col items-stretch md:flex-row md:items-center">
            {lane.nodes.map((node, index) => {
              const owner = node.target ? byKey.get(node.target) : undefined
              const companies =
                node.id === 'tally' ? ((byKey.get('tally_ods')?.last_run?.source?.companies as string[] | undefined) ?? []) : []
              const edgeKey = lane.edges[index]
              const edge = edgeKey ? byKey.get(edgeKey) : undefined
              const state = stateOf(edge)
              return (
                <div key={node.id} className="contents">
                  <div className="flex items-center gap-3 rounded-xl border border-[color:var(--color-border)] bg-surface px-3.5 py-3 md:w-[13.5rem] md:shrink-0">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${lane.tint}`}>
                      <node.icon className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 leading-tight">
                      <span className="block truncate text-[13px] font-semibold text-[color:var(--color-text)]">{node.title}</span>
                      <span className="block truncate font-mono text-[11px] text-[color:var(--color-text-muted)]">{node.schema}</span>
                      <span className="mt-0.5 block truncate text-[11px] text-[color:var(--color-text-faint)]">
                        {owner?.footprint
                          ? `${count(owner.footprint.rows)} rows · ${owner.footprint.tables} tables`
                          : companies.length
                            ? companies.join(', ')
                            : node.note}
                      </span>
                    </span>
                  </div>
                  {index < lane.nodes.length - 1 && (
                    <div className="relative flex h-20 items-center justify-center md:h-auto md:min-h-14 md:flex-1 md:px-2">
                      <span className="etl-line absolute inset-0" data-state={state === 'running' ? 'running' : state === 'failed' ? 'failed' : 'idle'} aria-hidden="true" />
                      <ChevronRight
                        aria-hidden="true"
                        className="absolute bottom-0 left-1/2 h-4 w-4 -translate-x-1/2 rotate-90 text-[color:var(--color-text-faint)] md:bottom-auto md:left-auto md:right-0 md:top-1/2 md:-translate-y-1/2 md:translate-x-0 md:rotate-0"
                      />
                      <Chip pipeline={edge} progress={edgeKey ? progress[edgeKey] : null} onSelect={() => edgeKey && onSelect(edgeKey)} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </section>
  )
}
