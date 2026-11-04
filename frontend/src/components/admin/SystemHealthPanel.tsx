import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { CheckCircle2, RefreshCw, TriangleAlert } from 'lucide-react'
import { api } from '../../api/client'
import type { SystemHealth } from '../../types'
import { formatDateTime, timeAgo } from '../../formatTime'
import { Card, CardHeader } from '../ui/Card'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Alert'

const REFRESH_MS = 30_000

function uptime(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h`
  return `${Math.round(seconds / 86400)} days`
}

/** A plain table whose cells may hold badges (DataTable draws text only). */
function Table({ columns, rows, empty }: { columns: string[]; rows: ReactNode[][]; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-[color:var(--color-text-muted)]">{empty}</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[28rem] border-collapse text-left text-[13px]">
        <thead>
          <tr className="text-[11px] text-[color:var(--color-text-muted)]">
            {columns.map((column) => (
              <th key={column} className="px-2.5 py-1.5 font-semibold">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={at} className="border-t border-[color:var(--color-border)]">
              {row.map((cell, index) => (
                <td key={index} className="px-2.5 py-2 align-top text-[color:var(--color-text)]">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/60 px-3 py-2.5">
      <p className="t-caption">{label}</p>
      <p className="t-num mt-0.5 truncate text-lg font-semibold text-[color:var(--color-text)]">{value}</p>
      {note && <p className="t-caption mt-0.5 truncate">{note}</p>}
    </div>
  )
}

const LEVEL: Record<string, 'rose' | 'amber' | 'default'> = { ERROR: 'rose', CRITICAL: 'rose', WARNING: 'amber' }

/**
 * What an administrator would otherwise have to ask someone to look up in the server's log: whether the database answers, when
 * each warehouse load and the backup last worked, how the server is coping, and the last warnings and errors with the reference
 * to find them in the log file. Read-only. It refreshes itself while it is open.
 */
export function SystemHealthPanel() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setHealth(await api.systemHealth())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the system status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [load])

  if (!health) {
    return (
      <Card accent="teal">
        <CardHeader title="System" subtitle="How the server is doing" />
        <p className="text-sm text-[color:var(--color-text-muted)]">{error || 'Loading…'}</p>
      </Card>
    )
  }

  const ok = health.status === 'ok'
  const { requests, database, backup } = health

  return (
    <div className="grid gap-5">
      <Card accent={ok ? 'emerald' : 'amber'}>
        <CardHeader
          title={ok ? 'Everything looks well' : 'Needs attention'}
          subtitle={`${health.environment === 'production' ? 'Production' : 'Development'} · checked ${timeAgo(health.checked)}`}
          action={
            <Button size="sm" variant="secondary" loading={loading} onClick={() => void load()}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              Refresh
            </Button>
          }
        />
        {error && (
          <p role="alert" className="mb-3 text-xs text-negative">
            {error}
          </p>
        )}
        {ok ? (
          <p className="flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
            <CheckCircle2 className="h-4 w-4 text-positive" aria-hidden="true" />
            The database answers, the loads and backup are current, and no errors were logged in the last hour.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {health.attention.map((note) => (
              <li key={note} className="flex items-start gap-2 text-sm text-[color:var(--color-text)]">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                {note}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Database"
          value={database.ok ? 'Answering' : 'Not answering'}
          note={
            database.ok && database.ms !== null
              ? `${database.ms} ms${database.pool ? ` · ${database.pool.in_use} of ${database.pool.max} connections busy` : ''}`
              : (database.error ?? undefined)
          }
        />
        <Stat label="Requests since start" value={requests.total.toLocaleString('en-IN')} note={`up ${uptime(requests.uptime_seconds)}`} />
        <Stat label="Server errors" value={String(requests.errors_5xx)} note="answered 500 since start" />
        <Stat label="Slow requests" value={String(requests.slow)} note={`over ${requests.slow_threshold_ms / 1000} s`} />
      </div>

      <Card accent="blue">
        <CardHeader title="Warehouse loads and backup" subtitle="From the run history, not from this page's own clock" />
        <Table
          columns={['What', 'Last good', 'Last failed', 'State']}
          rows={[
            ...health.loads.map((load) => [
              load.pipeline,
              load.last_success ? `${timeAgo(load.last_success)} (${formatDateTime(load.last_success)})` : 'never',
              load.last_failure ? timeAgo(load.last_failure) : '–',
              load.running ? <Badge key="r" variant="cyan">Running</Badge> : load.failing ? <Badge key="f" variant="rose">Failing</Badge> : <Badge key="o" variant="emerald">Fine</Badge>,
            ]),
            [
              'Backup',
              backup?.last_success?.finished_timestamp ? `${timeAgo(backup.last_success.finished_timestamp)} (${formatDateTime(backup.last_success.finished_timestamp)})` : backup ? 'never' : '–',
              '–',
              !backup ? (
                <Badge key="b">Unknown</Badge>
              ) : backup.state === 'off' ? (
                <Badge key="b">Off</Badge>
              ) : backup.running ? (
                <Badge key="b" variant="cyan">Running</Badge>
              ) : backup.state === 'blocked' || backup.stale ? (
                <Badge key="b" variant="rose">{backup.state === 'blocked' ? 'Blocked' : 'Overdue'}</Badge>
              ) : (
                <Badge key="b" variant="emerald">Fine</Badge>
              ),
            ],
          ]}
          empty="No loads have run yet."
        />
        <p className="t-caption mt-3">
          Database schema: {health.schema.applied} of {health.schema.steps} steps applied
          {health.schema.last_applied ? `, the last ${timeAgo(health.schema.last_applied)}` : ''}.{' '}
        </p>
        <p className="t-caption mt-1">
          {health.autoload.minutes
            ? `The warehouse checks for changes every ${health.autoload.minutes} minutes${health.autoload.next_check ? `; next check ${timeAgo(health.autoload.next_check) === 'just now' ? 'now' : formatDateTime(health.autoload.next_check)}` : ''}.`
            : 'Automatic warehouse loading is off.'}
        </p>
      </Card>

      {requests.recent_slow.length > 0 && (
        <Card accent="amber">
          <CardHeader title="Slowest recent requests" subtitle={`Anything over ${requests.slow_threshold_ms / 1000} seconds, newest first`} />
          <Table
            columns={['When', 'Request', 'Status', 'Time', 'Reference']}
            rows={[...requests.recent_slow].reverse().map((item) => [
              timeAgo(item.time),
              `${item.method} ${item.path}`,
              String(item.status),
              `${(item.ms / 1000).toFixed(1)} s`,
              <code key="c" className="text-xs">{item.request_id}</code>,
            ])}
          />
        </Card>
      )}

      <Card accent="rose">
        <CardHeader
          title="Recent problems"
          subtitle={`Warnings and errors since the server started. The reference finds the whole story in the log${health.log.file ? ` (${health.log.file})` : ''}.`}
        />
        {health.problems.length === 0 ? (
          <p className="text-sm text-[color:var(--color-text-muted)]">Nothing has been logged as a warning or an error since the server started.</p>
        ) : (
          <ul className="divide-y divide-[color:var(--color-border)]">
            {health.problems.map((item, index) => (
              <li key={index} className="py-2.5 first:pt-0 last:pb-0">
                <p className="flex flex-wrap items-center gap-2 text-xs text-[color:var(--color-text-muted)]">
                  <Badge variant={LEVEL[item.level] ?? 'default'}>{item.level}</Badge>
                  <span title={formatDateTime(item.time)}>{timeAgo(item.time)}</span>
                  <span>{item.logger}</span>
                  {item.request_id !== '-' && <code className="text-xs">{item.request_id}</code>}
                </p>
                <p className="mt-1 break-words text-sm text-[color:var(--color-text)]">{item.message}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
