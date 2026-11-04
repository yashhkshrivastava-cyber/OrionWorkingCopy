import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Flag, Pencil, Play, Plus } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { errorText, formatDay, KindIcon, Person, PriorityMark, StatusPill } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskBurndown, TaskCard, TaskSprint } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'

type Group = { sprint: TaskSprint | null; tasks: TaskCard[] }

function Burndown({ data }: { data: TaskBurndown }) {
  const w = 360
  const h = 110
  const max = Math.max(data.points, 1)
  const n = Math.max(data.days.length - 1, 1)
  const x = (i: number) => 8 + (i / n) * (w - 16)
  const y = (v: number) => 8 + (1 - v / max) * (h - 16)
  const ideal = data.days.map((d, i) => `${x(i)},${y(d.ideal)}`).join(' ')
  const left = data.days.flatMap((d, i) => (d.left === null ? [] : [`${x(i)},${y(d.left)}`])).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Work left each day against the ideal line" className="w-full max-w-md">
      <polyline points={ideal} fill="none" stroke="var(--color-text-faint)" strokeDasharray="4 4" strokeWidth="1.5" />
      <polyline points={left} fill="none" stroke="var(--color-accent)" strokeWidth="2" />
    </svg>
  )
}

/** Planning in sprints: put tasks into a short stretch of work with a goal, start it, watch it burn down, complete it (what is left goes back or on). */
export function SprintsView({ project, canManage, canWork }: { project: string; canManage: boolean; canWork: boolean }) {
  const { version, changed } = useTasks()
  const open = useOpenTask()
  const [sprints, setSprints] = useState<TaskSprint[] | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [burn, setBurn] = useState<TaskBurndown | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Partial<TaskSprint> | null>(null)
  const [completing, setCompleting] = useState<TaskSprint | null>(null)
  const [moveTo, setMoveTo] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const found = (await tasksApi.sprints(project)).sprints
      setSprints(found)
      const live = found.filter((s) => s.state !== 'Completed')
      const lists = await Promise.all([
        tasksApi.list({ project, sprint: 'none', open: 'true', limit: '200', sort: 'rank' }),
        ...live.map((s) => tasksApi.list({ project, sprint: String(s.id), limit: '200', sort: 'rank' })),
      ])
      setGroups([...live.map((s, i) => ({ sprint: s, tasks: lists[i + 1].tasks })), { sprint: null, tasks: lists[0].tasks }])
      const active = found.find((s) => s.state === 'Active')
      setBurn(active ? await tasksApi.burndown(project, active.id) : null)
      setError('')
    } catch (e) {
      setError(errorText(e, 'The sprints could not be loaded.'))
    }
  }, [project])

  useEffect(() => {
    void load()
  }, [load, version])

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await work()
      changed()
      await load()
      return true
    } catch (e) {
      setError(errorText(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const planned = sprints?.filter((s) => s.state === 'Planned') ?? []
  const done = sprints?.filter((s) => s.state === 'Completed') ?? []

  const place = (task: TaskCard, value: string) => act(() => tasksApi.update(task.key, { sprint_id: value ? Number(value) : null }))

  return (
    <div className="space-y-5">
      {error && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}
      {canManage && (
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setEditing({ name: `Sprint ${(sprints?.length ?? 0) + 1}` })}>
            <Plus className="h-4 w-4" /> New sprint
          </Button>
        </div>
      )}

      {groups.map((group) => {
        const sprint = group.sprint
        return (
          <section key={sprint?.id ?? 'backlog'} className="panel !p-0 overflow-hidden">
            <header className="flex flex-wrap items-center gap-3 border-b border-[color:var(--color-border)] bg-muted/30 px-4 py-3">
              <Flag className={`h-4 w-4 ${sprint?.state === 'Active' ? 'text-accent' : 'text-[color:var(--color-text-faint)]'}`} />
              <div className="min-w-0 flex-1">
                <h3 className="t-h3">{sprint ? sprint.name : 'Backlog'}</h3>
                <p className="t-caption text-[color:var(--color-text-muted)]">
                  {sprint
                    ? `${sprint.state}${sprint.start_date ? ` · ${formatDay(sprint.start_date)} – ${formatDay(sprint.end_date)}` : ''}${sprint.state === 'Active' && sprint.days_left !== null ? ` · ${sprint.days_left < 0 ? `${-sprint.days_left} days over` : `${sprint.days_left} days left`}` : ''}`
                    : 'Work not yet planned into a sprint'}
                  {' · '}
                  {group.tasks.length} task{group.tasks.length === 1 ? '' : 's'}
                  {sprint && sprint.points ? ` · ${sprint.points_done}/${sprint.points} points` : ''}
                </p>
                {sprint?.goal && <p className="mt-1 text-sm text-[color:var(--color-text)]">{sprint.goal}</p>}
              </div>
              {sprint && canManage && (
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" aria-label={`Edit ${sprint.name}`} onClick={() => setEditing(sprint)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  {sprint.state === 'Planned' && (
                    <Button size="sm" loading={busy} onClick={() => void act(() => tasksApi.startSprint(project, sprint.id))}>
                      <Play className="h-3.5 w-3.5" /> Start
                    </Button>
                  )}
                  {sprint.state === 'Active' && (
                    <Button
                      size="sm"
                      onClick={() => {
                        setMoveTo('')
                        setCompleting(sprint)
                      }}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" /> Complete
                    </Button>
                  )}
                </div>
              )}
            </header>
            {sprint?.state === 'Active' && burn && burn.days.length > 1 && (
              <div className="border-b border-[color:var(--color-border)] px-4 py-3">
                <p className="eyebrow mb-1">Burndown</p>
                <Burndown data={burn} />
              </div>
            )}
            {group.tasks.length === 0 ? (
              <p className="px-4 py-5 text-sm text-[color:var(--color-text-muted)]">{sprint ? 'Nothing planned in this sprint yet. Move tasks in from the backlog.' : 'The backlog is empty.'}</p>
            ) : (
              <ul className="divide-y divide-[color:var(--color-border)]">
                {group.tasks.map((task) => (
                  <li key={task.key} className="flex items-center gap-3 px-4 py-2">
                    <KindIcon kind={task.type} />
                    <button type="button" onClick={() => open(task.key)} className="min-w-0 flex-1 truncate text-left text-sm hover:text-accent">
                      <span className="mr-2 text-xs font-medium text-[color:var(--color-text-muted)]">{task.key}</span>
                      <span className={task.status.category === 'done' ? 'text-[color:var(--color-text-faint)] line-through' : ''}>{task.title}</span>
                    </button>
                    {task.story_points !== null && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-[color:var(--color-text-muted)]">{task.story_points}</span>}
                    <PriorityMark priority={task.priority} />
                    <span className="hidden sm:block">
                      <StatusPill name={task.status.name} category={task.status.category} />
                    </span>
                    <Person person={task.assignee} name={false} size="xs" />
                    {canWork && (
                      <Select className="!h-8 !min-h-0 !w-36 !py-0 text-xs" value={sprint?.id ?? ''} onChange={(e) => void place(task, e.target.value)} aria-label={`Sprint of ${task.key}`}>
                        <option value="">Backlog</option>
                        {[...planned, ...(sprints?.filter((s) => s.state === 'Active') ?? [])].map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </Select>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )
      })}

      {done.length > 0 && (
        <section>
          <h3 className="eyebrow mb-2">Finished sprints</h3>
          <ul className="panel divide-y divide-[color:var(--color-border)] !p-0">
            {done.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm">
                <span className="font-medium">{s.name}</span>
                <span className="text-xs text-[color:var(--color-text-muted)]">
                  {formatDay(s.start_date)} – {formatDay(s.end_date)}
                </span>
                <span className="text-xs text-[color:var(--color-text-muted)]">
                  {s.done}/{s.tasks} tasks done{s.points ? ` · ${s.points_done}/${s.points} points` : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Modal
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        title={editing?.id ? 'Edit sprint' : 'New sprint'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button
              loading={busy}
              disabled={!editing?.name?.trim()}
              onClick={async () => {
                if (!editing) return
                const body = { name: editing.name?.trim() ?? '', goal: editing.goal ?? '', start_date: editing.start_date ?? '', end_date: editing.end_date ?? '' }
                const ok = await act(() => (editing.id ? tasksApi.updateSprint(project, editing.id, body) : tasksApi.createSprint(project, body)))
                if (ok) setEditing(null)
              }}
            >
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name" required>
            <Input value={editing?.name ?? ''} maxLength={80} onChange={(e) => setEditing((now) => ({ ...now, name: e.target.value }))} />
          </Field>
          <Field label="Goal" hint="What the team wants to have achieved by the end.">
            <Textarea rows={3} value={editing?.goal ?? ''} maxLength={500} onChange={(e) => setEditing((now) => ({ ...now, goal: e.target.value }))} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Starts">
              <Input type="date" value={editing?.start_date ?? ''} onChange={(e) => setEditing((now) => ({ ...now, start_date: e.target.value }))} />
            </Field>
            <Field label="Ends" hint="Two weeks after the start if left empty.">
              <Input type="date" value={editing?.end_date ?? ''} onChange={(e) => setEditing((now) => ({ ...now, end_date: e.target.value }))} />
            </Field>
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(completing)}
        onClose={() => setCompleting(null)}
        title={`Complete ${completing?.name ?? 'sprint'}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCompleting(null)}>
              Cancel
            </Button>
            <Button
              loading={busy}
              onClick={async () => {
                if (!completing) return
                const ok = await act(() => tasksApi.completeSprint(project, completing.id, moveTo ? Number(moveTo) : null))
                if (ok) setCompleting(null)
              }}
            >
              Complete sprint
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-[color:var(--color-text-muted)]">
            {completing ? `${completing.done} of ${completing.tasks} tasks are done.` : ''} What is not finished can go back to the backlog or on to another sprint.
          </p>
          <Field label="Move unfinished tasks to">
            <Select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} aria-label="Move unfinished tasks to">
              <option value="">Backlog</option>
              {planned.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Modal>
    </div>
  )
}
