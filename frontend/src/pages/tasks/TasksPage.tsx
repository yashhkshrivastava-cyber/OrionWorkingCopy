import { useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Search } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { NewTaskModal } from '../../components/tasks/NewTaskModal'
import { TaskDrawer } from '../../components/tasks/TaskDrawer'
import { Button } from '../../components/ui/Button'
import { PageHeader } from '../../components/ui/PageHeader'
import { Tabs } from '../../components/ui/Tabs'
import { useTasks } from '../../context/TasksContext'
import { KindIcon, StatusPill } from '../../tasks/taskUi'
import type { TaskSearchResult } from '../../types'

type Section = 'mine' | 'todo' | 'projects' | 'reports' | 'inbox'

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'mine', label: 'My work' },
  { id: 'todo', label: 'To-do lists' },
  { id: 'projects', label: 'Projects' },
  { id: 'reports', label: 'Reports' },
  { id: 'inbox', label: 'Notifications' },
]

function sectionOf(pathname: string): Section {
  const part = pathname.split('/')[2]
  return (SECTIONS.find((s) => s.id === part)?.id ?? 'mine') as Section
}

/** The quick finder: type a task key or a few words of a title or project name. */
function Finder({ onOpen, onProject }: { onOpen: (key: string) => void; onProject: (key: string) => void }) {
  const [text, setText] = useState('')
  const [found, setFound] = useState<TaskSearchResult | null>(null)
  const [shown, setShown] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (text.trim().length < 2) {
      setFound(null)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      tasksApi
        .search(text.trim())
        .then((result) => !cancelled && setFound(result))
        .catch(() => !cancelled && setFound(null))
    }, 220)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [text])

  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setShown(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [])

  return (
    <div ref={box} className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
      <input
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setShown(true)
        }}
        onFocus={() => setShown(true)}
        onKeyDown={(e) => e.key === 'Escape' && setShown(false)}
        placeholder="Find a task or project"
        aria-label="Find a task or project"
        className="h-9 w-full rounded-lg border border-[color:var(--color-border-strong)] bg-surface pl-9 pr-3 text-sm text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] focus:border-accent focus:ring-[3px] focus:ring-[color:var(--orion-ring)]"
      />
      {shown && found && (found.tasks.length > 0 || found.projects.length > 0) && (
        <div className="overlay absolute right-0 top-full z-40 mt-1 max-h-96 w-[min(26rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border border-[color:var(--color-border)] p-1.5">
          {found.projects.map((p) => (
            <button
              key={p.key}
              type="button"
              className="interactive flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-muted"
              onClick={() => {
                setShown(false)
                setText('')
                onProject(p.key)
              }}
            >
              <span className="rounded bg-accent-dim px-1.5 py-0.5 text-[11px] font-bold text-accent">{p.key}</span>
              <span className="min-w-0 flex-1 truncate text-sm">{p.name}</span>
              <span className="text-xs text-[color:var(--color-text-faint)]">Project</span>
            </button>
          ))}
          {found.tasks.map((t) => (
            <button
              key={t.key}
              type="button"
              className="interactive flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-muted"
              onClick={() => {
                setShown(false)
                setText('')
                onOpen(t.key)
              }}
            >
              <KindIcon kind={t.type} />
              <span className="shrink-0 text-xs font-medium text-[color:var(--color-text-muted)]">{t.key}</span>
              <span className="min-w-0 flex-1 truncate text-sm">{t.title}</span>
              <StatusPill name={t.status.name} category={t.status.category} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** The task workspace: the page frame, its sections, the "new task" form, and the task drawer that opens over any of them (the `task` part of the address). */
export function TasksPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { me } = useTasks()
  const [creating, setCreating] = useState(false)
  const section = sectionOf(location.pathname)
  const openKey = params.get('task')
  const wantsNew = params.get('new')

  // "New task" from anywhere else in the application arrives as ?new=1: open the form and tidy the address.
  useEffect(() => {
    if (!wantsNew) return
    setCreating(true)
    setParams(
      (now) => {
        const next = new URLSearchParams(now)
        next.delete('new')
        return next
      },
      { replace: true },
    )
  }, [wantsNew, setParams])
  const project = location.pathname.startsWith('/tasks/projects/') ? location.pathname.split('/')[3] : undefined

  const open = (key: string) =>
    setParams(
      (now) => {
        const next = new URLSearchParams(now)
        next.set('task', key)
        return next
      },
      { replace: false },
    )
  const close = () =>
    setParams(
      (now) => {
        const next = new URLSearchParams(now)
        next.delete('task')
        return next
      },
      { replace: true },
    )

  return (
    <div>
      <PageHeader
        eyebrow="Team"
        title="Tasks"
        subtitle="Plan work, give it to people, review it and keep your own to-do list in one place."
        action={
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Finder onOpen={open} onProject={(key) => navigate(`/tasks/projects/${key}`)} />
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> New task
            </Button>
          </div>
        }
      />

      <Tabs
        label="Task sections"
        active={section}
        onChange={(id) => navigate(`/tasks/${id}`)}
        tabs={SECTIONS.map((s) => ({ id: s.id, label: s.id === 'inbox' && me.unread ? `${s.label} (${me.unread})` : s.id === 'mine' && me.attention ? `${s.label} (${me.attention})` : s.label }))}
      />

      <div className="pt-5">
        <Outlet context={{ openTask: open }} />
      </div>

      <TaskDrawer taskKey={openKey} onClose={close} onOpen={open} />
      <NewTaskModal
        open={creating}
        project={project}
        onClose={() => setCreating(false)}
        onCreated={(made) => {
          setCreating(false)
          open(made.key)
        }}
      />
    </div>
  )
}
