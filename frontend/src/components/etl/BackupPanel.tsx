import { useCallback, useEffect, useState } from 'react'
import { CircleAlert, CircleCheck, DatabaseBackup, LoaderCircle } from 'lucide-react'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { formatBytes, formatDuration } from '../../etl/format'
import { formatDateTime, timeAgo } from '../../formatTime'
import type { BackupStatus } from '../../types'
import { Button } from '../ui/Button'

const FAST_MS = 3000
const SLOW_MS = 30000

/**
 * When the database was last backed up, and whether backups are healthy. Admin only: it fetches its own status and
 * draws nothing for anyone else. It shows the state of backups, never their contents; there is no way to download one.
 */
export function BackupPanel({ now }: { now: number }) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [status, setStatus] = useState<BackupStatus | null>(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)

  const load = useCallback(() => {
    api
      .backupStatus()
      .then((next) => {
        setStatus(next)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const running = Boolean(status?.running) || starting
  useEffect(() => {
    if (!isAdmin) return
    load()
    const timer = window.setInterval(load, running ? FAST_MS : SLOW_MS)
    return () => window.clearInterval(timer)
  }, [isAdmin, load, running])

  useEffect(() => {
    if (status?.running) setStarting(false)
  }, [status?.running])

  if (!isAdmin) return null

  const run = async () => {
    setStarting(true)
    setError('')
    try {
      await api.runBackup()
      load()
    } catch (e) {
      setError((e as Error).message)
      setStarting(false)
    }
  }

  const last = status?.last_success ?? null
  const latest = status?.recent[0]
  const failing = latest?.status === 'failed'
  const bad = status?.state === 'ready' && (status.stale || failing)
  const tone = bad ? 'text-negative' : status?.state === 'ready' ? 'text-positive' : 'text-[color:var(--color-text-faint)]'
  const Icon = running ? LoaderCircle : bad ? CircleAlert : status?.state === 'ready' ? CircleCheck : DatabaseBackup

  let headline = 'Checking…'
  if (status) {
    if (status.state === 'off') headline = 'Backups are switched off on this machine'
    else if (status.state === 'blocked') headline = 'Backups cannot run on this machine'
    else if (running) headline = 'Backing up now…'
    else if (last?.finished_timestamp) headline = `Last successful backup ${timeAgo(last.finished_timestamp, now)}`
    else headline = 'No backup has succeeded yet'
  }

  return (
    <section className="panel overflow-hidden" aria-label="Database backups">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 py-4">
        <div className="flex min-w-0 items-start gap-3">
          <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${tone} ${running ? 'animate-spin' : ''}`} aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="t-h3 text-[color:var(--color-text)]">Database backups</h2>
            <p className="text-[15px] font-medium text-[color:var(--color-text)]" role="status" aria-live="polite">
              {headline}
            </p>
            {status && last?.finished_timestamp && status.state === 'ready' && (
              <p className="text-xs text-[color:var(--color-text-muted)]">
                {formatDateTime(last.finished_timestamp)} · {formatBytes(last.size_bytes)} · encrypted
              </p>
            )}
            {status?.state === 'ready' && (
              <p className="mt-1 text-xs text-[color:var(--color-text-muted)]">
                Every {status.interval_hours === 24 ? 'day' : `${status.interval_hours} h`} to the {status.role} bucket
                {status.bucket ? ` (${status.bucket})` : ''}
                {status.next_run ? ` · next ${formatDateTime(status.next_run)}` : ''}
              </p>
            )}
          </div>
        </div>
        {status?.state === 'ready' && (
          <Button variant="secondary" size="sm" onClick={() => void run()} loading={running} disabled={running}>
            Back up now
          </Button>
        )}
      </header>

      {error && (
        <p role="alert" className="border-t border-[color:var(--color-border)] bg-negative-dim px-5 py-2.5 text-sm text-[color:var(--color-text)]">
          {error}
        </p>
      )}
      {status && status.state === 'ready' && (status.stale || failing) && (
        <p role="alert" className="border-t border-[color:var(--color-border)] bg-negative-dim px-5 py-2.5 text-sm text-[color:var(--color-text)]">
          {failing ? `The latest backup failed: ${latest?.error ?? 'no reason recorded'}` : 'The last successful backup is older than it should be.'}
        </p>
      )}
      {status && status.state !== 'ready' && status.problems.length > 0 && (
        <ul className="space-y-1 border-t border-[color:var(--color-border)] bg-muted px-5 py-3 text-xs text-[color:var(--color-text-muted)]">
          {status.problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}

      {status && status.recent.length > 0 && (
        <div className="overflow-x-auto border-t border-[color:var(--color-border)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[color:var(--color-text-muted)]">
                <th className="px-5 py-2 font-medium">Started</th>
                <th className="px-3 py-2 font-medium">Result</th>
                <th className="px-3 py-2 font-medium">By</th>
                <th className="px-3 py-2 text-right font-medium">Size</th>
                <th className="px-5 py-2 text-right font-medium">Took</th>
              </tr>
            </thead>
            <tbody>
              {status.recent.slice(0, 5).map((row) => (
                <tr key={row.id} className="border-t border-[color:var(--color-border)]" title={row.error ?? undefined}>
                  <td className="px-5 py-2 text-[color:var(--color-text)]">{formatDateTime(row.started_timestamp)}</td>
                  <td className="px-3 py-2">
                    <span className={row.status === 'failed' ? 'font-medium text-negative' : row.status === 'running' ? 'text-warning' : 'text-positive'}>
                      {row.status === 'succeeded' ? 'Succeeded' : row.status === 'failed' ? 'Failed' : 'Running'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-[color:var(--color-text-muted)]">{row.trigger === 'manual' ? 'Manual' : 'Scheduled'}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-[color:var(--color-text)]">{formatBytes(row.size_bytes)}</td>
                  <td className="px-5 py-2 text-right tabular-nums text-[color:var(--color-text-muted)]">{formatDuration(row.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
