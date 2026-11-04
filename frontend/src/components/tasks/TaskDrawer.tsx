import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, CheckCircle2, Eye, EyeOff, ListPlus, Pencil, PlayCircle, RotateCcw, Send, Trash2, Undo2 } from 'lucide-react'
import { ApiError, tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { celebrate } from '../../lumen/celebrate'
import { formatDateTime, timeAgo } from '../../formatTime'
import {
  CATEGORY_LABEL,
  DueLabel,
  KindIcon,
  KINDS,
  Person,
  PRIORITIES,
  PriorityMark,
  StatusPill,
  errorText,
  formatMinutes,
  parseDuration,
} from '../../tasks/taskUi'
import { useTaskPeople } from '../../tasks/useTaskPeople'
import type { TaskChanges, TaskDetail, TaskKind, TaskPriority, TaskResolution, TaskSprint } from '../../types'
import { Markdown } from '../assistant/Markdown'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Drawer } from '../ui/Drawer'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { MultiSelect } from '../ui/MultiSelect'
import { Tabs } from '../ui/Tabs'
import { NewTaskModal } from './NewTaskModal'
import { PersonSelect } from './PersonSelect'
import { ActivityPanel, AttachmentsPanel, ChecklistPanel, CommentsPanel, LinksPanel, TimePanel } from './TaskPanels'

type Tab = 'comments' | 'activity' | 'time' | 'links'
const RESOLUTIONS: TaskResolution[] = ['Done', "Won't do", 'Duplicate', 'Cancelled']

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-2 py-1.5">
      <span className="text-xs font-medium text-[color:var(--color-text-muted)]">{label}</span>
      <div className="min-w-0 text-sm">{children}</div>
    </div>
  )
}

/**
 * One task, opened over the page: everything about it in one place, changed in place. A change is sent with the time the task was last changed,
 * so if someone else changed it meanwhile the person is told and sees theirs, instead of silently overwriting it.
 */
export function TaskDrawer({ taskKey, onClose, onOpen }: { taskKey: string | null; onClose: () => void; onOpen: (key: string) => void }) {
  const { changed, version } = useTasks()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [sprints, setSprints] = useState<TaskSprint[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState<Tab>('comments')
  const [titleDraft, setTitleDraft] = useState<string | null>(null)
  const [descDraft, setDescDraft] = useState<string | null>(null)
  const [estimateDraft, setEstimateDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [finish, setFinish] = useState<{ statusId: number } | null>(null)
  const [review, setReview] = useState<{ mode: 'request' | 'changes' | 'approve' } | null>(null)
  const [subtaskOpen, setSubtaskOpen] = useState(false)
  const people = useTaskPeople(task?.project_key ?? null)
  const loadedFor = useRef<string | null>(null)

  const load = useCallback(
    async (key: string, quiet = false) => {
      try {
        const found = await tasksApi.get(key)
        setTask(found)
        setError('')
        if (!quiet || loadedFor.current !== key) {
          tasksApi
            .sprints(found.project_key)
            .then((s) => setSprints(s.sprints.filter((x) => x.state !== 'Completed')))
            .catch(() => setSprints([]))
        }
        loadedFor.current = key
      } catch (e) {
        setError(errorText(e, 'The task could not be opened.'))
        if (!quiet) setTask(null)
      }
    },
    [],
  )

  useEffect(() => {
    if (!taskKey) {
      setTask(null)
      loadedFor.current = null
      return
    }
    setTask((now) => (now?.key === taskKey ? now : null))
    setTitleDraft(null)
    setDescDraft(null)
    setEstimateDraft(null)
    setNotice('')
    setTab('comments')
    void load(taskKey, loadedFor.current === taskKey)
  }, [taskKey, load])

  // Something changed elsewhere in the workspace (a board drag, a bulk change): look again, quietly.
  useEffect(() => {
    if (taskKey && loadedFor.current === taskKey) void load(taskKey, true)
  }, [version, taskKey, load])

  const perms = task?.permissions
  const canEdit = Boolean(perms?.can_edit) && task?.project.state === 'Active'
  const canComment = Boolean(perms?.can_comment) && task?.project.state === 'Active'

  const run = async (work: () => Promise<TaskDetail | void>, success?: string) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await work()
      if (result) setTask(result)
      if (success) setNotice(success)
      changed()
      return true
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && taskKey) {
        setError(`${e.message} The task has been reloaded, so you see the latest version.`)
        void load(taskKey, true)
      } else {
        setError(errorText(e))
      }
      return false
    } finally {
      setBusy(false)
    }
  }

  const save = (changes: TaskChanges) => (task ? run(() => tasksApi.update(task.key, changes, task.updated)) : Promise.resolve(false))

  const move = (statusId: number) => {
    if (!task || statusId === task.status.id) return
    const target = task.statuses.find((s) => s.id === statusId)
    if (!target) return
    if (target.category === 'done') return setFinish({ statusId })
    if (target.category === 'review') return setReview({ mode: 'request' })
    void run(() => tasksApi.move(task.key, { status_id: statusId }))
  }

  const nextStatus = (category: 'doing' | 'todo') => task?.statuses.find((s) => s.category === category)
  const hasReviewStatus = Boolean(task?.statuses.some((s) => s.category === 'review'))

  const doneStatus = task?.statuses.find((s) => s.category === 'done')

  const header = task && (
    <span className="flex flex-wrap items-center gap-2">
      <KindIcon kind={task.type} />
      <span>{task.key}</span>
    </span>
  )

  return (
    <>
      <Drawer
        open={Boolean(taskKey)}
        onClose={onClose}
        title={task ? task.key : (taskKey ?? 'Task')}
        subtitle={task ? `${task.project.name}${task.parent ? ` · in ${task.parent.key}` : ''}` : undefined}
        badge={task && <StatusPill name={task.status.name} category={task.status.category} />}
        footer={
          task && (
            <>
              <span className="mr-auto text-xs text-[color:var(--color-text-faint)]" title={formatDateTime(task.updated)}>
                Changed {timeAgo(task.updated)}
              </span>
              {perms?.can_delete && task.project.state === 'Active' && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(`Delete ${task.key}? It disappears from the lists; its history is kept.`)) void run(() => tasksApi.remove(task.key).then(() => undefined), 'Deleted.').then((ok) => ok && onClose())
                  }}
                >
                  <Trash2 className="h-4 w-4" /> Delete
                </Button>
              )}
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
            </>
          )
        }
      >
        {error && (
          <div className="mb-4">
            <Alert variant="error" onDismiss={() => setError('')}>
              {error}
            </Alert>
          </div>
        )}
        {notice && (
          <div className="mb-4">
            <Alert variant="success" onDismiss={() => setNotice('')}>
              {notice}
            </Alert>
          </div>
        )}
        {!task && !error && <p className="py-10 text-center text-sm text-[color:var(--color-text-faint)]">Loading…</p>}

        {task && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
            <div className="min-w-0 space-y-6">
              {header}

              {titleDraft === null ? (
                <div className="group flex items-start gap-2">
                  <h2 className="t-h2 min-w-0 flex-1 break-words">{task.title}</h2>
                  {canEdit && (
                    <button type="button" aria-label="Edit the title" onClick={() => setTitleDraft(task.title)} className="interactive rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]">
                      <Pencil className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ) : (
                <form
                  className="flex gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    if (!titleDraft.trim()) return
                    void save({ title: titleDraft.trim() }).then((ok) => ok && setTitleDraft(null))
                  }}
                >
                  <Input autoFocus value={titleDraft} maxLength={250} onChange={(e) => setTitleDraft(e.target.value)} aria-label="Title" />
                  <Button type="submit" loading={busy}>
                    Save
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setTitleDraft(null)}>
                    Cancel
                  </Button>
                </form>
              )}

              {/* What to do next */}
              {canEdit && (
                <div className="flex flex-wrap gap-2">
                  {task.status.category === 'todo' && nextStatus('doing') && (
                    <Button size="sm" loading={busy} onClick={() => move(nextStatus('doing')!.id)}>
                      <PlayCircle className="h-4 w-4" /> Start work
                    </Button>
                  )}
                  {task.status.category === 'doing' && hasReviewStatus && !task.pending_review && (
                    <Button size="sm" onClick={() => setReview({ mode: 'request' })}>
                      <Send className="h-4 w-4" /> Send for review
                    </Button>
                  )}
                  {(task.status.category === 'doing' || task.status.category === 'todo') && doneStatus && !task.project.require_review && (
                    <Button size="sm" variant="secondary" onClick={() => setFinish({ statusId: doneStatus.id })}>
                      <CheckCircle2 className="h-4 w-4" /> Mark done
                    </Button>
                  )}
                  {task.status.category === 'done' && nextStatus('todo') && (
                    <Button size="sm" variant="secondary" loading={busy} onClick={() => move(nextStatus('todo')!.id)}>
                      <RotateCcw className="h-4 w-4" /> Reopen
                    </Button>
                  )}
                </div>
              )}

              {/* Review */}
              {task.pending_review && (
                <div className="rounded-xl border border-violet/30 bg-violet-dim/50 p-4">
                  <p className="text-sm font-semibold text-[color:var(--color-text)]">In review</p>
                  <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
                    {task.pending_review.requester?.display_name ?? 'Someone'} asked {task.pending_review.reviewer?.display_name ?? 'a reviewer'} to review it {timeAgo(task.pending_review.requested)}.
                  </p>
                  {task.pending_review.request_note && <p className="mt-2 rounded-lg bg-surface/70 p-2 text-sm text-[color:var(--color-text)]">{task.pending_review.request_note}</p>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {perms?.can_decide_review && (
                      <>
                        <Button size="sm" onClick={() => setReview({ mode: 'approve' })}>
                          <Check className="h-4 w-4" /> Approve
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => setReview({ mode: 'changes' })}>
                          <Undo2 className="h-4 w-4" /> Request changes
                        </Button>
                      </>
                    )}
                    {canEdit && task.pending_review.requester && (
                      <Button size="sm" variant="ghost" loading={busy} onClick={() => void run(() => tasksApi.withdrawReview(task.key), 'The review was withdrawn.')}>
                        Withdraw
                      </Button>
                    )}
                  </div>
                </div>
              )}
              {!task.pending_review && task.reviews[0]?.status === 'Changes requested' && task.status.category !== 'done' && (
                <Alert variant="warning">
                  {task.reviews[0].reviewer?.display_name ?? 'The reviewer'} asked for changes{task.reviews[0].decision_note ? `: ${task.reviews[0].decision_note}` : '.'}
                </Alert>
              )}

              {/* Description */}
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="eyebrow">Description</h3>
                  {canEdit && descDraft === null && (
                    <Button size="sm" variant="ghost" onClick={() => setDescDraft(task.description ?? '')}>
                      <Pencil className="h-3.5 w-3.5" /> Edit
                    </Button>
                  )}
                </div>
                {descDraft === null ? (
                  task.description ? (
                    <div className="text-sm">
                      <Markdown text={task.description} />
                    </div>
                  ) : (
                    <p className="text-sm text-[color:var(--color-text-faint)]">No description.</p>
                  )
                ) : (
                  <div className="space-y-2">
                    <Textarea rows={8} autoFocus value={descDraft} onChange={(e) => setDescDraft(e.target.value)} aria-label="Description" />
                    <div className="flex gap-2">
                      <Button size="sm" loading={busy} onClick={() => void save({ description: descDraft.trim() || null }).then((ok) => ok && setDescDraft(null))}>
                        Save
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDescDraft(null)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </section>

              {/* Sub-tasks */}
              {(task.subtask_list.length > 0 || canEdit) && task.type !== 'Sub-task' && (
                <section>
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="eyebrow">{`Sub-tasks${task.subtasks.total ? ` · ${task.subtasks.done}/${task.subtasks.total}` : ''}`}</h3>
                    {canEdit && (
                      <Button size="sm" variant="secondary" onClick={() => setSubtaskOpen(true)}>
                        <ListPlus className="h-3.5 w-3.5" /> Add
                      </Button>
                    )}
                  </div>
                  <ul className="divide-y divide-[color:var(--color-border)] rounded-lg border border-[color:var(--color-border)]">
                    {task.subtask_list.map((s) => (
                      <li key={s.key}>
                        <button type="button" onClick={() => onOpen(s.key)} className="interactive flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/50">
                          <KindIcon kind={s.type} />
                          <span className="shrink-0 text-xs font-medium text-[color:var(--color-text-muted)]">{s.key}</span>
                          <span className={`min-w-0 flex-1 truncate text-sm ${s.status.category === 'done' ? 'text-[color:var(--color-text-faint)] line-through' : ''}`}>{s.title}</span>
                          <Person person={s.assignee} name={false} size="xs" />
                          <StatusPill name={s.status.name} category={s.status.category} />
                        </button>
                      </li>
                    ))}
                    {task.subtask_list.length === 0 && <li className="px-3 py-2 text-sm text-[color:var(--color-text-muted)]">No sub-tasks. Break the work into smaller pieces and give each to someone.</li>}
                  </ul>
                </section>
              )}

              <ChecklistPanel task={task} canEdit={canEdit} onItems={(items) => setTask((now) => (now ? { ...now, checklist_items: items, checklist: { total: items.length, done: items.filter((i) => i.done).length } } : now))} />

              <AttachmentsPanel task={task} canAttach={canComment} onChanged={(count) => setTask((now) => (now ? { ...now, attachments: count } : now))} />

              <section>
                <Tabs
                  label="Task details"
                  active={tab}
                  onChange={setTab}
                  tabs={[
                    { id: 'comments', label: `Comments${task.comments ? ` (${task.comments})` : ''}` },
                    { id: 'activity', label: 'History' },
                    { id: 'time', label: `Time${task.time.total ? ` (${formatMinutes(task.time.total)})` : ''}` },
                    { id: 'links', label: `Links${task.links.length + task.records.length ? ` (${task.links.length + task.records.length})` : ''}` },
                  ]}
                />
                <div className="pt-4">
                  {tab === 'comments' && <CommentsPanel task={task} people={people} canComment={canComment} onCount={(n) => setTask((now) => (now ? { ...now, comments: n } : now))} />}
                  {tab === 'activity' && <ActivityPanel taskKey={task.key} />}
                  {tab === 'time' && <TimePanel task={task} canLog={canEdit} onTime={(time, spent) => setTask((now) => (now ? { ...now, time, spent_minutes: spent } : now))} />}
                  {tab === 'links' && (
                    <LinksPanel
                      task={task}
                      canEdit={canEdit}
                      onOpen={onOpen}
                      onLinks={(links) => {
                        setTask((now) => (now ? { ...now, links } : now))
                        changed()
                      }}
                      onRecords={(records) => setTask((now) => (now ? { ...now, records } : now))}
                    />
                  )}
                </div>
              </section>
            </div>

            {/* The details */}
            <aside className="space-y-1 lg:border-l lg:border-[color:var(--color-border)] lg:pl-5">
              <Row label="Status">
                {canEdit ? (
                  <Select value={task.status.id} onChange={(e) => move(Number(e.target.value))} aria-label="Status" disabled={busy}>
                    {task.statuses.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} ({CATEGORY_LABEL[s.category]})
                      </option>
                    ))}
                  </Select>
                ) : (
                  <StatusPill name={task.status.name} category={task.status.category} />
                )}
              </Row>
              <Row label="Assignee">{canEdit ? <PersonSelect people={people} value={task.assignee?.id ?? null} onChange={(id) => void save({ assignee_id: id })} /> : <Person person={task.assignee} />}</Row>
              <Row label="Reviewer">{canEdit ? <PersonSelect people={people} value={task.reviewer?.id ?? null} onChange={(id) => void save({ reviewer_id: id })} emptyLabel="Chosen later" /> : <Person person={task.reviewer} />}</Row>
              <Row label="Reporter">
                <Person person={task.reporter} />
              </Row>
              <Row label="Priority">
                {canEdit ? (
                  <Select value={task.priority} onChange={(e) => void save({ priority: e.target.value as TaskPriority })} aria-label="Priority">
                    {PRIORITIES.map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </Select>
                ) : (
                  <PriorityMark priority={task.priority} withLabel />
                )}
              </Row>
              <Row label="Type">
                {canEdit ? (
                  <Select value={task.type} onChange={(e) => void save({ type: e.target.value as TaskKind })} aria-label="Type">
                    {KINDS.map((k) => (
                      <option key={k}>{k}</option>
                    ))}
                  </Select>
                ) : (
                  task.type
                )}
              </Row>
              <Row label="Due">
                {canEdit ? <Input type="date" value={task.due_date ?? ''} onChange={(e) => void save({ due_date: e.target.value || null })} aria-label="Due date" /> : <DueLabel due={task.due_date} overdue={task.overdue} done={task.status.category === 'done'} />}
              </Row>
              <Row label="Start">{canEdit ? <Input type="date" value={task.start_date ?? ''} onChange={(e) => void save({ start_date: e.target.value || null })} aria-label="Start date" /> : (task.start_date ?? '—')}</Row>
              <Row label="Estimate">
                {canEdit ? (
                  <Input
                    value={estimateDraft ?? (task.estimate_minutes ? formatMinutes(task.estimate_minutes) : '')}
                    placeholder="1h 30m"
                    aria-label="Estimate"
                    onChange={(e) => setEstimateDraft(e.target.value)}
                    onBlur={() => {
                      if (estimateDraft === null) return
                      const minutes = estimateDraft.trim() ? parseDuration(estimateDraft) : null
                      if (estimateDraft.trim() && minutes === null) {
                        setError('Write the estimate like 90, 1h 30m or 2d.')
                        return
                      }
                      setEstimateDraft(null)
                      if (minutes !== task.estimate_minutes) void save({ estimate_minutes: minutes })
                    }}
                  />
                ) : (
                  formatMinutes(task.estimate_minutes)
                )}
              </Row>
              <Row label="Logged">{formatMinutes(task.time.total)}</Row>
              <Row label="Points">
                {canEdit ? (
                  <Input
                    type="number"
                    min={0}
                    step="0.5"
                    defaultValue={task.story_points ?? ''}
                    key={`${task.key}-${task.story_points}`}
                    aria-label="Story points"
                    onBlur={(e) => {
                      const next = e.target.value.trim() ? Number(e.target.value) : null
                      if (next !== task.story_points) void save({ story_points: next })
                    }}
                  />
                ) : (
                  (task.story_points ?? '—')
                )}
              </Row>
              {(sprints.length > 0 || task.sprint) && (
                <Row label="Sprint">
                  {canEdit ? (
                    <Select value={task.sprint?.id ?? ''} onChange={(e) => void save({ sprint_id: e.target.value ? Number(e.target.value) : null })} aria-label="Sprint">
                      <option value="">Backlog</option>
                      {task.sprint && !sprints.some((s) => s.id === task.sprint?.id) && <option value={task.sprint.id}>{task.sprint.name}</option>}
                      {sprints.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    (task.sprint?.name ?? 'Backlog')
                  )}
                </Row>
              )}
              <div className="py-1.5">
                <MultiSelect label="Labels" values={task.labels} onChange={(next) => void save({ labels: next })} options={[]} allowCustom separator={/,/} noun={['label', 'labels']} placeholder="Labels" max={12} disabled={!canEdit} />
              </div>

              <div className="space-y-1 border-t border-[color:var(--color-border)] pt-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-[color:var(--color-text-muted)]">{task.watchers.length} watching</span>
                  <Button size="sm" variant="ghost" onClick={() => void run(async () => setTask({ ...task, watchers: (await tasksApi.watch(task.key, !task.watching)).watchers, watching: !task.watching }))}>
                    {task.watching ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />} {task.watching ? 'Stop' : 'Watch'}
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {task.watchers.slice(0, 12).map((w) => (
                    <span key={w.id} title={w.display_name}>
                      <Person person={w} name={false} />
                    </span>
                  ))}
                </div>
              </div>

              <dl className="space-y-1 border-t border-[color:var(--color-border)] pt-3 text-xs text-[color:var(--color-text-faint)]">
                <div>Created {formatDateTime(task.created)}</div>
                {task.resolved && <div>Finished {formatDateTime(task.resolved)}{task.resolution ? ` · ${task.resolution}` : ''}</div>}
                {task.recurring && <div>Made by a repeating schedule</div>}
              </dl>
            </aside>
          </div>
        )}
      </Drawer>

      {task && (
        <>
          <FinishDialog
            open={Boolean(finish)}
            taskKey={task.key}
            onClose={() => setFinish(null)}
            onConfirm={async (resolution, note) => {
              if (!finish) return
              const ok = await run(() => tasksApi.move(task.key, { status_id: finish.statusId, resolution, note: note || undefined }))
              if (ok) {
                setFinish(null)
                if (resolution === 'Done') celebrate()
              }
            }}
            busy={busy}
          />
          <ReviewDialog
            open={Boolean(review)}
            mode={review?.mode ?? 'request'}
            people={people.filter((p) => p.id !== task.assignee?.id)}
            initialReviewer={task.reviewer?.id ?? null}
            busy={busy}
            onClose={() => setReview(null)}
            onConfirm={async (reviewer, note) => {
              if (!review) return
              const ok = await run(
                () =>
                  review.mode === 'request'
                    ? tasksApi.requestReview(task.key, reviewer ?? 0, note || undefined)
                    : tasksApi.decideReview(task.key, review.mode === 'approve' ? 'approve' : 'changes', note || undefined),
                review.mode === 'approve' ? 'Approved.' : undefined,
              )
              if (ok) {
                setReview(null)
                if (review.mode === 'approve') celebrate()
              }
            }}
          />
          <NewTaskModal
            open={subtaskOpen}
            onClose={() => setSubtaskOpen(false)}
            project={task.project_key}
            parentKey={task.key}
            onCreated={(made) => {
              setSubtaskOpen(false)
              void load(task.key, true)
              onOpen(made.key)
            }}
          />
        </>
      )}
    </>
  )
}

function FinishDialog({ open, taskKey, onClose, onConfirm, busy }: { open: boolean; taskKey: string; onClose: () => void; onConfirm: (resolution: TaskResolution, note: string) => void; busy: boolean }) {
  const [resolution, setResolution] = useState<TaskResolution>('Done')
  const [note, setNote] = useState('')
  useEffect(() => {
    if (open) {
      setResolution('Done')
      setNote('')
    }
  }, [open])
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Finish ${taskKey}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={busy} onClick={() => onConfirm(resolution, note.trim())}>
            Finish
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="How did it end?">
          <Select value={resolution} onChange={(e) => setResolution(e.target.value as TaskResolution)} aria-label="Resolution">
            {RESOLUTIONS.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
        <Field label="Note" hint="Optional. Shown in the history.">
          <Textarea rows={3} value={note} maxLength={1500} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}

function ReviewDialog({
  open,
  mode,
  people,
  initialReviewer,
  busy,
  onClose,
  onConfirm,
}: {
  open: boolean
  mode: 'request' | 'changes' | 'approve'
  people: { id: number; display_name: string; has_avatar: boolean; avatar_version: number; avatar_url: string | null; username: string; role: string }[]
  initialReviewer: number | null
  busy: boolean
  onClose: () => void
  onConfirm: (reviewer: number | null, note: string) => void
}) {
  const [reviewer, setReviewer] = useState<number | null>(initialReviewer)
  const [note, setNote] = useState('')
  useEffect(() => {
    if (open) {
      setReviewer(initialReviewer)
      setNote('')
    }
  }, [open, initialReviewer])
  const title = mode === 'request' ? 'Send for review' : mode === 'approve' ? 'Approve' : 'Request changes'
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={busy} disabled={mode === 'request' && !reviewer} onClick={() => onConfirm(reviewer, note.trim())}>
            {title}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {mode === 'request' && (
          <Field label="Reviewer" required hint="Someone other than the person doing the work.">
            <PersonSelect people={people} value={reviewer} onChange={setReviewer} emptyLabel="Choose a reviewer" />
          </Field>
        )}
        <Field label={mode === 'request' ? 'What should they look at?' : mode === 'approve' ? 'Comment' : 'What needs to change?'} hint={mode === 'approve' ? 'Optional.' : undefined}>
          <Textarea rows={4} autoFocus value={note} maxLength={1500} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}
