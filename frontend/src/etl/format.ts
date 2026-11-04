import type { EtlRun, EtlStepStatus } from '../types'

/** "850 ms", "4.2 s", "2 min 5 s", "1 h 3 min". A missing time is a dash. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '–'
  if (ms < 1000) return `${Math.round(ms)} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ${Math.round(seconds % 60)} s`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

/** Whole numbers in the Indian grouping used everywhere else in the app. */
export function count(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : value.toLocaleString('en-IN')
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : `${Math.round(value * 100)}%`
}

export const TRIGGER_LABEL: Record<EtlRun['trigger'], string> = { manual: 'Manual', scheduled: 'Scheduled' }

export const STATUS_LABEL: Record<EtlRun['status'] | EtlStepStatus, string> = {
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  pending: 'Waiting',
  skipped: 'Skipped',
}

/** Who started it: a person, or the scheduler when nobody did. */
export function startedBy(run: Pick<EtlRun, 'trigger' | 'started_by_name' | 'started_by'>): string {
  if (run.started_by_name) return run.started_by_name
  if (run.trigger === 'scheduled') return 'Scheduler'
  return run.started_by === null ? 'Unknown' : 'A former user'
}

/** What a run read from, in a sentence. The source is whatever the pipeline recorded when it started. */
export function describeSource(source: EtlRun['source']): string {
  if (!source) return 'Not recorded (the run stopped before it connected)'
  const system = String(source.system ?? '')
  if (system === 'Tally Prime') {
    const companies = Array.isArray(source.companies) ? (source.companies as string[]).join(', ') : ''
    const range = source.from_date && source.to_date ? ` · vouchers ${source.from_date} to ${source.to_date}` : ''
    return `Tally Prime at ${source.host}:${source.port}${companies ? ` · ${companies}` : ''}${range}`
  }
  return source.schema ? `${system} (${source.schema})` : system
}

/** "Today", "Yesterday", or "3 Oct 2026": the heading a day of runs sits under. */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const day = new Date(iso)
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const diff = Math.round((midnight(now) - midnight(day)) / 86_400_000)
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  return day.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** "11:37 am" */
export function clock(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true })
}

/** "AM" for "Aman Mishra", "S" for "Scheduler". */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

/** The four things a load can do to a row, with the colour that marks each. Always printed beside its name. */
export const OUTCOMES = [
  { key: 'inserted', label: 'Inserted', color: 'var(--etl-inserted)', hint: 'New rows.' },
  { key: 'updated', label: 'Updated', color: 'var(--etl-updated)', hint: 'Rows that changed. In a warehouse, rows that got a new version.' },
  { key: 'deleted', label: 'Deleted', color: 'var(--etl-deleted)', hint: 'Rows the source no longer has. In a warehouse, rows marked expired.' },
  { key: 'unchanged', label: 'Unchanged', color: 'var(--orion-text-faint)', hint: 'Rows that were already up to date.' },
] as const

export type OutcomeKey = (typeof OUTCOMES)[number]['key']

/** How the counts of a run read in a sentence: "inserted 2, updated 1" or "nothing changed". */
export function changeSentence(counts: Record<'inserted' | 'updated' | 'deleted', number>): string {
  const parts = (['inserted', 'updated', 'deleted'] as const).filter((k) => counts[k] > 0).map((k) => `${k} ${counts[k].toLocaleString('en-IN')}`)
  return parts.length ? parts.join(', ') : 'nothing changed'
}

/** One sentence about the state of every pipeline, for the top of the page. */
export function healthSummary(
  pipelines: { label: string; running: boolean; last_run: { status: string; started_timestamp: string } | null }[],
  ago: (iso: string) => string,
): { tone: 'ok' | 'running' | 'failed' | 'idle'; text: string } {
  const running = pipelines.filter((p) => p.running)
  if (running.length) {
    return { tone: 'running', text: `${running.map((p) => p.label).join(' and ')} ${running.length === 1 ? 'is' : 'are'} loading now` }
  }
  const failed = pipelines.filter((p) => p.last_run?.status === 'failed')
  if (failed.length) {
    const first = failed[0]
    return { tone: 'failed', text: `${first.label} failed ${ago(first.last_run!.started_timestamp)}${failed.length > 1 ? `, and ${failed.length - 1} more` : ''}` }
  }
  const ran = pipelines.filter((p) => p.last_run)
  if (!ran.length) return { tone: 'idle', text: 'No pipeline has run yet' }
  const stamps = ran.map((p) => p.last_run!.started_timestamp).sort()
  const newest = stamps[stamps.length - 1]
  return { tone: 'ok', text: `Everything is healthy. The last load was ${ago(newest)}` }
}

/** "350 KB", "12.4 MB": the size of a file. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '–'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}
