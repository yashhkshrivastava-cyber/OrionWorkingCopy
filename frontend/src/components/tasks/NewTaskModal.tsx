import { useEffect, useMemo, useRef, useState } from 'react'
import { tasksApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { useTasks } from '../../context/TasksContext'
import { errorText, KINDS, PRIORITIES, parseDuration } from '../../tasks/taskUi'
import { useTaskPeople } from '../../tasks/useTaskPeople'
import type { TaskDetail, TaskInput, TaskKind, TaskPriority, TaskProject, TaskProjectSummary, TaskSprint } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MultiSelect } from '../ui/MultiSelect'
import { PersonSelect } from './PersonSelect'

/**
 * The form that makes a task. One key is made when the form opens and sent with every attempt, so a double click or a retry makes one task, not two.
 * `parentKey` makes it a sub-task; `defaults` fills in what the caller already knows (a status from a board column, a sprint, a due date from the calendar).
 */
export function NewTaskModal({
  open,
  onClose,
  project: fixedProject,
  parentKey,
  defaults,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  project?: string
  parentKey?: string
  defaults?: Partial<TaskInput>
  onCreated: (task: TaskDetail) => void
}) {
  const { changed } = useTasks()
  const [projects, setProjects] = useState<TaskProjectSummary[]>([])
  const [projectKey, setProjectKey] = useState(fixedProject ?? '')
  const [detail, setDetail] = useState<TaskProject | null>(null)
  const [sprints, setSprints] = useState<TaskSprint[]>([])
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [kind, setKind] = useState<TaskKind>(parentKey ? 'Sub-task' : 'Task')
  const [priority, setPriority] = useState<TaskPriority>('Medium')
  const [assignee, setAssignee] = useState<number | null>(null)
  const [reviewer, setReviewer] = useState<number | null>(null)
  const [due, setDue] = useState('')
  const [estimate, setEstimate] = useState('')
  const [points, setPoints] = useState('')
  const [labels, setLabels] = useState<string[]>([])
  const [statusId, setStatusId] = useState<string>('')
  const [sprintId, setSprintId] = useState<string>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const key = useRef(newIdempotencyKey())
  const sending = useRef(false)
  const people = useTaskPeople(projectKey || null)
  // The caller may pass a new object every render; only a change in what it says resets the form.
  const defaultsKey = JSON.stringify(defaults ?? {})

  // A fresh form: a new key, and what the caller knows.
  useEffect(() => {
    if (!open) return
    key.current = newIdempotencyKey()
    sending.current = false
    const defaults = JSON.parse(defaultsKey) as Partial<TaskInput>
    setTitle(defaults?.title ?? '')
    setDescription(defaults?.description ?? '')
    setKind(defaults?.type ?? (parentKey ? 'Sub-task' : 'Task'))
    setPriority(defaults?.priority ?? 'Medium')
    setAssignee(defaults?.assignee_id ?? null)
    setReviewer(defaults?.reviewer_id ?? null)
    setDue(defaults?.due_date ?? '')
    setEstimate('')
    setPoints('')
    setLabels(defaults?.labels ?? [])
    setStatusId(defaults?.status_id ? String(defaults.status_id) : '')
    setSprintId(defaults?.sprint_id ? String(defaults.sprint_id) : '')
    setError('')
    setBusy(false)
  }, [open, defaultsKey, parentKey])

  useEffect(() => {
    if (!open) return
    if (fixedProject) {
      setProjectKey(fixedProject)
      return
    }
    tasksApi
      .projects()
      .then((found) => {
        const usable = found.projects.filter((p) => p.state === 'Active' && p.role !== 'Viewer')
        setProjects(usable)
        setProjectKey((now) => (now && usable.some((p) => p.key === now) ? now : (usable[0]?.key ?? '')))
      })
      .catch((e) => setError(errorText(e)))
  }, [open, fixedProject])

  useEffect(() => {
    if (!open || !projectKey) return
    let cancelled = false
    Promise.all([tasksApi.project(projectKey), tasksApi.sprints(projectKey).catch(() => ({ sprints: [] as TaskSprint[] }))])
      .then(([found, sp]) => {
        if (cancelled) return
        setDetail(found)
        setSprints(sp.sprints.filter((s) => s.state !== 'Completed'))
      })
      .catch((e) => !cancelled && setError(errorText(e)))
    return () => {
      cancelled = true
    }
  }, [open, projectKey])

  const statuses = useMemo(() => detail?.statuses ?? [], [detail])

  const save = async () => {
    if (sending.current) return
    const minutes = estimate.trim() ? parseDuration(estimate) : null
    if (estimate.trim() && minutes === null) return setError('Write the estimate like 90, 1h 30m or 2d.')
    if (!title.trim()) return setError('Give the task a title.')
    if (!projectKey) return setError('Choose the project the task belongs to.')
    sending.current = true
    setBusy(true)
    setError('')
    try {
      const body: TaskInput = {
        title: title.trim(),
        description: description.trim() || null,
        type: kind,
        priority,
        assignee_id: assignee,
        reviewer_id: reviewer,
        due_date: due || null,
        estimate_minutes: minutes,
        story_points: points.trim() ? Number(points) : null,
        labels,
        status_id: statusId ? Number(statusId) : null,
        sprint_id: sprintId ? Number(sprintId) : null,
        parent_key: parentKey ?? null,
        records: (JSON.parse(defaultsKey) as Partial<TaskInput>).records,
        checklist: (JSON.parse(defaultsKey) as Partial<TaskInput>).checklist,
      }
      const made = await tasksApi.create(projectKey, body, key.current)
      changed()
      onCreated(made)
    } catch (e) {
      setError(errorText(e))
      sending.current = false
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={parentKey ? `New sub-task of ${parentKey}` : 'New task'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={busy} onClick={() => void save()}>
            Create task
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          void save()
        }}
      >
        {error && <Alert variant="error">{error}</Alert>}

        {!fixedProject && !parentKey && (
          <Field label="Project" required>
            <Select value={projectKey} onChange={(e) => setProjectKey(e.target.value)} aria-label="Project">
              {projects.length === 0 && <option value="">No project you can add tasks to</option>}
              {projects.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.key} · {p.name}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <Field label="Title" required>
          <Input autoFocus value={title} maxLength={250} onChange={(e) => setTitle(e.target.value)} placeholder="What needs to be done?" />
        </Field>

        <Field label="Description" hint="You can use **bold**, lists and links.">
          <Textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Details, steps, what done looks like…" />
        </Field>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Type">
            <Select value={kind} onChange={(e) => setKind(e.target.value as TaskKind)} aria-label="Type">
              {KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </Select>
          </Field>
          <Field label="Priority">
            <Select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)} aria-label="Priority">
              {PRIORITIES.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
          </Field>
          <Field label="Status">
            <Select value={statusId} onChange={(e) => setStatusId(e.target.value)} aria-label="Status">
              <option value="">First status</option>
              {statuses.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Assignee">
            <PersonSelect people={people} value={assignee} onChange={setAssignee} />
          </Field>
          <Field label="Reviewer" hint="Who checks it when it is done.">
            <PersonSelect people={people} value={reviewer} onChange={setReviewer} emptyLabel="Chosen later" />
          </Field>
          <Field label="Due date">
            <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </Field>
          <Field label="Estimate" hint="For example 90, 1h 30m, 2d.">
            <Input value={estimate} onChange={(e) => setEstimate(e.target.value)} placeholder="1h 30m" />
          </Field>
          <Field label="Story points">
            <Input type="number" min={0} max={1000} step="0.5" value={points} onChange={(e) => setPoints(e.target.value)} />
          </Field>
          {sprints.length > 0 && (
            <Field label="Sprint">
              <Select value={sprintId} onChange={(e) => setSprintId(e.target.value)} aria-label="Sprint">
                <option value="">Backlog</option>
                {sprints.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.state})
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>

        <MultiSelect label="Labels" values={labels} onChange={setLabels} options={[]} allowCustom separator={/,/} noun={['label', 'labels']} placeholder="Add labels" max={12} />
      </form>
    </Modal>
  )
}
