import { lazy, Suspense, useState } from 'react'
import { TabLink } from '../ui/TabLink'
import { ArrowDownRight, ArrowUpRight, BellRing, Download, FileSpreadsheet, FileText, ListChecks } from 'lucide-react'
import { count, inr } from '../dashboard/format'
import { Frame } from './Frame'
import { BillNumber } from '../billing/BillNumber'
import type { AiBlock } from '../../types'

/*
 * The things an answer can show. Each is made by the server from real data and is only drawn here: the model chooses
 * where a block goes in its answer, never what is in it.
 */

type Block<K extends AiBlock['kind']> = Extract<AiBlock, { kind: K }>

const ChartBlock = lazy(() => import('./ChartBlock').then((module) => ({ default: module.ChartBlock })))

// ------------------------------------------------------------------------------------------- metric cards

const TONE = {
  positive: 'bg-positive-dim text-positive',
  negative: 'bg-negative-dim text-negative',
  neutral: 'bg-muted text-[color:var(--color-text-muted)]',
} as const

export function MetricsBlock({ block }: { block: Block<'metrics'> }) {
  return (
    <Frame title={block.title} link={block.link}>
      <div className="grid grid-cols-2 gap-2 p-3 @[34rem]:grid-cols-3">
        {block.items.map((item) => {
          const delta = item.delta
          const down = delta?.startsWith('-')
          const up = delta?.startsWith('+')
          return (
            <div key={item.label} className="min-w-0 rounded-lg bg-muted/60 px-3 py-2.5">
              <p className="line-clamp-2 text-[11px] font-medium leading-tight text-[color:var(--color-text-muted)]">{item.label}</p>
              <p className="t-num mt-0.5 truncate text-lg font-semibold leading-tight text-[color:var(--color-text)]">{item.value}</p>
              {delta && (
                <span className={`mt-1 inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${TONE[item.tone ?? 'neutral']}`}>
                  {up && <ArrowUpRight className="h-3 w-3" aria-hidden="true" />}
                  {down && <ArrowDownRight className="h-3 w-3" aria-hidden="true" />}
                  {delta}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </Frame>
  )
}

// ------------------------------------------------------------------------------------------------ tables

function cell(value: unknown, format?: string | null): string {
  if (value === null || value === undefined || value === '') return '–'
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (format === 'inr') return inr(value)
    if (format === 'pct') return `${value.toFixed(1)}%`
    return count(value)
  }
  return String(value)
}

const FIRST = 8

export function TableBlock({ block }: { block: Block<'table'> }) {
  const [all, setAll] = useState(false)
  const rows = all ? block.rows : block.rows.slice(0, FIRST)
  return (
    <Frame title={block.title} link={block.link}>
      <div className="overflow-x-auto px-1 pb-1 pt-2">
        <table className="w-full min-w-[18rem] border-collapse text-left text-[13px]">
          <thead>
            <tr className="text-[11px] text-[color:var(--color-text-muted)]">
              {block.columns.map((column) => (
                <th key={column.key} className={`px-2.5 py-1.5 font-semibold ${column.align === 'right' ? 'text-right' : ''}`}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, at) => (
              <tr key={at} className="border-t border-[color:var(--color-border)]">
                {block.columns.map((column) => (
                  <td
                    key={column.key}
                    className={`t-num max-w-[14rem] truncate px-2.5 py-1.5 ${column.align === 'right' ? 'text-right' : ''}`}
                    title={String(row[column.key] ?? '')}
                  >
                    {column.format === 'bill' && row[column.key] ? (
                      <BillNumber number={String(row[column.key])} code={typeof row.id === 'string' ? row.id : null} />
                    ) : (
                      cell(row[column.key], column.format)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {block.rows.length === 0 && <p className="px-2.5 py-3 text-sm text-[color:var(--color-text-muted)]">Nothing to show.</p>}
        {block.rows.length > FIRST && (
          <button
            type="button"
            onClick={() => setAll((value) => !value)}
            className="interactive mb-1 mt-1 w-full rounded-lg py-1.5 text-xs font-semibold text-accent hover:bg-muted"
          >
            {all ? 'Show fewer' : `Show all ${block.rows.length}`}
          </button>
        )}
      </div>
    </Frame>
  )
}

// ---------------------------------------------------------------------------------------- files and tasks

function size(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return `${bytes} B`
}

export function FileBlock({ block }: { block: Block<'file'> }) {
  const Icon = block.format === 'pdf' ? FileText : FileSpreadsheet
  return (
    <div className="panel flex items-center gap-3 p-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-accent-dim text-accent">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{block.name}</p>
        <p className="truncate text-xs text-[color:var(--color-text-muted)]">
          {[block.description, size(block.size)].filter(Boolean).join(' · ')}
        </p>
      </div>
      <a
        href={block.url}
        download={block.name}
        className="btn-primary interactive inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        Download
      </a>
    </div>
  )
}

function when(value?: string | null): string {
  if (!value) return 'No date'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

export function TaskBlock({ block }: { block: Block<'task'> }) {
  const Icon = block.task_kind === 'task' ? ListChecks : BellRing
  const inner = (
    <>
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-accent-dim text-accent">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{block.title}</p>
        <p className="text-xs text-[color:var(--color-text-muted)]">
          {block.task_kind === 'task' ? 'Task' : 'Reminder'} · {when(block.due)}
        </p>
      </div>
    </>
  )
  return block.link ? (
    <TabLink to={block.link} className="panel interactive flex items-center gap-3 p-3 hover:border-[color:var(--color-border-strong)]">
      {inner}
    </TabLink>
  ) : (
    <div className="panel flex items-center gap-3 p-3">{inner}</div>
  )
}

export function BlockView({ block }: { block: AiBlock }) {
  switch (block.kind) {
    case 'metrics':
      return <MetricsBlock block={block} />
    case 'table':
      return <TableBlock block={block} />
    case 'chart':
      return (
        <Suspense fallback={<div className="panel h-[230px]" aria-busy="true" />}>
          <ChartBlock block={block} />
        </Suspense>
      )
    case 'file':
      return <FileBlock block={block} />
    case 'task':
      return <TaskBlock block={block} />
    default:
      return null
  }
}
