import { useEffect, useState } from 'react'
import { TabLink } from '../ui/TabLink'
import { Database } from 'lucide-react'
import { api } from '../../api/client'
import { formatDateTime, timeAgo } from '../../formatTime'
import type { WarehouseStatus } from '../../types'
import { HoverCard } from './HoverCard'

/**
 * When the warehouse, which keeps the history of every record, was last loaded.
 *
 * The Orion dashboards read the warehouse, so their figures are as current as its last load; this tells the
 * reader how recent that is. `reloadKey` fetches it again. `compact` is a small status chip for a page header: it
 * says how fresh the figures are and keeps the detail (when, by whom, how often it checks) in a pop-over.
 */
export function WarehouseFreshness({
  source,
  reloadKey = 0,
  compact = false,
}: {
  source: 'dashboard' | 'dw'
  reloadKey?: number
  compact?: boolean
}) {
  const [status, setStatus] = useState<WarehouseStatus | null>(null)

  useEffect(() => {
    let live = true
    api
      .warehouseStatus(source)
      .then((s) => live && setStatus(s))
      .catch(() => live && setStatus(null))
    return () => {
      live = false
    }
  }, [source, reloadKey])

  if (!status) return null
  const ok = status.last_success
  const failed = status.latest?.status === 'failed' ? status.latest : null
  const how =
    status.autoload_minutes > 0
      ? `Checked automatically every ${status.autoload_minutes === 60 ? 'hour' : `${status.autoload_minutes} min`}.`
      : 'Automatic loading is off.'

  if (compact) {
    const tone = failed ? 'bg-negative' : ok ? 'bg-positive' : 'bg-warning'
    return (
      <HoverCard
        label="How current these figures are"
        width={320}
        trigger={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-border)] bg-surface px-2.5 py-1 text-xs text-[color:var(--color-text-muted)]">
            <span className={`h-1.5 w-1.5 rounded-full ${tone}`} aria-hidden="true" />
            {failed ? 'Latest load failed' : ok ? <>Updated {timeAgo(ok.finished)}</> : 'Not loaded yet'}
          </span>
        }
      >
        <div className="space-y-1.5">
          <p className="text-sm font-semibold text-[color:var(--color-text)]">
            {ok ? (
              <>Figures are as at {formatDateTime(ok.finished)}</>
            ) : (
              'The warehouse has not been fully loaded yet'
            )}
          </p>
          {ok && (
            <p>
              {ok.trigger === 'manual' && ok.by ? `Loaded by ${ok.by}. ` : ok.trigger === 'scheduled' ? 'Loaded on schedule. ' : ''}
              {source === 'dashboard' ? 'Changes made since then show after the next load. ' : ''}
              {how}
            </p>
          )}
          {failed && (
            <p className="font-medium text-negative">
              The latest load failed {timeAgo(failed.finished ?? failed.started)}
              {failed.error ? `: ${failed.error}` : '.'}
            </p>
          )}
          <TabLink to="/etl?pipeline=orion_dw" className="inline-block font-medium text-accent hover:underline">
            View load history
          </TabLink>
        </div>
      </HoverCard>
    )
  }

  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[color:var(--color-text-muted)]">
      <Database className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
      {ok ? (
        <span>
          Warehouse last loaded{' '}
          <span className="font-medium text-[color:var(--color-text)]" title={formatDateTime(ok.finished)}>
            {timeAgo(ok.finished)}
          </span>{' '}
          ({formatDateTime(ok.finished)}
          {ok.trigger === 'manual' && ok.by ? `, by ${ok.by}` : ok.trigger === 'scheduled' ? ', scheduled' : ''}).
          {source === 'dashboard' ? ' Figures here are as at that load.' : ''} {how}
        </span>
      ) : (
        <span>The warehouse has not been fully loaded yet. {how}</span>
      )}
      <TabLink to="/etl?pipeline=orion_dw" className="font-medium text-accent hover:underline">
        View load history
      </TabLink>
      {failed && (
        <span className="font-medium text-negative">
          The latest load failed {timeAgo(failed.finished ?? failed.started)}
          {failed.error ? `: ${failed.error}` : '.'}
        </span>
      )}
    </p>
  )
}
