import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, CircleSlash, Pencil, ShieldAlert, Trash2, Users, XCircle } from 'lucide-react'
import { api } from '../../api/client'
import { timeAgo } from '../../formatTime'
import type { SqlHistoryRow, SqlSavedQuery } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox, Field, Input, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'

/** The queries kept for later, grouped by folder: the person's own, and those other administrators shared. */
export function SavedQueries({ reload, onOpen, onEdit }: { reload: number; onOpen: (query: SqlSavedQuery) => void; onEdit: (query: SqlSavedQuery) => void }) {
  const [queries, setQueries] = useState<SqlSavedQuery[] | null>(null)
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    api
      .sqlSaved()
      .then((r) => setQueries(r.queries))
      .catch((e: Error) => setError(e.message))
  }, [reload, tick])

  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase()
    const found = (queries ?? []).filter((q) => !needle || `${q.title} ${q.folder ?? ''} ${q.description ?? ''} ${q.sql}`.toLowerCase().includes(needle))
    const map = new Map<string, SqlSavedQuery[]>()
    for (const q of found) map.set(q.folder ?? '', [...(map.get(q.folder ?? '') ?? []), q])
    return [...map.entries()]
  }, [queries, search])

  const remove = async (query: SqlSavedQuery) => {
    if (!window.confirm(`Delete the saved query “${query.title}”?`)) return
    try {
      await api.sqlDeleteSaved(query.id)
      setTick((n) => n + 1)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="px-2 pb-2">
        <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a saved query" aria-label="Find a saved query" className="!min-h-0 !py-1.5 text-xs" />
      </div>
      {error && (
        <div className="px-2 pb-2">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}
      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-1 pb-2 text-[13px]">
        {queries === null && !error && <p className="px-3 py-2 text-xs text-[color:var(--color-text-muted)]">Loading…</p>}
        {queries !== null && queries.length === 0 && <p className="px-3 py-2 text-xs text-[color:var(--color-text-muted)]">Nothing is saved yet. Write a query and press Save (Ctrl+S).</p>}
        {groups.map(([folder, list]) => (
          <section key={folder || '~'} className="mb-2">
            {folder && <h3 className="px-2 pb-0.5 pt-1 text-[11px] font-semibold uppercase tracking-wide text-[color:var(--color-text-faint)]">{folder}</h3>}
            {list.map((q) => (
              <div key={q.id} className="group flex items-start gap-1 rounded-md px-2 py-1.5 hover:bg-muted">
                <button type="button" onClick={() => onOpen(q)} className="min-w-0 flex-1 text-left" title={`${q.sql.slice(0, 400)}`}>
                  <span className="flex items-center gap-1.5 font-medium text-[color:var(--color-text)]">
                    <span className="truncate">{q.title}</span>
                    {q.shared && <Users className="h-3 w-3 shrink-0 text-accent" aria-label="Shared with the other administrators" />}
                  </span>
                  <span className="block truncate text-[11px] text-[color:var(--color-text-muted)]">
                    {q.description || q.sql.replace(/\s+/g, ' ').slice(0, 80)}
                  </span>
                  <span className="block text-[10px] text-[color:var(--color-text-faint)]">
                    {q.mine ? 'Yours' : `Shared by ${q.owner ?? 'someone'}`} · {timeAgo(q.updated)}
                  </span>
                </button>
                {q.mine && (
                  <span className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button type="button" onClick={() => onEdit(q)} aria-label={`Rename or share ${q.title}`} className="rounded p-1 text-[color:var(--color-text-muted)] hover:bg-surface">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" onClick={() => void remove(q)} aria-label={`Delete ${q.title}`} className="rounded p-1 text-[color:var(--color-text-muted)] hover:bg-surface hover:text-negative">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                )}
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  )
}

const STATUS = {
  ok: { icon: CheckCircle2, tone: 'text-positive', label: 'Ran' },
  error: { icon: XCircle, tone: 'text-negative', label: 'Failed' },
  blocked: { icon: ShieldAlert, tone: 'text-warning', label: 'Refused' },
  cancelled: { icon: CircleSlash, tone: 'text-[color:var(--color-text-faint)]', label: 'Cancelled' },
} as const

/** What has been run, newest first. Every run is kept for good: who, what, in which mode and how it ended. */
export function QueryHistory({ reload, onOpen }: { reload: number; onOpen: (sql: string) => void }) {
  const [runs, setRuns] = useState<SqlHistoryRow[] | null>(null)
  const [everyone, setEveryone] = useState(false)
  const [search, setSearch] = useState('')
  const [needle, setNeedle] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setNeedle(search), 300)
    return () => window.clearTimeout(timer)
  }, [search])

  const load = useCallback(() => {
    api
      .sqlHistory(everyone, needle)
      .then((r) => setRuns(r.runs))
      .catch((e: Error) => setError(e.message))
  }, [everyone, needle])
  useEffect(load, [load, reload])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-1.5 px-2 pb-2">
        <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search what was run" aria-label="Search what was run" className="!min-h-0 !py-1.5 text-xs" />
        <Checkbox label="Everyone’s runs" checked={everyone} onChange={setEveryone} />
      </div>
      {error && (
        <div className="px-2 pb-2">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}
      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-1 pb-2 text-[13px]">
        {runs === null && !error && <p className="px-3 py-2 text-xs text-[color:var(--color-text-muted)]">Loading…</p>}
        {runs !== null && runs.length === 0 && <p className="px-3 py-2 text-xs text-[color:var(--color-text-muted)]">Nothing has been run yet.</p>}
        {runs?.map((run) => {
          const status = STATUS[run.status]
          const Icon = status.icon
          return (
            <button key={run.id} type="button" onClick={() => onOpen(run.sql)} className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted" title={run.error ?? run.sql.slice(0, 500)}>
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${status.tone}`} aria-label={status.label} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-mono text-xs text-[color:var(--color-text)]">{run.sql.replace(/\s+/g, ' ').slice(0, 90)}</span>
                <span className="block text-[10px] text-[color:var(--color-text-faint)]">
                  {timeAgo(run.at)}
                  {everyone && run.username ? ` · ${run.username}` : ''}
                  {run.mode === 'write' ? ' · changes allowed' : ''}
                  {run.status === 'ok' ? ` · ${run.rows_returned ? `${run.rows_returned.toLocaleString('en-IN')} rows` : `${run.rows_affected} affected`}${run.rolled_back ? ', rolled back' : ''}` : ` · ${status.label.toLowerCase()}`}
                  {run.duration_ms !== null ? ` · ${run.duration_ms} ms` : ''}
                </span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** The dialog for keeping a query: a title, an optional folder and note, and whether the other administrators may see it. */
export function SaveQueryModal({
  open,
  initial,
  onClose,
  onSave,
}: {
  open: boolean
  initial: { title: string; folder: string; description: string; shared: boolean; isNew: boolean }
  onClose: () => void
  onSave: (values: { title: string; folder: string; description: string; shared: boolean; asCopy: boolean }) => Promise<void>
}) {
  const [title, setTitle] = useState(initial.title)
  const [folder, setFolder] = useState(initial.folder)
  const [description, setDescription] = useState(initial.description)
  const [shared, setShared] = useState(initial.shared)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setTitle(initial.title)
    setFolder(initial.folder)
    setDescription(initial.description)
    setShared(initial.shared)
    setError('')
  }, [open, initial])

  const save = async (asCopy: boolean) => {
    setBusy(true)
    setError('')
    try {
      await onSave({ title, folder, description, shared, asCopy })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={initial.isNew ? 'Save this query' : 'Save changes to this query'}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          {!initial.isNew && (
            <Button variant="secondary" onClick={() => void save(true)} loading={busy} disabled={!title.trim()}>
              Save as a new query
            </Button>
          )}
          <Button onClick={() => void save(false)} loading={busy} disabled={!title.trim()}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Alert variant="error">{error}</Alert>}
        <Field label="Title" required>
          <Input autoFocus value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="Folder" hint="Optional. Queries with the same folder are listed together.">
          <Input value={folder} maxLength={60} onChange={(event) => setFolder(event.target.value)} />
        </Field>
        <Field label="Note">
          <Textarea rows={2} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} />
        </Field>
        <Checkbox label="Share with the other administrators (they can run and copy it, not change it)" checked={shared} onChange={setShared} />
      </div>
    </Modal>
  )
}
