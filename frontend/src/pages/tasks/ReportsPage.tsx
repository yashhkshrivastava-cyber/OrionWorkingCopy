import { useEffect, useState, type ReactNode } from 'react'
import { tasksApi } from '../../api/client'
import { Alert } from '../../components/ui/Alert'
import { Skeleton } from '../../components/ui/EmptyState'
import { Select } from '../../components/ui/Field'
import { useTasks } from '../../context/TasksContext'
import { CATEGORY_LABEL, errorText, formatDay, formatMinutes, PriorityMark } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { StatusCategory, TaskProjectSummary, TaskReports } from '../../types'

const BAR: Record<StatusCategory, string> = { todo: 'bg-[color:var(--color-text-faint)]', doing: 'bg-accent', review: 'bg-violet', done: 'bg-positive' }

function Tile({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: 'danger' }) {
  return (
    <div className="panel !p-4">
      <p className="t-caption text-[color:var(--color-text-muted)]">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone === 'danger' ? 'text-negative' : 'text-[color:var(--color-text)]'}`}>{value}</p>
      {hint && <p className="t-caption mt-0.5 text-[color:var(--color-text-faint)]">{hint}</p>}
    </div>
  )
}

function Bars({ rows, tone }: { rows: { label: string; value: number; className?: string }[]; tone?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (!rows.length) return <p className="text-sm text-[color:var(--color-text-muted)]">Nothing to show.</p>
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.label} className="grid grid-cols-[8rem_1fr_2.5rem] items-center gap-3 text-sm">
          <span className="truncate text-[color:var(--color-text-muted)]">{row.label}</span>
          <span className="h-2.5 overflow-hidden rounded-full bg-muted">
            <span className={`block h-full rounded-full ${row.className ?? tone ?? 'bg-accent'}`} style={{ width: `${(row.value / max) * 100}%` }} />
          </span>
          <span className="text-right tabular-nums text-[color:var(--color-text)]">{row.value}</span>
        </li>
      ))}
    </ul>
  )
}

/** How the work is going: what is open and where, who has how much, what is late, and how much is made against how much is finished each week. */
export function ReportsPage() {
  const { version } = useTasks()
  const open = useOpenTask()
  const [project, setProject] = useState('')
  const [days, setDays] = useState(30)
  const [projects, setProjects] = useState<TaskProjectSummary[]>([])
  const [data, setData] = useState<TaskReports | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    tasksApi
      .projects()
      .then((found) => setProjects(found.projects))
      .catch(() => setProjects([]))
  }, [])

  useEffect(() => {
    let cancelled = false
    tasksApi
      .reports(project || undefined, days)
      .then((found) => {
        if (!cancelled) {
          setData(found)
          setError('')
        }
      })
      .catch((e) => !cancelled && setError(errorText(e, 'The report could not be loaded.')))
    return () => {
      cancelled = true
    }
  }, [project, days, version])

  const flowMax = Math.max(1, ...(data?.flow.flatMap((w) => [w.created, w.resolved]) ?? [1]))

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Select className="!w-auto" value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
          <option value="">All my projects</option>
          {projects.map((p) => (
            <option key={p.key} value={p.key}>
              {p.key} · {p.name}
            </option>
          ))}
        </Select>
        <Select className="!w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={180}>Last 180 days</option>
        </Select>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {!data && !error && (
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Open tasks" value={data.open} hint={`${data.unassigned} with nobody assigned`} />
            <Tile label="Overdue" value={data.overdue.length >= 25 ? '25+' : data.overdue.length} tone="danger" />
            <Tile label="Finished in 90 days" value={data.finished_90} />
            <Tile label="Typical time to finish" value={data.cycle_days ? `${data.cycle_days} days` : '—'} hint="From raised to finished" />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="panel space-y-3">
              <h3 className="t-h3">Where the work is</h3>
              <Bars rows={data.by_status.map((s) => ({ label: `${s.name}`, value: s.count, className: BAR[s.category] }))} />
              <p className="t-caption text-[color:var(--color-text-faint)]">{(Object.keys(CATEGORY_LABEL) as StatusCategory[]).map((c) => CATEGORY_LABEL[c]).join(' · ')}</p>
            </section>
            <section className="panel space-y-3">
              <h3 className="t-h3">Open by priority</h3>
              <Bars
                rows={data.by_priority.map((p) => ({ label: p.priority, value: p.count, className: p.priority === 'Critical' ? 'bg-negative' : p.priority === 'High' ? 'bg-warning' : p.priority === 'Medium' ? 'bg-accent' : 'bg-[color:var(--color-text-faint)]' }))}
              />
              <h3 className="t-h3 pt-2">Open by type</h3>
              <Bars rows={data.by_type.map((t) => ({ label: t.type, value: t.count }))} />
            </section>
          </div>

          <section className="panel space-y-3">
            <h3 className="t-h3">Raised and finished, week by week</h3>
            <div className="flex h-40 items-end gap-2" role="img" aria-label="Tasks raised and finished each week">
              {data.flow.map((w) => (
                <div key={w.week} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                  <div className="flex h-32 w-full items-end justify-center gap-0.5">
                    <span className="w-1/2 max-w-4 rounded-t bg-accent" style={{ height: `${(w.created / flowMax) * 100}%` }} title={`${w.created} raised`} />
                    <span className="w-1/2 max-w-4 rounded-t bg-positive" style={{ height: `${(w.resolved / flowMax) * 100}%` }} title={`${w.resolved} finished`} />
                  </div>
                  <span className="text-[10px] text-[color:var(--color-text-faint)]">{formatDay(w.week)}</span>
                </div>
              ))}
            </div>
            <p className="t-caption flex gap-4 text-[color:var(--color-text-muted)]">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-accent" /> Raised
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-positive" /> Finished
              </span>
            </p>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="panel space-y-3">
              <h3 className="t-h3">Who has what</h3>
              <ul className="divide-y divide-[color:var(--color-border)]">
                {data.people.map((p) => (
                  <li key={p.id ?? 'nobody'} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-4 py-2 text-sm">
                    <span className="truncate font-medium">{p.name}</span>
                    <span className="tabular-nums text-[color:var(--color-text-muted)]" title="Open">
                      {p.open} open
                    </span>
                    <span className={`tabular-nums ${p.overdue ? 'font-semibold text-negative' : 'text-[color:var(--color-text-faint)]'}`} title="Overdue">
                      {p.overdue} late
                    </span>
                    <span className="tabular-nums text-positive" title={`Finished in ${data.days} days`}>
                      {p.finished} done
                    </span>
                  </li>
                ))}
                {data.people.length === 0 && <li className="py-2 text-sm text-[color:var(--color-text-muted)]">No tasks yet.</li>}
              </ul>
            </section>
            <section className="panel space-y-3">
              <h3 className="t-h3">Time logged · last {data.days} days</h3>
              <Bars rows={data.time_by_person.map((t) => ({ label: t.name, value: Math.round(t.minutes / 6) / 10 }))} tone="bg-accent" />
              <p className="t-caption text-[color:var(--color-text-faint)]">Hours.{data.time_by_person.length ? ` Total ${formatMinutes(data.time_by_person.reduce((n, t) => n + t.minutes, 0))}.` : ''}</p>
            </section>
          </div>

          <section className="panel space-y-3">
            <h3 className="t-h3">Most overdue</h3>
            {data.overdue.length === 0 ? (
              <p className="text-sm text-[color:var(--color-text-muted)]">Nothing is overdue.</p>
            ) : (
              <ul className="divide-y divide-[color:var(--color-border)]">
                {data.overdue.map((t) => (
                  <li key={t.key}>
                    <button type="button" onClick={() => open(t.key)} className="interactive grid w-full grid-cols-[5rem_1fr_auto_auto] items-center gap-3 py-2 text-left text-sm hover:text-accent">
                      <span className="text-xs font-medium text-[color:var(--color-text-muted)]">{t.key}</span>
                      <span className="truncate">{t.title}</span>
                      <PriorityMark priority={t.priority} />
                      <span className="text-xs font-semibold text-negative">
                        {t.days_late} day{t.days_late === 1 ? '' : 's'} late{t.assignee ? ` · ${t.assignee}` : ''}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
