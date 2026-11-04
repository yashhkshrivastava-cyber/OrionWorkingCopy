import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, CalendarDays, Check, Plus, Sparkles, Sun } from 'lucide-react'
import { api, tasksApi } from '../api/client'
import { newIdempotencyKey } from '../api/idempotency'
import { useAssistant } from '../ai/AssistantContext'
import { NAV_GROUPS, AREA_BLURB, hueVar } from '../components/nav/navigation'
import { UserAvatar } from '../components/UserAvatar'
import { inr } from '../components/dashboard/format'
import { useAuth } from '../context/AuthContext'
import { useChat } from '../context/ChatContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { useTabMemory } from '../context/TabMemoryContext'
import { useTasks } from '../context/TasksContext'
import { celebrate } from '../lumen/celebrate'
import { useCountUp } from '../lumen/useCountUp'
import { DueLabel, KindIcon, errorText } from '../tasks/taskUi'
import type { TaskMine, TodoOverview } from '../types'

function greeting() {
  const hour = new Date().getHours()
  if (hour < 5) return 'Still up'
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  if (hour < 21) return 'Good evening'
  return 'Good night'
}

/** A figure that counts up when the page opens, over a soft coloured tile. Opens where it belongs. */
function Tile({ label, value, hint, to, hue, format }: { label: string; value: number; hint?: string; to: string; hue: string; format?: (n: number) => string }) {
  const shown = useCountUp(value)
  return (
    <Link to={to} style={{ '--hue': `var(--lumen-${hue})` } as React.CSSProperties} className="panel data-hot group relative flex flex-col gap-1 overflow-hidden !p-5">
      <span className="absolute -right-6 -top-6 h-24 w-24 rounded-full opacity-25 blur-2xl transition-opacity duration-500 group-hover:opacity-50" style={{ background: 'var(--hue)' }} aria-hidden="true" />
      <span className="t-caption relative font-semibold text-[color:var(--color-text-muted)]">{label}</span>
      <span className="font-display relative text-3xl font-semibold tabular-nums leading-none">{format ? format(shown) : shown}</span>
      {hint && <span className="t-caption relative text-[color:var(--color-text-faint)]">{hint}</span>}
    </Link>
  )
}

/**
 * Today: the Lumen interface's front door for someone signed in. What needs this person today (their tasks, reviews, messages and, where they may see it,
 * what clients owe), a "My day" list they can tick off here, and every space they can use as coloured tiles. Everything on it is live data from the same
 * places the rest of the application reads; a tile for something this person may not see is not drawn.
 */
export function LumenHome() {
  const { user } = useAuth()
  const { unread } = useChat()
  const { version, changed } = useTasks()
  const { generation } = useDataRefresh()
  const last = useTabMemory()
  const assistant = useAssistant()
  const navigate = useNavigate()
  const [mine, setMine] = useState<TaskMine | null>(null)
  const [todo, setTodo] = useState<TodoOverview | null>(null)
  const [owed, setOwed] = useState<number | null>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const canBill = Boolean(user?.pages.includes('utility'))

  const load = useCallback(async () => {
    try {
      const [m, t] = await Promise.all([tasksApi.mine(), tasksApi.todo()])
      setMine(m)
      setTodo(t)
      setError('')
    } catch (e) {
      setError(errorText(e, 'Your day could not be loaded.'))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, version, generation])

  useEffect(() => {
    if (!canBill) return
    let cancelled = false
    api
      .receivables()
      .then((r) => !cancelled && setOwed(r.totals.total))
      .catch(() => !cancelled && setOwed(null))
    return () => {
      cancelled = true
    }
  }, [canBill, generation])

  const day = useMemo(() => new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' }), [])
  const first = user?.display_name?.split(' ')[0] ?? ''
  const myDay = todo?.items.filter((item) => item.in_my_day) ?? []
  const open = myDay.filter((item) => !item.done)
  const dueToday = [...(mine?.buckets.overdue ?? []), ...(mine?.buckets.today ?? [])]
  const attention = (mine?.counts.overdue ?? 0) + (mine?.counts.today ?? 0) + (mine?.counts.to_review ?? 0)

  const addToDay = async () => {
    const value = text.trim()
    if (!value || !todo) return
    setText('')
    try {
      setTodo(await tasksApi.addTodo({ text: value, my_day: todo.today }, newIdempotencyKey()))
    } catch (e) {
      setError(errorText(e))
    }
  }

  const tick = async (id: number, done: boolean, origin: Element) => {
    try {
      setTodo(await tasksApi.updateTodo(id, { done }))
      if (done) celebrate(origin)
      changed()
    } catch (e) {
      setError(errorText(e))
    }
  }

  const areas = NAV_GROUPS.flatMap((group) => group.items.filter((item) => user && item.visible(user)))

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 pb-10 pt-2 sm:px-6 lg:px-8">
      {/* The greeting */}
      <section className="panel relative overflow-hidden !p-6 sm:!p-8" style={{ backgroundImage: 'var(--orion-highlight-fill)' }}>
        <span className="lumen-orb pointer-events-none absolute -right-10 -top-12 h-52 w-52 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
        <span className="lumen-orb pointer-events-none absolute bottom-[-4rem] right-1/3 h-40 w-40 rounded-full bg-white/15 blur-2xl [animation-delay:-3s]" aria-hidden="true" />
        <div className="relative flex flex-wrap items-center gap-5">
          {user && <UserAvatar user={user} size="lg" className="hidden ring-4 ring-white/30 sm:inline-flex" />}
          <div className="min-w-0 flex-1 text-[color:var(--orion-on-primary)]">
            <p className="flex items-center gap-2 text-sm font-semibold opacity-90">
              <CalendarDays className="h-4 w-4" aria-hidden="true" /> {day}
            </p>
            <h1 className="font-display mt-1 text-3xl font-semibold leading-tight sm:text-4xl">
              {greeting()}, {first}.
            </h1>
            <p className="mt-1 max-w-xl text-sm opacity-90 sm:text-base">
              {mine === null ? 'Looking at your day…' : attention > 0 ? `${attention} ${attention === 1 ? 'thing needs' : 'things need'} you today. Let’s get through them.` : 'Nothing is waiting on you. A good day to get ahead.'}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/tasks/mine?new=1" className="interactive inline-flex h-11 items-center gap-2 rounded-full bg-white px-5 text-sm font-bold text-ink shadow-raised hover:-translate-y-0.5">
              <Plus className="h-4 w-4" /> New task
            </Link>
            {assistant.enabled && (
              <button type="button" onClick={() => assistant.setOpen(true)} className="interactive inline-flex h-11 items-center gap-2 rounded-full border border-white/40 bg-white/15 px-5 text-sm font-bold text-[color:var(--orion-on-primary)] backdrop-blur hover:bg-white/25">
                <Sparkles className="h-4 w-4" /> Ask the Copilot
              </button>
            )}
          </div>
        </div>
      </section>

      {/* The pulse */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Your numbers">
        <Tile label="Due today" value={mine?.counts.today ?? 0} hint="your tasks" to="/tasks/mine" hue="amber" />
        <Tile label="Overdue" value={mine?.counts.overdue ?? 0} hint={mine?.counts.overdue ? 'start with these' : 'all clear'} to="/tasks/mine" hue="coral" />
        <Tile label="To review" value={mine?.counts.to_review ?? 0} hint="waiting for you" to="/tasks/mine" hue="violet" />
        {canBill && owed !== null ? (
          <Tile label="Clients owe" value={owed} format={(n) => inr(n)} hint="open receivables" to="/utility/receivables" hue="green" />
        ) : (
          <Tile label="Unread messages" value={unread} hint="in your chats" to={last.messages} hue="cyan" />
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* My day */}
        <section className="panel space-y-4 !p-6 lg:col-span-3" aria-label="My day">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-display flex items-center gap-2 text-xl font-semibold">
              <Sun className="h-5 w-5 text-amber" aria-hidden="true" /> My day
            </h2>
            <Link to="/tasks/todo" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
              All my lists <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          {error && <p className="text-sm text-negative">{error}</p>}
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              void addToDay()
            }}
          >
            <input value={text} maxLength={300} onChange={(e) => setText(e.target.value)} placeholder="What do you want to get done today?" aria-label="Add to my day" className="h-11 min-h-0 w-full rounded-full px-4 text-sm" />
            <button type="submit" disabled={!text.trim()} className="btn-primary interactive grid h-11 w-11 shrink-0 place-items-center rounded-full disabled:opacity-50" aria-label="Add">
              <Plus className="h-5 w-5" />
            </button>
          </form>
          <ul className="space-y-1.5">
            {myDay.map((item) => (
              <li key={item.id} className="group flex items-center gap-3 rounded-2xl px-2 py-2 hover:bg-muted/60">
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={item.done}
                  aria-label={item.done ? `Mark “${item.text}” not done` : `Done: ${item.text}`}
                  onClick={(e) => void tick(item.id, !item.done, e.currentTarget)}
                  className={`interactive grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 ${item.done ? 'border-transparent bg-primary text-on-primary' : 'border-[color:var(--color-border-strong)] hover:border-[color:var(--color-accent)]'}`}
                >
                  {item.done && <Check className="h-3.5 w-3.5" strokeWidth={3} />}
                </button>
                <span className={`min-w-0 flex-1 truncate text-[15px] ${item.done ? 'text-[color:var(--color-text-faint)] line-through' : 'font-medium'}`}>{item.text}</span>
                {item.task && (
                  <button type="button" onClick={() => navigate(`/tasks/mine?task=${item.task!.key}`)} className="shrink-0 rounded-full bg-accent-dim px-2 py-0.5 text-[11px] font-bold text-accent hover:underline">
                    {item.task.key}
                  </button>
                )}
              </li>
            ))}
            {todo && myDay.length === 0 && <li className="rounded-2xl bg-muted/50 px-4 py-6 text-center text-sm text-[color:var(--color-text-muted)]">Nothing planned yet. Add what you want to finish today.</li>}
            {!todo && !error && <li className="px-2 py-6 text-center text-sm text-[color:var(--color-text-faint)]">Loading…</li>}
          </ul>
          {open.length === 0 && myDay.length > 0 && <p className="text-center text-sm font-semibold text-positive">Everything planned for today is done. 🎉</p>}
        </section>

        {/* Tasks that need you */}
        <section className="panel space-y-3 !p-6 lg:col-span-2" aria-label="Tasks that need you">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-display text-xl font-semibold">Needs you</h2>
            <Link to="/tasks/mine" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
              My work <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <ul className="space-y-1">
            {[...(mine?.to_review ?? []), ...dueToday].slice(0, 6).map((task) => (
              <li key={task.key}>
                <Link to={`/tasks/mine?task=${task.key}`} className="interactive flex items-center gap-3 rounded-2xl px-2 py-2 hover:bg-muted/60">
                  <KindIcon kind={task.type} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{task.title}</span>
                    <span className="t-caption block truncate">{task.key} · {task.status.category === 'review' ? 'review it' : task.project_name}</span>
                  </span>
                  <DueLabel due={task.due_date} overdue={task.overdue} done={false} />
                </Link>
              </li>
            ))}
            {mine && attention === 0 && <li className="rounded-2xl bg-muted/50 px-4 py-6 text-center text-sm text-[color:var(--color-text-muted)]">No task is late or due today.</li>}
          </ul>
          {mine && mine.raised.length + mine.buckets.week.length > 0 && <p className="t-caption text-[color:var(--color-text-faint)]">{mine.buckets.week.length} more due this week · {mine.raised.length} raised by you</p>}
        </section>
      </div>

      {/* Every space */}
      <section aria-label="Spaces">
        <h2 className="font-display mb-3 text-xl font-semibold">Your spaces</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {areas.map((item) => {
            const Icon = item.icon
            return (
              <Link key={item.area} to={last[item.area]} style={{ '--hue': hueVar(item.area) } as React.CSSProperties} className="panel data-hot lumen-dock-item group flex items-center gap-4 !p-4">
                <span className="lumen-chip grid h-12 w-12 shrink-0 place-items-center rounded-2xl">
                  <Icon className="h-6 w-6" />
                </span>
                <span className="min-w-0">
                  <span className="font-display block truncate text-base font-semibold">{item.label}</span>
                  <span className="t-caption line-clamp-2">{AREA_BLURB[item.area]}</span>
                </span>
              </Link>
            )
          })}
        </div>
      </section>
    </div>
  )
}
