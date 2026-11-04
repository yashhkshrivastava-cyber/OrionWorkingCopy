import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ChevronLeft, Lock } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { BoardView } from '../../components/tasks/BoardView'
import { CalendarView } from '../../components/tasks/CalendarView'
import { FilterBar } from '../../components/tasks/FilterBar'
import { ListView } from '../../components/tasks/ListView'
import { ProjectSettings } from '../../components/tasks/ProjectSettings'
import { SprintsView } from '../../components/tasks/SprintsView'
import { TemplatesView } from '../../components/tasks/TemplatesView'
import { Alert, Badge } from '../../components/ui/Alert'
import { Skeleton } from '../../components/ui/EmptyState'
import { Tabs } from '../../components/ui/Tabs'
import { useTasks } from '../../context/TasksContext'
import { errorText } from '../../tasks/taskUi'
import { useTaskPeople } from '../../tasks/useTaskPeople'
import type { TaskFilters, TaskProject } from '../../types'

type View = 'board' | 'list' | 'sprints' | 'calendar' | 'templates' | 'settings'

/** One project: its board, list, sprints, calendar, repeating templates and settings. The view and the filters are kept in the address so a page can be shared or reloaded. */
export function ProjectPage() {
  const { key = '' } = useParams()
  const { version } = useTasks()
  const [params, setParams] = useSearchParams()
  const [project, setProject] = useState<TaskProject | null>(null)
  const [error, setError] = useState('')
  const people = useTaskPeople(key)
  const view = (params.get('view') as View) || 'board'

  const filters: TaskFilters = {}
  for (const name of ['q', 'assignee', 'priority', 'type', 'due'] as const) {
    const value = params.get(name)
    if (value) filters[name] = value
  }

  const load = useCallback(async () => {
    try {
      setProject(await tasksApi.project(key))
      setError('')
    } catch (e) {
      setError(errorText(e, 'The project could not be opened.'))
    }
  }, [key])

  useEffect(() => {
    setProject(null)
    void load()
  }, [load])
  useEffect(() => {
    if (project) void load()
    // only when something changed elsewhere in the workspace; the project itself is already loaded
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version])

  const change = (patch: Record<string, string | null>) =>
    setParams(
      (now) => {
        const next = new URLSearchParams(now)
        for (const [name, value] of Object.entries(patch)) {
          if (value) next.set(name, value)
          else next.delete(name)
        }
        return next
      },
      { replace: true },
    )

  if (error) return <Alert variant="error">{error}</Alert>
  if (!project)
    return (
      <div className="space-y-3">
        <Skeleton className="h-14" />
        <Skeleton className="h-64" />
      </div>
    )

  const manager = project.role === 'Manager'
  const canWork = (project.role === 'Manager' || project.role === 'Member') && project.state === 'Active'
  const tabs: { id: View; label: string }[] = [
    { id: 'board', label: 'Board' },
    { id: 'list', label: 'List' },
    { id: 'sprints', label: 'Sprints' },
    { id: 'calendar', label: 'Calendar' },
    { id: 'templates', label: 'Repeating & templates' },
    ...(manager ? [{ id: 'settings' as const, label: 'Settings' }] : []),
  ]
  const filtered = view === 'board' || view === 'list' || view === 'calendar'

  return (
    <div className="space-y-4">
      <div>
        <Link to="/tasks/projects" className="interactive mb-2 inline-flex items-center gap-1 text-xs font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
          <ChevronLeft className="h-3.5 w-3.5" /> All projects
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-lg bg-accent-dim px-2.5 py-1 text-sm font-bold text-accent">{project.key}</span>
          <h2 className="t-h2">{project.name}</h2>
          {project.visibility === 'Private' && (
            <Badge variant="violet">
              <Lock className="mr-1 inline h-3 w-3" />
              Private
            </Badge>
          )}
          {project.state === 'Archived' && <Badge variant="amber">Archived · read-only</Badge>}
          {project.require_review && <Badge variant="cyan">Review required</Badge>}
          <span className="t-small text-[color:var(--color-text-muted)]">
            {project.members.length} {project.members.length === 1 ? 'person' : 'people'} · you are {project.role === 'Manager' ? 'a manager' : project.role === 'Member' ? 'a member' : 'a viewer'}
          </span>
        </div>
        {project.description && <p className="t-small mt-1 max-w-3xl text-[color:var(--color-text-muted)]">{project.description}</p>}
      </div>

      <Tabs label="Project views" active={view} onChange={(id) => change({ view: id === 'board' ? null : id })} tabs={tabs} />

      {filtered && <FilterBar value={filters} onChange={(next) => change({ q: next.q ?? null, assignee: next.assignee ?? null, priority: next.priority ?? null, type: next.type ?? null, due: next.due ?? null })} people={people} project={project.key} canShare={manager} onError={setError} />}

      {view === 'board' && <BoardView project={project.key} filters={filters} canWork={canWork} />}
      {view === 'list' && <ListView project={project.key} filters={filters} />}
      {view === 'sprints' && <SprintsView project={project.key} canManage={manager && project.state === 'Active'} canWork={canWork} />}
      {view === 'calendar' && <CalendarView project={project.key} filters={filters} />}
      {view === 'templates' && <TemplatesView project={project.key} canManage={manager && project.state === 'Active'} canWork={canWork} />}
      {view === 'settings' && manager && <ProjectSettings project={project} onChanged={setProject} />}
    </div>
  )
}
