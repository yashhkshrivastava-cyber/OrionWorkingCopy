import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { errorText, KindIcon, todayIso } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskCalendar, TaskFilters } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const iso = (day: Date) => `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`

/** A month, week by week (Monday first), with the tasks on the day they are due. */
export function CalendarView({ project, filters }: { project: string; filters: TaskFilters }) {
  const { version } = useTasks()
  const open = useOpenTask()
  const [month, setMonth] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [data, setData] = useState<TaskCalendar | null>(null)
  const [error, setError] = useState('')
  const filterKey = JSON.stringify(filters)

  const days = useMemo(() => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1)
    const lead = (first.getDay() + 6) % 7
    const start = new Date(first)
    start.setDate(first.getDate() - lead)
    const weeks = Math.ceil((lead + new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()) / 7)
    return Array.from({ length: weeks * 7 }, (_, i) => {
      const day = new Date(start)
      day.setDate(start.getDate() + i)
      return day
    })
  }, [month])

  const load = useCallback(async () => {
    try {
      setData(await tasksApi.calendar(iso(days[0]), iso(days[days.length - 1]), { ...JSON.parse(filterKey), project, include_archived: 'true' }))
      setError('')
    } catch (e) {
      setError(errorText(e, 'The calendar could not be loaded.'))
    }
  }, [days, filterKey, project])

  useEffect(() => {
    void load()
  }, [load, version])

  const today = todayIso()
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <h2 className="t-h3 min-w-40 text-center">{month.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</h2>
        <Button size="sm" variant="secondary" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>
          Today
        </Button>
        {data && <span className="ml-auto text-xs text-[color:var(--color-text-muted)]">{data.total} with a due date</span>}
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      <div className="scroll-quiet overflow-x-auto">
        <div className="grid min-w-[44rem] grid-cols-7 overflow-hidden rounded-xl border border-[color:var(--color-border)]">
          {WEEKDAYS.map((d) => (
            <div key={d} className="border-b border-[color:var(--color-border)] bg-muted/50 px-2 py-1.5 text-center text-xs font-semibold text-[color:var(--color-text-muted)]">
              {d}
            </div>
          ))}
          {days.map((day) => {
            const key = iso(day)
            const tasks = data?.days[key] ?? []
            const outside = day.getMonth() !== month.getMonth()
            return (
              <div key={key} className={`min-h-28 border-b border-r border-[color:var(--color-border)] p-1.5 ${outside ? 'bg-muted/30' : 'bg-surface'}`}>
                <p className={`mb-1 text-right text-xs ${key === today ? 'ml-auto inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary font-bold text-on-primary' : outside ? 'text-[color:var(--color-text-faint)]' : 'text-[color:var(--color-text-muted)]'}`}>{day.getDate()}</p>
                <ul className="space-y-1">
                  {tasks.slice(0, 4).map((t) => (
                    <li key={t.key}>
                      <button
                        type="button"
                        onClick={() => open(t.key)}
                        title={`${t.key} · ${t.title}`}
                        className={`interactive flex w-full items-center gap-1 truncate rounded px-1.5 py-0.5 text-left text-[11px] ${t.status.category === 'done' ? 'bg-positive-dim text-[color:var(--color-text-muted)] line-through' : t.overdue ? 'bg-negative-dim text-[color:var(--color-text)]' : 'bg-accent-dim text-[color:var(--color-text)]'}`}
                      >
                        <KindIcon kind={t.type} className="h-3 w-3" />
                        <span className="truncate">{t.title}</span>
                      </button>
                    </li>
                  ))}
                  {tasks.length > 4 && <li className="px-1 text-[11px] text-[color:var(--color-text-muted)]">+{tasks.length - 4} more</li>}
                </ul>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
