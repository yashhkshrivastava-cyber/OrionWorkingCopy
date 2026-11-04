import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { AlertTriangle, CheckSquare, MessageSquare, Paperclip, Plus } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { useTasks } from '../../context/TasksContext'
import { celebrate } from '../../lumen/celebrate'
import { useLumen } from '../../lumen/useLumen'
import { CATEGORY_LABEL, DueLabel, errorText, KindIcon, Person, PriorityMark } from '../../tasks/taskUi'
import { useOpenTask } from '../../tasks/useOpenTask'
import type { TaskBoardColumn, TaskBoardData, TaskCard, TaskFilters, TaskInput, TaskResolution } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/EmptyState'
import { Modal } from '../ui/Modal'
import { Field, Select, Textarea } from '../ui/Field'
import { NewTaskModal } from './NewTaskModal'

const TONE: Record<string, string> = {
  todo: 'bg-[color:var(--color-text-faint)]',
  doing: 'bg-accent',
  review: 'bg-violet',
  done: 'bg-positive',
}

function Card({ task, onOpen, onDragStart, dragging }: { task: TaskCard; onOpen: () => void; onDragStart: (e: DragEvent) => void; dragging: boolean }) {
  const lumen = useLumen()
  const done = task.status.category === 'done'
  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      onDragStart={onDragStart}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onOpen())}
      className={`panel cursor-grab transition-shadow hover:shadow-raised active:cursor-grabbing ${lumen ? '!rounded-2xl !p-3.5' : '!p-3'} ${dragging ? 'opacity-40' : ''}`}
      data-task={task.key}
    >
      <p className={`text-sm font-medium ${done ? 'text-[color:var(--color-text-faint)] line-through' : 'text-[color:var(--color-text)]'}`}>{task.title}</p>
      {task.labels.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {task.labels.slice(0, 4).map((label) => (
            <span key={label} className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-[color:var(--color-text-muted)]">
              {label}
            </span>
          ))}
        </div>
      )}
      {task.blocked_by.length > 0 && (
        <p className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-negative">
          <AlertTriangle className="h-3 w-3" /> Blocked by {task.blocked_by.join(', ')}
        </p>
      )}
      <div className="mt-2.5 flex items-center gap-2">
        <KindIcon kind={task.type} className="h-3.5 w-3.5" />
        <span className="text-[11px] font-medium text-[color:var(--color-text-muted)]">{task.key}</span>
        <PriorityMark priority={task.priority} />
        <DueLabel due={task.due_date} overdue={task.overdue} done={done} />
        <span className="ml-auto flex items-center gap-2 text-[color:var(--color-text-faint)]">
          {task.subtasks.total > 0 && (
            <span className="text-[11px]" title="Sub-tasks done">
              {task.subtasks.done}/{task.subtasks.total}
            </span>
          )}
          {task.checklist.total > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px]" title="Checklist">
              <CheckSquare className="h-3 w-3" />
              {task.checklist.done}/{task.checklist.total}
            </span>
          )}
          {task.comments > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px]">
              <MessageSquare className="h-3 w-3" />
              {task.comments}
            </span>
          )}
          {task.attachments > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[11px]">
              <Paperclip className="h-3 w-3" />
              {task.attachments}
            </span>
          )}
          <Person person={task.assignee} name={false} size="xs" />
        </span>
      </div>
    </div>
  )
}

/** The project's columns, one per status, with the tasks as cards. Dragging a card to another column changes its status; dropping it between cards sets its place. */
export function BoardView({ project, filters, canWork }: { project: string; filters: TaskFilters; canWork: boolean }) {
  const { changed, version } = useTasks()
  const lumen = useLumen()
  const open = useOpenTask()
  const [board, setBoard] = useState<TaskBoardData | null>(null)
  const [error, setError] = useState('')
  const [drag, setDrag] = useState<string | null>(null)
  const [over, setOver] = useState<{ column: number; before: string | null } | null>(null)
  const [finishing, setFinishing] = useState<{ key: string; column: TaskBoardColumn; before: string | null } | null>(null)
  const [adding, setAdding] = useState<number | null>(null)
  const filterKey = JSON.stringify(filters)
  const latest = useRef(0)

  const load = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const found = await tasksApi.board(project, JSON.parse(filterKey))
      if (ticket === latest.current) {
        setBoard(found)
        setError('')
      }
    } catch (e) {
      if (ticket === latest.current) setError(errorText(e, 'The board could not be loaded.'))
    }
  }, [project, filterKey])

  useEffect(() => {
    void load()
  }, [load, version])

  const drop = async (column: TaskBoardColumn, before: string | null, resolution?: TaskResolution, note?: string, taskKey?: string) => {
    const key = taskKey ?? drag
    setDrag(null)
    setOver(null)
    if (!key || !board) return
    const card = board.columns.flatMap((c) => c.tasks).find((t) => t.key === key)
    if (!card) return
    const same = card.status.id === column.id
    if (same && before === key) return
    if (!same && column.category === 'done' && !resolution) return setFinishing({ key, column, before })
    if (!same && column.category === 'review') return setError('To send a task for review, open it and use “Send for review”: someone has to be chosen to review it.')
    const siblings = column.tasks.filter((t) => t.key !== key)
    const index = before ? siblings.findIndex((t) => t.key === before) : siblings.length
    const after = index > 0 ? siblings[index - 1].key : null
    try {
      await tasksApi.move(key, { status_id: column.id, before_key: before ?? undefined, after_key: before ? undefined : (after ?? undefined), resolution, note })
      setError('')
      changed()
      if (column.category === 'done' && !same) celebrate()
    } catch (e) {
      setError(errorText(e))
      void load()
    }
  }

  if (error && !board) return <Alert variant="error">{error}</Alert>
  if (!board)
    return (
      <div className="grid gap-3 md:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-64" />
        ))}
      </div>
    )

  return (
    <div className="space-y-3">
      {error && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}
      {board.hidden_done > 0 && <p className="t-caption text-[color:var(--color-text-muted)]">{board.hidden_done} older finished tasks are not shown here. Find them in the List.</p>}
      <div className="scroll-quiet -mx-1 flex gap-3 overflow-x-auto px-1 pb-3">
        {board.columns.map((column) => {
          const overLimit = column.wip_limit !== null && column.wip_limit > 0 && column.count > column.wip_limit
          return (
            <section
              key={column.id}
              aria-label={column.name}
              className={`flex shrink-0 flex-col border ${lumen ? 'w-80 rounded-[1.5rem] bg-[color:color-mix(in_srgb,var(--orion-surface)_55%,transparent)] backdrop-blur-xl' : 'w-72 rounded-xl bg-muted/40'} ${over?.column === column.id ? 'border-accent' : 'border-[color:var(--color-border)]'}`}
              onDragOver={(e) => {
                if (!drag || !canWork) return
                e.preventDefault()
                setOver((now) => (now?.column === column.id ? now : { column: column.id, before: null }))
              }}
              onDrop={(e) => {
                e.preventDefault()
                void drop(column, over?.column === column.id ? over.before : null)
              }}
            >
              <header className="flex items-center gap-2 px-3 py-2.5">
                <span className={`rounded-full ${lumen ? 'h-2.5 w-2.5' : 'h-2 w-2'} ${TONE[column.category]}`} aria-hidden="true" />
                <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-[color:var(--color-text)]" title={`${column.name} (${CATEGORY_LABEL[column.category]})`}>
                  {column.name}
                </h3>
                <span className={`text-xs tabular-nums ${overLimit ? 'font-bold text-negative' : 'text-[color:var(--color-text-muted)]'}`} title={column.wip_limit ? `At most ${column.wip_limit} at a time` : undefined}>
                  {column.count}
                  {column.wip_limit ? ` / ${column.wip_limit}` : ''}
                </span>
                {canWork && (
                  <button type="button" aria-label={`Add a task to ${column.name}`} onClick={() => setAdding(column.id)} className="interactive rounded p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]">
                    <Plus className="h-4 w-4" />
                  </button>
                )}
              </header>
              <div className="flex min-h-16 flex-1 flex-col gap-2 px-2 pb-2">
                {column.tasks.map((task) => (
                  <div
                    key={task.key}
                    onDragOver={(e) => {
                      if (!drag || drag === task.key || !canWork) return
                      e.preventDefault()
                      e.stopPropagation()
                      const rect = e.currentTarget.getBoundingClientRect()
                      const upper = e.clientY < rect.top + rect.height / 2
                      const idx = column.tasks.findIndex((t) => t.key === task.key)
                      const before = upper ? task.key : (column.tasks[idx + 1]?.key ?? null)
                      setOver((now) => (now?.column === column.id && now.before === before ? now : { column: column.id, before }))
                    }}
                  >
                    {over?.column === column.id && over.before === task.key && drag !== task.key && <div className="mb-2 h-1 rounded-full bg-accent" />}
                    <Card
                      task={task}
                      dragging={drag === task.key}
                      onOpen={() => open(task.key)}
                      onDragStart={(e) => {
                        if (!canWork) return e.preventDefault()
                        e.dataTransfer.effectAllowed = 'move'
                        e.dataTransfer.setData('text/plain', task.key)
                        setDrag(task.key)
                      }}
                    />
                  </div>
                ))}
                {over?.column === column.id && over.before === null && drag && <div className="h-1 rounded-full bg-accent" />}
                {column.tasks.length === 0 && !drag && <p className="px-2 py-4 text-center text-xs text-[color:var(--color-text-faint)]">Nothing here</p>}
              </div>
            </section>
          )
        })}
      </div>

      <FinishOnDrop
        open={Boolean(finishing)}
        onClose={() => {
          setFinishing(null)
          void load()
        }}
        onConfirm={async (resolution, note) => {
          if (!finishing) return
          const f = finishing
          setFinishing(null)
          await drop(f.column, f.before, resolution, note, f.key)
        }}
      />

      <NewTaskModal
        open={adding !== null}
        project={project}
        defaults={{ status_id: adding ?? undefined } as Partial<TaskInput>}
        onClose={() => setAdding(null)}
        onCreated={(made) => {
          setAdding(null)
          open(made.key)
        }}
      />
    </div>
  )
}

function FinishOnDrop({ open, onClose, onConfirm }: { open: boolean; onClose: () => void; onConfirm: (resolution: TaskResolution, note: string) => void }) {
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
      title="Finish this task"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(resolution, note.trim())}>Finish</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="How did it end?">
          <Select value={resolution} onChange={(e) => setResolution(e.target.value as TaskResolution)} aria-label="Resolution">
            {(['Done', "Won't do", 'Duplicate', 'Cancelled'] as const).map((r) => (
              <option key={r}>{r}</option>
            ))}
          </Select>
        </Field>
        <Field label="Note" hint="Optional.">
          <Textarea rows={3} value={note} maxLength={1500} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}
