import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CalendarDays, Check, ChevronDown, ChevronRight, Inbox, ListPlus, ListTodo, Plus, Sun, Trash2, X } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { EmptyState } from '../../components/ui/EmptyState'
import { Field, Input, Select, Textarea } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { celebrate } from '../../lumen/celebrate'
import { formatDay, errorText } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskProjectSummary, TodoItem, TodoOverview } from '../../types'

type View = 'myday' | 'inbox' | 'week' | number

/** Each person's own lists: private to them, with a "My day" for what they mean to do today. Any item can be turned into a real task. */
export function TodoPage() {
  const open = useOpenTask()
  const [data, setData] = useState<TodoOverview | null>(null)
  const [view, setView] = useState<View>('myday')
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [newList, setNewList] = useState<string | null>(null)
  const [converting, setConverting] = useState<TodoItem | null>(null)
  const [showDone, setShowDone] = useState(false)
  const addKey = useRef(newIdempotencyKey())
  const adding = useRef(false)

  const run = useCallback(async (work: () => Promise<TodoOverview>) => {
    setError('')
    try {
      setData(await work())
      return true
    } catch (e) {
      setError(errorText(e))
      return false
    }
  }, [])

  useEffect(() => {
    void run(() => tasksApi.todo())
  }, [run])

  const items = useMemo(() => {
    if (!data) return []
    return data.items.filter((item) => {
      if (view === 'myday') return item.in_my_day
      if (view === 'inbox') return item.list_id === null
      if (view === 'week') return Boolean(item.due_date && item.due_date <= data.week)
      return item.list_id === view
    })
  }, [data, view])

  const open_ = items.filter((i) => !i.done)
  const done_ = items.filter((i) => i.done)
  const listName = data && typeof view === 'number' ? data.lists.find((l) => l.id === view)?.name : undefined
  const title = view === 'myday' ? 'My day' : view === 'inbox' ? 'Inbox' : view === 'week' ? 'Next 7 days' : (listName ?? 'List')

  const add = async () => {
    const value = text.trim()
    if (!value || adding.current || !data) return
    adding.current = true
    const ok = await run(() =>
      tasksApi.addTodo(
        { text: value, list_id: typeof view === 'number' ? view : null, my_day: view === 'myday' ? data.today : null, due_date: view === 'week' ? data.today : null },
        addKey.current,
      ),
    )
    if (ok) {
      setText('')
      addKey.current = newIdempotencyKey()
    }
    adding.current = false
  }

  const nav = (id: View, label: string, icon: ReactNode, count?: number) => (
    <button
      key={String(id)}
      type="button"
      onClick={() => setView(id)}
      aria-current={view === id ? 'page' : undefined}
      className={`interactive flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm ${view === id ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]'}`}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count ? <span className="text-xs tabular-nums text-[color:var(--color-text-faint)]">{count}</span> : null}
    </button>
  )

  if (!data) return error ? <Alert variant="error">{error}</Alert> : <p className="text-sm text-[color:var(--color-text-faint)]">Loading…</p>

  return (
    <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="space-y-1">
        {nav('myday', 'My day', <Sun className="h-4 w-4" />, data.my_day_open)}
        {nav('week', 'Next 7 days', <CalendarDays className="h-4 w-4" />)}
        {nav('inbox', 'Inbox', <Inbox className="h-4 w-4" />, data.inbox_open)}
        <p className="eyebrow px-3 pb-1 pt-4">My lists</p>
        {data.lists.map((list) => nav(list.id, list.name, <ListTodo className="h-4 w-4" />, list.open))}
        {newList === null ? (
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={() => setNewList('')}>
            <ListPlus className="h-4 w-4" /> New list
          </Button>
        ) : (
          <form
            className="flex gap-1 px-1"
            onSubmit={(event) => {
              event.preventDefault()
              if (!newList.trim()) return
              void run(() => tasksApi.createTodoList(newList.trim())).then((ok) => ok && setNewList(null))
            }}
          >
            <Input autoFocus value={newList} maxLength={60} onChange={(e) => setNewList(e.target.value)} placeholder="List name" aria-label="List name" />
            <Button type="button" variant="ghost" size="sm" aria-label="Cancel" onClick={() => setNewList(null)}>
              <X className="h-4 w-4" />
            </Button>
          </form>
        )}
      </aside>

      <section className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="t-h2">{title}</h2>
            {view === 'myday' && <p className="t-small text-[color:var(--color-text-muted)]">{formatDay(data.today)} · what you mean to do today</p>}
            {typeof view === 'number' && <p className="t-small text-[color:var(--color-text-muted)]">Only you can see this list.</p>}
          </div>
          <div className="flex gap-2">
            {typeof view === 'number' && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const name = window.prompt('Rename the list', listName)
                    if (name?.trim()) void run(() => tasksApi.renameTodoList(view, name.trim()))
                  }}
                >
                  Rename
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(`Delete the list “${listName}” and everything in it?`)) void run(() => tasksApi.deleteTodoList(view)).then(() => setView('inbox'))
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </Button>
              </>
            )}
            {done_.length > 0 && (
              <Button size="sm" variant="secondary" onClick={() => void run(() => tasksApi.clearTodo(typeof view === 'number' ? view : view === 'inbox' ? 'inbox' : undefined))}>
                Clear finished
              </Button>
            )}
          </div>
        </div>

        {error && (
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        )}

        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void add()
          }}
        >
          <Input value={text} maxLength={300} onChange={(e) => setText(e.target.value)} placeholder={view === 'myday' ? 'Add something to do today…' : 'Add a to-do…'} aria-label="New to-do" />
          <Button type="submit" disabled={!text.trim()}>
            <Plus className="h-4 w-4" /> Add
          </Button>
        </form>

        {open_.length === 0 && done_.length === 0 && (
          <EmptyState compact icon={ListTodo} title="Nothing here yet">
            {view === 'myday' ? 'Add what you want to get done today, or move things here from your lists with the sun.' : 'Type above and press Enter.'}
          </EmptyState>
        )}

        <ul className="space-y-1.5">
          {open_.map((item) => (
            <TodoRow key={item.id} item={item} lists={data.lists} today={data.today} expanded={expanded === item.id} onExpand={() => setExpanded(expanded === item.id ? null : item.id)} run={run} onConvert={() => setConverting(item)} onOpenTask={open} />
          ))}
        </ul>

        {done_.length > 0 && (
          <div>
            <button type="button" onClick={() => setShowDone((v) => !v)} className="interactive mb-1.5 flex items-center gap-1 text-xs font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
              {showDone ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} Finished · {done_.length}
            </button>
            {showDone && (
              <ul className="space-y-1.5">
                {done_.map((item) => (
                  <TodoRow key={item.id} item={item} lists={data.lists} today={data.today} expanded={false} onExpand={() => undefined} run={run} onConvert={() => undefined} onOpenTask={open} />
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <ConvertDialog
        item={converting}
        onClose={() => setConverting(null)}
        onDone={(overview, key) => {
          setData(overview)
          setConverting(null)
          open(key)
        }}
      />
    </div>
  )
}

function TodoRow({
  item,
  lists,
  today,
  expanded,
  onExpand,
  run,
  onConvert,
  onOpenTask,
}: {
  item: TodoItem
  lists: TodoOverview['lists']
  today: string
  expanded: boolean
  onExpand: () => void
  run: (work: () => Promise<TodoOverview>) => Promise<boolean>
  onConvert: () => void
  onOpenTask: (key: string) => void
}) {
  const [text, setText] = useState(item.text)
  const [notes, setNotes] = useState(item.notes ?? '')
  useEffect(() => {
    setText(item.text)
    setNotes(item.notes ?? '')
  }, [item.text, item.notes])

  return (
    <li className="panel !p-0">
      <div className="flex items-center gap-2.5 px-3 py-2">
        <input type="checkbox" className="h-4 w-4 accent-[color:var(--color-primary)]" checked={item.done} aria-label={`Finished: ${item.text}`} onChange={(e) => {
            if (e.target.checked) celebrate(e.target)
            void run(() => tasksApi.updateTodo(item.id, { done: e.target.checked }))
          }}
        />
        <button type="button" onClick={onExpand} className={`min-w-0 flex-1 truncate text-left text-sm ${item.done ? 'text-[color:var(--color-text-faint)] line-through' : 'text-[color:var(--color-text)]'}`}>
          {item.text}
        </button>
        {item.task && (
          <button type="button" onClick={() => onOpenTask(item.task!.key)} className="shrink-0 rounded bg-accent-dim px-1.5 py-0.5 text-[11px] font-bold text-accent hover:underline">
            {item.task.key}
          </button>
        )}
        {item.due_date && <span className={`shrink-0 text-xs ${item.overdue ? 'font-semibold text-negative' : item.due_date === today ? 'font-semibold text-warning' : 'text-[color:var(--color-text-muted)]'}`}>{formatDay(item.due_date)}</span>}
        {!item.done && (
          <button
            type="button"
            aria-label={item.in_my_day ? 'Take out of My day' : 'Add to My day'}
            aria-pressed={item.in_my_day}
            title={item.in_my_day ? 'In My day' : 'Add to My day'}
            onClick={() => void run(() => tasksApi.updateTodo(item.id, { my_day: item.in_my_day ? null : today }))}
            className={`interactive rounded p-1.5 ${item.in_my_day ? 'text-warning' : 'text-[color:var(--color-text-faint)] hover:text-warning'}`}
          >
            <Sun className="h-4 w-4" />
          </button>
        )}
      </div>
      {expanded && (
        <div className="space-y-3 border-t border-[color:var(--color-border)] px-3 py-3">
          <Input value={text} maxLength={300} onChange={(e) => setText(e.target.value)} onBlur={() => text.trim() && text !== item.text && void run(() => tasksApi.updateTodo(item.id, { text: text.trim() }))} aria-label="To-do" />
          <Textarea rows={3} value={notes} maxLength={2000} placeholder="Notes" onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (item.notes ?? '') && void run(() => tasksApi.updateTodo(item.id, { notes: notes.trim() || null }))} aria-label="Notes" />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Due">
              <Input type="date" value={item.due_date ?? ''} onChange={(e) => void run(() => tasksApi.updateTodo(item.id, { due_date: e.target.value || null }))} />
            </Field>
            <Field label="List">
              <Select value={item.list_id ?? ''} onChange={(e) => void run(() => tasksApi.updateTodo(item.id, { list_id: e.target.value ? Number(e.target.value) : null }))} aria-label="List">
                <option value="">Inbox</option>
                {lists.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="flex justify-between gap-2">
            {!item.task ? (
              <Button size="sm" variant="secondary" onClick={onConvert}>
                <Check className="h-3.5 w-3.5" /> Make it a task
              </Button>
            ) : (
              <span />
            )}
            <Button size="sm" variant="ghost" onClick={() => void run(() => tasksApi.deleteTodo(item.id))}>
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}

function ConvertDialog({ item, onClose, onDone }: { item: TodoItem | null; onClose: () => void; onDone: (overview: TodoOverview, key: string) => void }) {
  const [projects, setProjects] = useState<TaskProjectSummary[]>([])
  const [project, setProject] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!item) return
    setError('')
    tasksApi
      .projects()
      .then((found) => {
        const usable = found.projects.filter((p) => p.state === 'Active' && p.role !== 'Viewer')
        setProjects(usable)
        setProject((now) => now || usable[0]?.key || '')
      })
      .catch((e) => setError(errorText(e)))
  }, [item])

  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title="Make it a task"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={busy}
            disabled={!project}
            onClick={async () => {
              if (!item) return
              setBusy(true)
              try {
                const result = await tasksApi.todoToTask(item.id, { project })
                onDone(result.todo, result.task.key)
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            Create task
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && <Alert variant="error">{error}</Alert>}
        <p className="text-sm text-[color:var(--color-text-muted)]">“{item?.text}” becomes a task in the project you choose. It is given to you, and this to-do is ticked off and linked to it.</p>
        <Field label="Project" required>
          <Select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Project">
            {projects.length === 0 && <option value="">No project you can add tasks to</option>}
            {projects.map((p) => (
              <option key={p.key} value={p.key}>
                {p.key} · {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </Modal>
  )
}
