import { useCallback, useEffect, useState } from 'react'
import { Copy, Pencil, Plus, Repeat2, Trash2 } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { errorText, formatDay, KINDS, parseDuration, formatMinutes, PRIORITIES } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import { useTaskPeople } from '../../tasks/useTaskPeople'
import type { TaskKind, TaskPriority, TaskTemplate } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MultiSelect } from '../ui/MultiSelect'
import { PersonSelect } from './PersonSelect'

type Draft = {
  id?: number
  name: string
  title: string
  description: string
  type: TaskKind
  priority: TaskPriority
  assignee: number | null
  reviewer: number | null
  labels: string[]
  checklist: string
  dueOffset: string
  estimate: string
  frequency: '' | 'daily' | 'weekly' | 'monthly' | 'yearly'
  interval: string
  weekday: string
  dayOfMonth: string
  month: string
  start: string
  end: string
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

const blank = (): Draft => ({
  name: '', title: '', description: '', type: 'Task', priority: 'Medium', assignee: null, reviewer: null, labels: [], checklist: '', dueOffset: '0', estimate: '', frequency: '', interval: '1', weekday: '0', dayOfMonth: '1', month: '1', start: '', end: '',
})

const fromTemplate = (t: TaskTemplate): Draft => ({
  id: t.id, name: t.name, title: t.title, description: t.description ?? '', type: t.type, priority: t.priority, assignee: t.assignee?.id ?? null, reviewer: t.reviewer?.id ?? null, labels: t.labels,
  checklist: t.checklist.join('\n'), dueOffset: String(t.due_offset_days), estimate: t.estimate_minutes ? formatMinutes(t.estimate_minutes) : '', frequency: t.frequency ?? '',
  interval: String(t.interval_count || 1), weekday: String(t.weekday ?? 0), dayOfMonth: String(t.day_of_month ?? 1), month: String(t.month_of_year ?? 1), start: t.next_run ?? '', end: t.end_date ?? '',
})

/** Ready-made tasks, and tasks that come back by themselves (every day, week, month or year) with their checklist, owner and due date already filled in. */
export function TemplatesView({ project, canManage, canWork }: { project: string; canManage: boolean; canWork: boolean }) {
  const { changed } = useTasks()
  const open = useOpenTask()
  const people = useTaskPeople(project)
  const [list, setList] = useState<TaskTemplate[] | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setList((await tasksApi.templates(project)).templates)
      setError('')
    } catch (e) {
      setError(errorText(e, 'The templates could not be loaded.'))
    }
  }, [project])
  useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    if (!draft) return
    const minutes = draft.estimate.trim() ? parseDuration(draft.estimate) : null
    if (draft.estimate.trim() && minutes === null) return setError('Write the estimate like 90, 1h 30m or 2d.')
    setBusy(true)
    setError('')
    const repeating = draft.frequency !== ''
    try {
      const body = {
        name: draft.name.trim(),
        title: draft.title.trim(),
        description: draft.description.trim() || null,
        type: draft.type,
        priority: draft.priority,
        assignee_id: draft.assignee,
        reviewer_id: draft.reviewer,
        labels: draft.labels,
        checklist: draft.checklist.split('\n').map((l) => l.trim()).filter(Boolean),
        due_offset_days: Number(draft.dueOffset || 0),
        estimate_minutes: minutes,
        frequency: repeating ? draft.frequency : null,
        interval_count: repeating ? Number(draft.interval || 1) : 1,
        weekday: draft.frequency === 'weekly' ? Number(draft.weekday) : null,
        day_of_month: draft.frequency === 'monthly' || draft.frequency === 'yearly' ? Number(draft.dayOfMonth) : null,
        month_of_year: draft.frequency === 'yearly' ? Number(draft.month) : null,
        next_run: repeating && draft.start ? draft.start : null,
        end_date: repeating && draft.end ? draft.end : null,
        active: true,
      }
      setList((await tasksApi.saveTemplate(project, body, draft.id)).templates)
      setDraft(null)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const set = (patch: Partial<Draft>) => setDraft((now) => (now ? { ...now, ...patch } : now))

  return (
    <div className="space-y-4">
      {error && !draft && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}
      <div className="flex items-center justify-between gap-2">
        <p className="t-small max-w-xl text-[color:var(--color-text-muted)]">Use a template to make the same kind of task quickly, or let it come back on a schedule: each time it is due, the task appears already filled in.</p>
        {canManage && (
          <Button size="sm" onClick={() => setDraft(blank())}>
            <Plus className="h-4 w-4" /> New template
          </Button>
        )}
      </div>

      {list && list.length === 0 && (
        <EmptyState icon={Repeat2} title="No templates yet">
          {canManage ? 'Make one for work that repeats, such as the monthly bill run, the GST return or a site inspection.' : 'A manager of the project can make templates.'}
        </EmptyState>
      )}

      <ul className="grid gap-3 md:grid-cols-2">
        {list?.map((t) => (
          <li key={t.id} className="panel space-y-2 !p-4">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-[color:var(--color-text)]">{t.name}</p>
                <p className="truncate text-sm text-[color:var(--color-text-muted)]">{t.title}</p>
              </div>
              {canManage && (
                <>
                  <Button size="sm" variant="ghost" aria-label={`Edit ${t.name}`} onClick={() => setDraft(fromTemplate(t))}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Delete ${t.name}`}
                    onClick={async () => {
                      if (!window.confirm(`Delete the template “${t.name}”? Tasks already made from it stay.`)) return
                      try {
                        setList((await tasksApi.deleteTemplate(project, t.id)).templates)
                      } catch (e) {
                        setError(errorText(e))
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </>
              )}
            </div>
            <p className="flex items-center gap-1.5 text-xs text-[color:var(--color-text-muted)]">
              <Repeat2 className="h-3.5 w-3.5" />
              {t.frequency ? `${t.schedule}${t.next_run ? ` · next ${formatDay(t.next_run)}` : ''}` : 'Does not repeat'}
            </p>
            {canWork && (
              <Button
                size="sm"
                variant="secondary"
                onClick={async () => {
                  try {
                    const made = await tasksApi.makeFromTemplate(project, t.id)
                    changed()
                    open(made.key)
                  } catch (e) {
                    setError(errorText(e))
                  }
                }}
              >
                <Copy className="h-3.5 w-3.5" /> Make a task now
              </Button>
            )}
          </li>
        ))}
      </ul>

      <Modal
        open={Boolean(draft)}
        onClose={() => setDraft(null)}
        size="xl"
        title={draft?.id ? 'Edit template' : 'New template'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button loading={busy} disabled={!draft?.name.trim() || !draft?.title.trim()} onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        {draft && (
          <div className="space-y-4">
            {error && <Alert variant="error">{error}</Alert>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Template name" required>
                <Input value={draft.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} placeholder="Monthly GST return" />
              </Field>
              <Field label="Task title" required>
                <Input value={draft.title} maxLength={250} onChange={(e) => set({ title: e.target.value })} placeholder="File GST return" />
              </Field>
            </div>
            <Field label="Description">
              <Textarea rows={3} value={draft.description} onChange={(e) => set({ description: e.target.value })} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Type">
                <Select value={draft.type} onChange={(e) => set({ type: e.target.value as TaskKind })} aria-label="Type">
                  {KINDS.filter((k) => k !== 'Sub-task').map((k) => (
                    <option key={k}>{k}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Priority">
                <Select value={draft.priority} onChange={(e) => set({ priority: e.target.value as TaskPriority })} aria-label="Priority">
                  {PRIORITIES.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Estimate">
                <Input value={draft.estimate} onChange={(e) => set({ estimate: e.target.value })} placeholder="2h" />
              </Field>
              <Field label="Assignee">
                <PersonSelect people={people} value={draft.assignee} onChange={(id) => set({ assignee: id })} />
              </Field>
              <Field label="Reviewer">
                <PersonSelect people={people} value={draft.reviewer} onChange={(id) => set({ reviewer: id })} emptyLabel="Chosen later" />
              </Field>
              <Field label="Due after" hint="Days after it is made.">
                <Input type="number" min={0} max={366} value={draft.dueOffset} onChange={(e) => set({ dueOffset: e.target.value })} />
              </Field>
            </div>
            <Field label="Checklist" hint="One step per line.">
              <Textarea rows={4} value={draft.checklist} onChange={(e) => set({ checklist: e.target.value })} />
            </Field>
            <MultiSelect label="Labels" values={draft.labels} onChange={(labels) => set({ labels })} options={[]} allowCustom separator={/,/} noun={['label', 'labels']} placeholder="Labels" max={12} />

            <fieldset className="space-y-3 rounded-xl border border-[color:var(--color-border)] p-4">
              <legend className="eyebrow px-1">Repeat</legend>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="How often">
                  <Select value={draft.frequency} onChange={(e) => set({ frequency: e.target.value as Draft['frequency'] })} aria-label="How often">
                    <option value="">Does not repeat</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                    <option value="yearly">Yearly</option>
                  </Select>
                </Field>
                {draft.frequency && (
                  <Field label="Every" hint={draft.frequency === 'daily' ? 'days' : draft.frequency === 'weekly' ? 'weeks' : draft.frequency === 'monthly' ? 'months' : 'years'}>
                    <Input type="number" min={1} max={52} value={draft.interval} onChange={(e) => set({ interval: e.target.value })} />
                  </Field>
                )}
                {draft.frequency === 'weekly' && (
                  <Field label="On">
                    <Select value={draft.weekday} onChange={(e) => set({ weekday: e.target.value })} aria-label="Day of the week">
                      {WEEKDAYS.map((d, i) => (
                        <option key={d} value={i}>
                          {d}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                {(draft.frequency === 'monthly' || draft.frequency === 'yearly') && (
                  <Field label="Day of the month" hint="A short month uses its last day.">
                    <Input type="number" min={1} max={31} value={draft.dayOfMonth} onChange={(e) => set({ dayOfMonth: e.target.value })} />
                  </Field>
                )}
                {draft.frequency === 'yearly' && (
                  <Field label="Month">
                    <Select value={draft.month} onChange={(e) => set({ month: e.target.value })} aria-label="Month">
                      {MONTHS.map((m, i) => (
                        <option key={m} value={i + 1}>
                          {m}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
              </div>
              {draft.frequency && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="First one on" hint="The next matching day if left empty.">
                    <Input type="date" value={draft.start} onChange={(e) => set({ start: e.target.value })} />
                  </Field>
                  <Field label="Stop after" hint="Optional.">
                    <Input type="date" value={draft.end} onChange={(e) => set({ end: e.target.value })} />
                  </Field>
                </div>
              )}
            </fieldset>
          </div>
        )}
      </Modal>
    </div>
  )
}
