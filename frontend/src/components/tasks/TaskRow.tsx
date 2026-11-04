import { CheckSquare, MessageSquare, Paperclip } from 'lucide-react'
import { useLumen } from '../../lumen/useLumen'
import type { TaskCard } from '../../types'
import { DueLabel, KindIcon, Person, PriorityMark, StatusPill } from '../../tasks/taskUi'

/** One task as a line: what it is, where it stands, who has it and when it is due. The whole line opens the task. */
export function TaskRow({ task, onOpen, showProject = true }: { task: TaskCard; onOpen: (key: string) => void; showProject?: boolean }) {
  const lumen = useLumen()
  const done = task.status.category === 'done'
  return (
    <button type="button" onClick={() => onOpen(task.key)} className={`interactive flex w-full items-center gap-3 text-left hover:bg-muted/50 ${lumen ? 'px-4 py-3.5' : 'px-3 py-2.5'}`}>
      <KindIcon kind={task.type} />
      <span className="w-20 shrink-0 text-xs font-medium text-[color:var(--color-text-muted)]">{task.key}</span>
      <span className="min-w-0 flex-1">
        <span className={`block truncate ${lumen ? 'text-[0.95rem]' : 'text-sm'} ${done ? 'text-[color:var(--color-text-faint)] line-through' : 'font-medium text-[color:var(--color-text)]'}`}>{task.title}</span>
        {(showProject || task.blocked_by.length > 0) && (
          <span className="t-caption block truncate text-[color:var(--color-text-faint)]">
            {showProject ? task.project_name : ''}
            {task.blocked_by.length > 0 ? `${showProject ? ' · ' : ''}Blocked by ${task.blocked_by.join(', ')}` : ''}
          </span>
        )}
      </span>
      <span className="hidden shrink-0 items-center gap-2.5 text-[color:var(--color-text-faint)] sm:flex">
        {task.checklist.total > 0 && (
          <span className="inline-flex items-center gap-1 text-xs" title="Checklist">
            <CheckSquare className="h-3.5 w-3.5" />
            {task.checklist.done}/{task.checklist.total}
          </span>
        )}
        {task.comments > 0 && (
          <span className="inline-flex items-center gap-1 text-xs" title="Comments">
            <MessageSquare className="h-3.5 w-3.5" />
            {task.comments}
          </span>
        )}
        {task.attachments > 0 && (
          <span className="inline-flex items-center gap-1 text-xs" title="Files">
            <Paperclip className="h-3.5 w-3.5" />
            {task.attachments}
          </span>
        )}
      </span>
      <PriorityMark priority={task.priority} />
      <span className="hidden w-24 shrink-0 text-right md:block">
        <DueLabel due={task.due_date} overdue={task.overdue} done={done} />
      </span>
      <span className="hidden shrink-0 md:block">
        <StatusPill name={task.status.name} category={task.status.category} />
      </span>
      <Person person={task.assignee} name={false} />
    </button>
  )
}

export function TaskGroup({ title, count, tone, tasks, onOpen, showProject = true }: { title: string; count?: number; tone?: 'danger' | 'warn'; tasks: TaskCard[]; onOpen: (key: string) => void; showProject?: boolean }) {
  const lumen = useLumen()
  if (!tasks.length) return null
  return (
    <section>
      {lumen ? (
        <h3 className="mb-2 flex items-center gap-2 px-1 text-sm font-semibold">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold tabular-nums ${tone === 'danger' ? 'bg-negative-dim text-negative' : tone === 'warn' ? 'bg-warning-dim text-warning' : 'bg-accent-dim text-[color:var(--color-text)]'}`}>{count ?? tasks.length}</span>
          {title}
        </h3>
      ) : (
      <h3 className={`eyebrow mb-1.5 ${tone === 'danger' ? '!text-negative' : tone === 'warn' ? '!text-warning' : ''}`}>
        {title} · {count ?? tasks.length}
      </h3>
      )}
      <div className="panel divide-y divide-[color:var(--color-border)] overflow-hidden !p-0">
        {tasks.map((task) => (
          <TaskRow key={task.key} task={task} onOpen={onOpen} showProject={showProject} />
        ))}
      </div>
    </section>
  )
}
