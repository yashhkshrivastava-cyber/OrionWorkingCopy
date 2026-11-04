import { useCallback, useEffect, useState } from 'react'
import { ClipboardCheck, ListTodo } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { TaskGroup } from '../../components/tasks/TaskRow'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { EmptyState, Skeleton } from '../../components/ui/EmptyState'
import { useAuth } from '../../context/AuthContext'
import { useTasks } from '../../context/TasksContext'
import { useLumen } from '../../lumen/useLumen'
import { errorText } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskMine } from '../../types'

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'danger' | 'warn' }) {
  const lumen = useLumen()
  if (lumen) return <StatTile label={label} text={String(value)} tone={value && tone === 'danger' ? 'text-negative' : value && tone === 'warn' ? 'text-warning' : ''} />
  return (
    <div className="panel !p-4">
      <p className="t-caption text-[color:var(--color-text-muted)]">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone === 'danger' && value ? 'text-negative' : tone === 'warn' && value ? 'text-warning' : 'text-[color:var(--color-text)]'}`}>{value}</p>
    </div>
  )
}

/** What is on this person's plate: their tasks by when they are due, what waits for their review, and what they raised or watch. */
export function MyWorkPage() {
  const { version } = useTasks()
  const lumen = useLumen()
  const { user } = useAuth()
  const open = useOpenTask()
  const [mine, setMine] = useState<TaskMine | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setMine(await tasksApi.mine())
      setError('')
    } catch (e) {
      setError(errorText(e, 'Your work could not be loaded.'))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, version])

  if (error && !mine) return <Alert variant="error">{error}</Alert>
  if (!mine)
    return (
      <div className="space-y-3">
        <Skeleton className="h-20" />
        <Skeleton className="h-48" />
      </div>
    )

  const { buckets, counts } = mine
  const nothing = counts.assigned === 0 && mine.to_review.length === 0 && mine.raised.length === 0 && mine.watching.length === 0

  // Lumen opens on a sentence about the day: what is late, what is due, what waits for this person.
  const parts = [
    counts.overdue ? `${counts.overdue} overdue` : '',
    counts.today ? `${counts.today} due today` : '',
    counts.to_review ? `${counts.to_review} waiting for your review` : '',
  ].filter(Boolean)
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const first = (user?.display_name ?? '').trim().split(/\s+/)[0]
  const sentence = parts.length
    ? `You have ${parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0]}.`
    : counts.assigned
      ? `${counts.assigned} ${counts.assigned === 1 ? 'task is' : 'tasks are'} on your plate and none is urgent.`
      : 'You are all caught up.'

  return (
    <div className="space-y-6">
      {lumen && (
        <section aria-label="Your day" className="panel relative overflow-hidden !p-0 text-[color:var(--orion-on-primary)]" style={{ backgroundImage: 'var(--orion-highlight-fill)' }}>
          <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
          <div className="relative p-6 sm:p-8">
            <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-85">Your day</p>
            <h2 className="font-display mt-1 text-3xl font-semibold leading-tight sm:text-4xl">
              {greeting}
              {first ? `, ${first}` : ''}
            </h2>
            <p className="mt-1 max-w-xl text-sm opacity-90">{sentence}</p>
          </div>
        </section>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Assigned to me" value={counts.assigned} />
        <Stat label="Overdue" value={counts.overdue} tone="danger" />
        <Stat label="Due today" value={counts.today} tone="warn" />
        <Stat label="Waiting for my review" value={counts.to_review} tone="warn" />
      </div>

      {nothing && (
        <EmptyState icon={ClipboardCheck} title="Nothing on your plate">
          Tasks given to you, waiting for your review, raised by you or watched by you appear here. Make one with “New task”, or write yourself a note in To-do lists.
        </EmptyState>
      )}

      <TaskGroup title="Waiting for my review" tone="warn" tasks={mine.to_review} onOpen={open} />
      <TaskGroup title="Overdue" tone="danger" tasks={buckets.overdue} onOpen={open} />
      <TaskGroup title="Due today" tone="warn" tasks={buckets.today} onOpen={open} />
      <TaskGroup title="This week" tasks={buckets.week} onOpen={open} />
      <TaskGroup title="Later" tasks={buckets.later} onOpen={open} />
      <TaskGroup title="No due date" tasks={buckets.no_date} onOpen={open} />
      <TaskGroup title="Raised by me" tasks={mine.raised} onOpen={open} />
      <TaskGroup title="Watching" tasks={mine.watching} onOpen={open} />
      <TaskGroup title="Finished recently" tasks={mine.recently_done} onOpen={open} />

      {!nothing && counts.assigned === 0 && (
        <p className="flex items-center gap-2 text-sm text-[color:var(--color-text-muted)]">
          <ListTodo className="h-4 w-4" /> No task is assigned to you right now.
        </p>
      )}
    </div>
  )
}
