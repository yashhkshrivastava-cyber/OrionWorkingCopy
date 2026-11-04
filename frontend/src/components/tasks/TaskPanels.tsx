import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type ReactNode } from 'react'
import { Check, Download, FileText, Link2, Paperclip, Pencil, Plus, Trash2, Upload, X } from 'lucide-react'
import { tasksApi } from '../../api/client'
import { newIdempotencyKey } from '../../api/idempotency'
import { Markdown } from '../assistant/Markdown'
import { formatDateTime, timeAgo } from '../../formatTime'
import { errorText, formatBytes, formatMinutes, parseDuration, todayIso } from '../../tasks/taskUi'
import type {
  TaskActivityLine,
  TaskAttachment,
  TaskChecklistItem,
  TaskComment,
  TaskDetail,
  TaskLink,
  TaskLinkKind,
  TaskPersonRow,
  TaskRecordLink,
  TaskTime,
} from '../../types'
import { Person } from '../../tasks/taskUi'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Input, Select, Textarea } from '../ui/Field'

const RECORD_KINDS: { id: string; label: string; hint: string }[] = [
  { id: 'bill', label: 'Bill', hint: 'Bill number, e.g. 2026-27/12' },
  { id: 'case', label: 'Case', hint: 'Case code' },
  { id: 'client', label: 'Client', hint: 'Client code' },
  { id: 'employee', label: 'Employee', hint: 'Employee code' },
  { id: 'opportunity', label: 'Opportunity', hint: 'Opportunity code' },
  { id: 'emd', label: 'EMD', hint: 'EMD code' },
  { id: 'expense', label: 'Expense', hint: 'Expense code' },
  { id: 'document', label: 'Document', hint: 'Document number' },
]

const LINK_LABEL: Record<TaskLinkKind, string> = {
  blocks: 'Blocks',
  blocked_by: 'Blocked by',
  relates: 'Relates to',
  duplicates: 'Duplicates',
  duplicated_by: 'Duplicated by',
}

function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="eyebrow">{children}</h3>
      {action}
    </div>
  )
}

// ------------------------------------------------------------------------------------------------------------------ checklist

export function ChecklistPanel({ task, canEdit, onItems }: { task: TaskDetail; canEdit: boolean; onItems: (items: TaskChecklistItem[]) => void }) {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const items = task.checklist_items
  const done = items.filter((item) => item.done).length

  const run = async (work: () => Promise<{ checklist: TaskChecklistItem[] }>) => {
    setError('')
    try {
      onItems((await work()).checklist)
    } catch (e) {
      setError(errorText(e))
    }
  }

  if (!items.length && !canEdit) return null
  return (
    <section>
      <SectionTitle>{`Checklist${items.length ? ` · ${done}/${items.length}` : ''}`}</SectionTitle>
      {items.length > 0 && (
        <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className="h-full rounded-full bg-positive transition-[width]" style={{ width: `${(done / items.length) * 100}%` }} />
        </div>
      )}
      {error && <p className="mb-2 text-xs text-negative">{error}</p>}
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.id} className="group flex items-start gap-2 rounded-md px-1 py-1 hover:bg-muted/50">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 accent-[color:var(--color-primary)]"
              checked={item.done}
              disabled={!canEdit}
              aria-label={item.text}
              onChange={(e) => void run(() => tasksApi.updateChecklist(item.id, { done: e.target.checked }))}
            />
            <span className={`min-w-0 flex-1 break-words text-sm ${item.done ? 'text-[color:var(--color-text-faint)] line-through' : 'text-[color:var(--color-text)]'}`}>{item.text}</span>
            {canEdit && (
              <button type="button" aria-label={`Remove ${item.text}`} onClick={() => void run(() => tasksApi.deleteChecklist(item.id))} className="interactive rounded p-1 text-[color:var(--color-text-faint)] opacity-0 hover:text-negative focus:opacity-100 group-hover:opacity-100">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {canEdit && (
        <form
          className="mt-2 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (!text.trim()) return
            const value = text
            setText('')
            void run(() => tasksApi.addChecklist(task.key, value))
          }}
        >
          <Input value={text} maxLength={300} onChange={(e) => setText(e.target.value)} placeholder="Add a step…" aria-label="New checklist step" />
          <Button type="submit" variant="secondary" size="sm" disabled={!text.trim()}>
            <Plus className="h-3.5 w-3.5" /> Add
          </Button>
        </form>
      )}
    </section>
  )
}

// ----------------------------------------------------------------------------------------------------------------- attachments

export function AttachmentsPanel({ task, canAttach, onChanged }: { task: TaskDetail; canAttach: boolean; onChanged: (count: number) => void }) {
  const [files, setFiles] = useState<TaskAttachment[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let cancelled = false
    tasksApi
      .attachments(task.key)
      .then((found) => !cancelled && setFiles(found.attachments))
      .catch((e) => !cancelled && setError(errorText(e)))
    return () => {
      cancelled = true
    }
  }, [task.key])

  const upload = async (list: File[]) => {
    if (!list.length || !canAttach) return
    setBusy(true)
    setError('')
    try {
      let latest: TaskAttachment[] | null = null
      for (const file of list) latest = (await tasksApi.attach(task.key, file)).attachments
      if (latest) {
        setFiles(latest)
        onChanged(latest.length)
      }
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const remove = async (file: TaskAttachment) => {
    if (!window.confirm(`Remove ${file.name} from this task?`)) return
    try {
      const left = (await tasksApi.deleteAttachment(file.id)).attachments
      setFiles(left)
      onChanged(left.length)
    } catch (e) {
      setError(errorText(e))
    }
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setOver(false)
    void upload(Array.from(event.dataTransfer.files))
  }
  const onPaste = (event: ClipboardEvent) => {
    const pasted = Array.from(event.clipboardData.files)
    if (pasted.length) {
      event.preventDefault()
      void upload(pasted)
    }
  }

  const list = files ?? []
  return (
    <section onPaste={onPaste}>
      <SectionTitle
        action={
          canAttach && (
            <Button size="sm" variant="secondary" loading={busy} onClick={() => input.current?.click()}>
              <Paperclip className="h-3.5 w-3.5" /> Attach
            </Button>
          )
        }
      >{`Attachments${list.length ? ` · ${list.length}` : ''}`}</SectionTitle>
      <input ref={input} type="file" multiple hidden onChange={(e) => void upload(Array.from(e.target.files ?? []))} />
      {error && <Alert variant="error">{error}</Alert>}
      <div
        onDragOver={(e) => {
          if (!canAttach) return
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={`rounded-lg border border-dashed p-2 transition-colors ${over ? 'border-accent bg-accent-dim/40' : 'border-[color:var(--color-border)]'}`}
      >
        {files === null && !error && <p className="py-3 text-center text-xs text-[color:var(--color-text-faint)]">Loading…</p>}
        {files !== null && list.length === 0 && (
          <p className="flex items-center justify-center gap-2 py-3 text-center text-xs text-[color:var(--color-text-muted)]">
            <Upload className="h-3.5 w-3.5" /> {canAttach ? 'Drop files here, paste a picture, or use Attach.' : 'No files.'}
          </p>
        )}
        <ul className="grid gap-2 sm:grid-cols-2">
          {list.map((file) => (
            <li key={file.id} className="group flex items-center gap-2.5 rounded-lg border border-[color:var(--color-border)] bg-surface p-2">
              {file.image ? (
                <a href={tasksApi.attachmentUrl(file.id)} target="_blank" rel="noopener noreferrer" className="shrink-0">
                  <img src={tasksApi.attachmentUrl(file.id)} alt="" loading="lazy" className="h-10 w-10 rounded object-cover" />
                </a>
              ) : (
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-muted text-[color:var(--color-text-muted)]">
                  <FileText className="h-5 w-5" />
                </span>
              )}
              <div className="min-w-0 flex-1">
                <a href={tasksApi.attachmentUrl(file.id)} target="_blank" rel="noopener noreferrer" className="block truncate text-sm font-medium text-[color:var(--color-text)] hover:text-accent">
                  {file.name}
                </a>
                <p className="t-caption text-[color:var(--color-text-faint)]">
                  {formatBytes(file.size)} · {file.who?.display_name ?? 'Someone'} · {timeAgo(file.uploaded)}
                </p>
              </div>
              <a href={tasksApi.attachmentUrl(file.id, true)} aria-label={`Download ${file.name}`} className="interactive rounded p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]">
                <Download className="h-4 w-4" />
              </a>
              {file.can_delete && (
                <button type="button" aria-label={`Remove ${file.name}`} onClick={() => void remove(file)} className="interactive rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-negative-dim hover:text-negative">
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

// ------------------------------------------------------------------------------------------------------------------- comments

/** Replaces what is typed after an @ with the person chosen, in the form the server reads (`@[Name](user:ID)`). */
function MentionBox({ people, value, onChange, onSubmit, busy }: { people: TaskPersonRow[]; value: string; onChange: (v: string) => void; onSubmit: () => void; busy: boolean }) {
  const [at, setAt] = useState<{ start: number; caret: number; query: string } | null>(null)
  const matches = useMemo(() => (at ? people.filter((p) => p.display_name.toLowerCase().includes(at.query.toLowerCase())).slice(0, 6) : []), [at, people])

  const look = (text: string, caret: number) => {
    const found = /(^|\s)@([\w .'-]{0,30})$/.exec(text.slice(0, caret))
    setAt(found ? { start: caret - found[2].length - 1, caret, query: found[2] } : null)
  }
  const pick = (person: TaskPersonRow) => {
    if (!at) return
    onChange(`${value.slice(0, at.start)}@[${person.display_name}](user:${person.id}) ${value.slice(at.caret)}`)
    setAt(null)
  }

  return (
    <div className="relative">
      <Textarea
        rows={3}
        value={value}
        maxLength={5000}
        placeholder="Write a comment. Type @ to mention someone."
        aria-label="Comment"
        onChange={(e) => {
          onChange(e.target.value)
          look(e.target.value, e.target.selectionStart)
        }}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault()
            onSubmit()
          }
          if (e.key === 'Escape') setAt(null)
        }}
        disabled={busy}
      />
      {at && matches.length > 0 && (
        <ul role="listbox" aria-label="People" className="overlay absolute bottom-full left-0 z-10 mb-1 w-64 rounded-lg border border-[color:var(--color-border)] p-1">
          {matches.map((person) => (
            <li key={person.id}>
              <button type="button" role="option" aria-selected="false" onMouseDown={(e) => e.preventDefault()} onClick={() => pick(person)} className="interactive flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted">
                <Person person={person} size="xs" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** What a mention looks like when read: `@[Asha](user:4)` becomes **@Asha**. */
function readable(body: string): string {
  return body.replace(/@\[([^\]]+)\]\(user:\d+\)/g, '**@$1**')
}

export function CommentsPanel({ task, people, canComment, onCount }: { task: TaskDetail; people: TaskPersonRow[]; canComment: boolean; onCount: (n: number) => void }) {
  const [comments, setComments] = useState<TaskComment[] | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<{ id: number; body: string } | null>(null)
  const idem = useRef(newIdempotencyKey())

  const load = async () => {
    try {
      const found = (await tasksApi.comments(task.key)).comments
      setComments(found)
      onCount(found.filter((c) => !c.deleted).length)
    } catch (e) {
      setError(errorText(e))
    }
  }
  useEffect(() => {
    let cancelled = false
    tasksApi
      .comments(task.key)
      .then((found) => !cancelled && setComments(found.comments))
      .catch((e) => !cancelled && setError(errorText(e)))
    return () => {
      cancelled = true
    }
  }, [task.key])

  const post = async () => {
    if (!text.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      await tasksApi.addComment(task.key, text.trim(), idem.current)
      idem.current = newIdempotencyKey()
      setText('')
      await load()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const saveEdit = async () => {
    if (!editing || !editing.body.trim()) return
    try {
      await tasksApi.editComment(editing.id, editing.body.trim())
      setEditing(null)
      await load()
    } catch (e) {
      setError(errorText(e))
    }
  }
  const remove = async (id: number) => {
    if (!window.confirm('Delete this comment?')) return
    try {
      await tasksApi.deleteComment(id)
      await load()
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert variant="error">{error}</Alert>}
      {canComment && (
        <div className="space-y-2">
          <MentionBox people={people} value={text} onChange={setText} onSubmit={() => void post()} busy={busy} />
          <div className="flex items-center justify-between gap-2">
            <span className="t-caption text-[color:var(--color-text-faint)]">Ctrl + Enter to send</span>
            <Button size="sm" loading={busy} disabled={!text.trim()} onClick={() => void post()}>
              Comment
            </Button>
          </div>
        </div>
      )}
      {comments === null && !error && <p className="text-sm text-[color:var(--color-text-faint)]">Loading…</p>}
      {comments?.length === 0 && <p className="text-sm text-[color:var(--color-text-muted)]">No comments yet.</p>}
      <ul className="space-y-4">
        {comments?.map((c) => (
          <li key={c.id} className="flex gap-2.5">
            <Person person={c.author} name={false} />
            <div className="min-w-0 flex-1">
              <p className="text-xs">
                <span className="font-semibold text-[color:var(--color-text)]">{c.author?.display_name ?? 'Someone'}</span>{' '}
                <span className="text-[color:var(--color-text-faint)]" title={formatDateTime(c.created)}>
                  {timeAgo(c.created)}
                  {c.edited && !c.deleted ? ' · edited' : ''}
                </span>
              </p>
              {c.deleted ? (
                <p className="mt-1 text-sm italic text-[color:var(--color-text-faint)]">This comment was deleted.</p>
              ) : editing?.id === c.id ? (
                <div className="mt-1 space-y-2">
                  <Textarea rows={3} value={editing.body} onChange={(e) => setEditing({ id: c.id, body: e.target.value })} aria-label="Edit comment" />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => void saveEdit()}>
                      <Check className="h-3.5 w-3.5" /> Save
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="mt-1 text-sm">
                    <Markdown text={readable(c.body ?? '')} />
                  </div>
                  {(c.can_edit || c.can_delete) && (
                    <div className="mt-1 flex gap-3 text-xs text-[color:var(--color-text-faint)]">
                      {c.can_edit && (
                        <button type="button" className="hover:text-[color:var(--color-text)]" onClick={() => setEditing({ id: c.id, body: c.body ?? '' })}>
                          <Pencil className="mr-1 inline h-3 w-3" />
                          Edit
                        </button>
                      )}
                      {c.can_delete && (
                        <button type="button" className="hover:text-negative" onClick={() => void remove(c.id)}>
                          <Trash2 className="mr-1 inline h-3 w-3" />
                          Delete
                        </button>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------------------------------------------------------- activity

export function ActivityPanel({ taskKey }: { taskKey: string }) {
  const [lines, setLines] = useState<TaskActivityLine[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    tasksApi
      .activity(taskKey)
      .then((found) => !cancelled && setLines(found.activity))
      .catch((e) => !cancelled && setError(errorText(e)))
    return () => {
      cancelled = true
    }
  }, [taskKey])
  if (error) return <Alert variant="error">{error}</Alert>
  if (!lines) return <p className="text-sm text-[color:var(--color-text-faint)]">Loading…</p>
  if (!lines.length) return <p className="text-sm text-[color:var(--color-text-muted)]">Nothing has happened yet.</p>
  return (
    <ol className="space-y-3">
      {lines.map((line) => (
        <li key={line.id} className="flex gap-2.5">
          <Person person={line.who} name={false} size="xs" />
          <p className="min-w-0 flex-1 text-sm text-[color:var(--color-text-muted)]">
            <span className="font-medium text-[color:var(--color-text)]">{line.who?.display_name ?? 'Orion'}</span> {line.text}
            <span className="ml-2 text-xs text-[color:var(--color-text-faint)]" title={formatDateTime(line.at)}>
              {timeAgo(line.at)}
            </span>
          </p>
        </li>
      ))}
    </ol>
  )
}

// ---------------------------------------------------------------------------------------------------------------------- time

export function TimePanel({ task, canLog, onTime }: { task: TaskDetail; canLog: boolean; onTime: (time: TaskTime, spent: number) => void }) {
  const [spent, setSpent] = useState('')
  const [day, setDay] = useState(todayIso())
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const estimate = task.estimate_minutes
  const total = task.time.total

  const log = async () => {
    const minutes = parseDuration(spent)
    if (!minutes) return setError('Write the time like 90, 1h 30m or 2d.')
    setBusy(true)
    setError('')
    try {
      const result = await tasksApi.logTime(task.key, minutes, day, note.trim() || undefined)
      onTime(result, result.spent_minutes)
      setSpent('')
      setNote('')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const remove = async (id: number) => {
    try {
      const result = await tasksApi.deleteTime(task.key, id)
      onTime(result, result.spent_minutes)
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-[color:var(--color-text-muted)]">
        <strong className="text-[color:var(--color-text)]">{formatMinutes(total)}</strong> logged{estimate ? ` of ${formatMinutes(estimate)} estimated` : ''}.
      </p>
      {estimate ? (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className={`h-full rounded-full ${total > estimate ? 'bg-negative' : 'bg-accent'}`} style={{ width: `${Math.min(100, (total / estimate) * 100)}%` }} />
        </div>
      ) : null}
      {error && <p className="text-xs text-negative">{error}</p>}
      {canLog && (
        <form
          className="grid gap-2 sm:grid-cols-[7rem_9rem_1fr_auto]"
          onSubmit={(event) => {
            event.preventDefault()
            void log()
          }}
        >
          <Input value={spent} onChange={(e) => setSpent(e.target.value)} placeholder="1h 30m" aria-label="Time worked" />
          <Input type="date" max={todayIso()} value={day} onChange={(e) => setDay(e.target.value)} aria-label="Day worked" />
          <Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="What was done (optional)" aria-label="Note" />
          <Button type="submit" size="sm" loading={busy} className="sm:h-9">
            Log time
          </Button>
        </form>
      )}
      <ul className="divide-y divide-[color:var(--color-border)]">
        {task.time.logs.map((entry) => (
          <li key={entry.id} className="flex items-center gap-3 py-2 text-sm">
            <Person person={entry.who} size="xs" />
            <span className="font-medium text-[color:var(--color-text)]">{formatMinutes(entry.minutes)}</span>
            <span className="text-xs text-[color:var(--color-text-faint)]">{entry.date}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-[color:var(--color-text-muted)]">{entry.note}</span>
            {entry.can_delete && (
              <button type="button" aria-label="Remove this time" onClick={() => void remove(entry.id)} className="interactive rounded p-1 text-[color:var(--color-text-faint)] hover:text-negative">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
        {task.time.logs.length === 0 && <li className="py-2 text-sm text-[color:var(--color-text-muted)]">No time logged.</li>}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------------------------------- links

export function LinksPanel({
  task,
  canEdit,
  onLinks,
  onRecords,
  onOpen,
}: {
  task: TaskDetail
  canEdit: boolean
  onLinks: (links: TaskLink[]) => void
  onRecords: (records: TaskRecordLink[]) => void
  onOpen: (key: string) => void
}) {
  const [kind, setKind] = useState<'blocks' | 'relates' | 'duplicates'>('relates')
  const [other, setOther] = useState('')
  const [recordKind, setRecordKind] = useState('bill')
  const [ref, setRef] = useState('')
  const [error, setError] = useState('')

  const run = async (work: () => Promise<void>) => {
    setError('')
    try {
      await work()
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <div className="space-y-5">
      {error && <Alert variant="error">{error}</Alert>}

      <section>
        <SectionTitle>Linked tasks</SectionTitle>
        <ul className="space-y-1">
          {task.links.map((link) => (
            <li key={link.id} className="group flex items-center gap-2 rounded-md px-1 py-1 hover:bg-muted/50">
              <span className="w-28 shrink-0 text-xs text-[color:var(--color-text-muted)]">{LINK_LABEL[link.kind]}</span>
              <button type="button" onClick={() => onOpen(link.key)} className={`min-w-0 flex-1 truncate text-left text-sm hover:text-accent ${link.done ? 'text-[color:var(--color-text-faint)] line-through' : 'text-[color:var(--color-text)]'}`}>
                <span className="font-medium">{link.key}</span> {link.title}
              </button>
              <span className="shrink-0 text-xs text-[color:var(--color-text-faint)]">{link.status}</span>
              {canEdit && (
                <button
                  type="button"
                  aria-label={`Remove link to ${link.key}`}
                  onClick={() => void run(async () => onLinks((await tasksApi.removeLink(task.key, link.id)).links))}
                  className="interactive rounded p-1 text-[color:var(--color-text-faint)] opacity-0 hover:text-negative focus:opacity-100 group-hover:opacity-100"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </li>
          ))}
          {task.links.length === 0 && <li className="text-sm text-[color:var(--color-text-muted)]">No linked tasks.</li>}
        </ul>
        {canEdit && (
          <form
            className="mt-2 grid gap-2 sm:grid-cols-[9rem_1fr_auto]"
            onSubmit={(event) => {
              event.preventDefault()
              if (!other.trim()) return
              void run(async () => {
                onLinks((await tasksApi.addLink(task.key, kind, other.trim().toUpperCase())).links)
                setOther('')
              })
            }}
          >
            <Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} aria-label="How it is linked">
              <option value="relates">Relates to</option>
              <option value="blocks">Blocks</option>
              <option value="duplicates">Duplicates</option>
            </Select>
            <Input value={other} onChange={(e) => setOther(e.target.value)} placeholder="Task key, e.g. OPS-12" aria-label="Task to link" />
            <Button type="submit" size="sm" variant="secondary" disabled={!other.trim()} className="sm:h-9">
              <Link2 className="h-3.5 w-3.5" /> Link
            </Button>
          </form>
        )}
      </section>

      <section>
        <SectionTitle>Orion records</SectionTitle>
        <ul className="space-y-1">
          {task.records.map((record) => (
            <li key={record.id} className="group flex items-center gap-2 rounded-md px-1 py-1 hover:bg-muted/50">
              <span className="w-28 shrink-0 text-xs capitalize text-[color:var(--color-text-muted)]">{record.type}</span>
              <span className="min-w-0 flex-1 truncate text-sm text-[color:var(--color-text)]">{record.restricted ? 'A record you cannot see' : (record.label ?? record.ref)}</span>
              {canEdit && (
                <button
                  type="button"
                  aria-label="Remove this record link"
                  onClick={() => void run(async () => onRecords((await tasksApi.removeRecord(task.key, record.id)).records))}
                  className="interactive rounded p-1 text-[color:var(--color-text-faint)] opacity-0 hover:text-negative focus:opacity-100 group-hover:opacity-100"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </li>
          ))}
          {task.records.length === 0 && <li className="text-sm text-[color:var(--color-text-muted)]">Nothing linked. Tie the task to the bill, case, client or document it is about.</li>}
        </ul>
        {canEdit && (
          <form
            className="mt-2 grid gap-2 sm:grid-cols-[9rem_1fr_auto]"
            onSubmit={(event) => {
              event.preventDefault()
              if (!ref.trim()) return
              void run(async () => {
                onRecords((await tasksApi.addRecord(task.key, recordKind, ref.trim())).records)
                setRef('')
              })
            }}
          >
            <Select value={recordKind} onChange={(e) => setRecordKind(e.target.value)} aria-label="Kind of record">
              {RECORD_KINDS.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </Select>
            <Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder={RECORD_KINDS.find((k) => k.id === recordKind)?.hint} aria-label="Record" />
            <Button type="submit" size="sm" variant="secondary" disabled={!ref.trim()} className="sm:h-9">
              <Link2 className="h-3.5 w-3.5" /> Link
            </Button>
          </form>
        )}
      </section>
    </div>
  )
}
