import { DocumentDriveLinks } from './DocumentDriveLinks'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Lock, Maximize2, Pencil, RotateCcw, Trash2, Upload } from 'lucide-react'
import { api } from '../../api/client'
import { formatDateTime } from '../../formatTime'
import type { DocumentDetail, DocumentFolder, DocumentOptions } from '../../types'
import { Alert, Badge } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Drawer } from '../ui/Drawer'
import { FullScreenViewer } from '../ui/FullScreenViewer'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { PdfFrame, saveBlob } from '../ui/PdfPreview'
import { Tabs } from '../ui/Tabs'
import { TabLink } from '../ui/TabLink'
import { useLumen } from '../../lumen/useLumen'
import { ACTION_LABEL, day, ExpiryBadge, fileSize, FileTypeIcon, folderOrder, spaceLabel, StatusBadge } from './docUi'
import { sameSpace, SpacePicker, type Space } from './SpacePicker'
import { TagPicker } from './TagPicker'

type Tab = 'details' | 'versions' | 'activity'

/**
 * One document in depth: the file, its details (which can be edited), every version, and who has done what to it.
 * `canWrite` and `isAdmin` only decide what is shown; the server decides what is allowed.
 */
export function DocumentDrawer({
  id,
  options,
  canWrite,
  isAdmin,
  onClose,
  onChanged,
}: {
  id: number | null
  options: DocumentOptions
  canWrite: boolean
  isAdmin: boolean
  onClose: () => void
  /** The document, or the list it is in, changed. */
  onChanged: (message?: string) => void
}) {
  const lumen = useLumen()
  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('details')
  const [editing, setEditing] = useState(false)
  const [preview, setPreview] = useState<{ blob: Blob; type: string } | null>(null)
  const [busy, setBusy] = useState('')

  const load = useCallback(() => {
    if (id === null) return
    api
      .document(id)
      .then((d) => {
        setDoc(d)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
  }, [id])

  useEffect(() => {
    setDoc(null)
    setError('')
    setTab('details')
    setEditing(false)
    setPreview(null)
    load()
  }, [load])

  // The file is shown as soon as the document is opened, when a browser can draw it. That counts as viewing it.
  const shownVersion = useRef<string>('')
  useEffect(() => {
    if (!doc || !doc.inline) return
    const key = `${doc.id}:${doc.current_version}`
    if (shownVersion.current === key) return
    shownVersion.current = key
    api
      .documentFile(doc.id)
      .then((blob) => setPreview({ blob, type: doc.content_type }))
      .catch((e: Error) => setError(e.message))
  }, [doc])

  useEffect(() => {
    if (id === null) shownVersion.current = ''
  }, [id])

  /** Does the work, then refreshes (or closes). Returns whether it worked, so a form can stay open when it did not. */
  const run = async (label: string, work: () => Promise<unknown>, message?: string, thenClose = false): Promise<boolean> => {
    setBusy(label)
    setError('')
    try {
      await work()
      onChanged(message)
      if (thenClose) onClose()
      else load()
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy('')
    }
  }

  const download = async (version?: number, name?: string) => {
    if (!doc) return
    setBusy('download')
    try {
      saveBlob(await api.documentFile(doc.id, version), name ?? doc.file_name)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  const open = id !== null

  return (
    <Drawer
      open={open}
      title={doc?.title ?? 'Document'}
      onClose={onClose}
      subtitle={
        doc ? (
          <span>
            {doc.code} · {spaceLabel(doc)}
            {doc.folder_path.length ? ` · ${doc.folder_path.map((f) => f.name).join(' / ')}` : ''}
          </span>
        ) : undefined
      }
      badge={
        doc ? (
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusBadge status={doc.status} />
            {doc.confidentiality === 'Confidential' && (
              <Badge variant="violet">
                <Lock className="mr-1 h-3 w-3" aria-hidden="true" /> Confidential
              </Badge>
            )}
            {doc.is_deleted && <Badge variant="rose">In trash</Badge>}
            <ExpiryBadge doc={doc} />
          </span>
        ) : undefined
      }
      footer={
        doc && (
          <>
            <Button variant="secondary" onClick={() => download()} loading={busy === 'download'}>
              <Download className="h-4 w-4" /> Download
            </Button>
            {canWrite && !doc.is_deleted && (
              <Button
                variant="secondary"
                onClick={() => {
                  setTab('details') // the form is on the Details tab, whichever tab the person is looking at
                  setEditing(true)
                }}
                disabled={editing}
              >
                <Pencil className="h-4 w-4" /> Edit details
              </Button>
            )}
            {canWrite && !doc.is_deleted && !doc.source && (
              <Button
                variant="ghost"
                loading={busy === 'delete'}
                onClick={() => {
                  if (window.confirm(`Move "${doc.title}" to the trash? You can restore it from there.`)) {
                    void run('delete', () => api.deleteDocument(doc.id), 'Moved to the trash.', true)
                  }
                }}
              >
                <Trash2 className="h-4 w-4" /> Delete
              </Button>
            )}
            {canWrite && doc.is_deleted && (
              <Button loading={busy === 'restore'} onClick={() => void run('restore', () => api.restoreDocument(doc.id), 'Document restored.', true)}>
                <RotateCcw className="h-4 w-4" /> Restore
              </Button>
            )}
            {canWrite && isAdmin && doc.is_deleted && (
              <Button
                variant="danger"
                loading={busy === 'purge'}
                onClick={() => {
                  if (window.confirm(`Delete "${doc.title}" for good, with all its versions and its history? This cannot be undone.`)) {
                    void run('purge', () => api.purgeDocument(doc.id), 'Deleted for good.', true)
                  }
                }}
              >
                <Trash2 className="h-4 w-4" /> Delete for good
              </Button>
            )}
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
      {!doc && !error && <p className="text-sm text-[color:var(--color-text-muted)]">Loading…</p>}
      {doc && (
        <div className="space-y-5">
          {lumen && <KeyFacts doc={doc} />}
          <FilePreview doc={doc} preview={preview} onDownload={() => download()} compact={lumen} />

          <Tabs<Tab>
            tabs={[
              { id: 'details', label: 'Details' },
              { id: 'versions', label: `Versions (${doc.versions.length})` },
              { id: 'activity', label: 'Activity' },
            ]}
            active={tab}
            onChange={setTab}
          />

          {tab === 'details' &&
            (editing ? (
              <EditForm
                doc={doc}
                filed={Boolean(doc.source)}
                options={options}
                busy={busy === 'save'}
                onCancel={() => setEditing(false)}
                onSave={(changes) =>
                  void run('save', () => api.updateDocument(doc.id, changes), 'Changes saved.').then((ok) => ok && setEditing(false))
                }
              />
            ) : (
              <Details doc={doc} />
            ))}

          {tab === 'versions' && (
            <Versions
              doc={doc}
              canWrite={canWrite && !doc.is_deleted && !doc.source}
              busy={busy}
              onDownload={download}
              onUpload={(file, note) => run('version', () => api.uploadDocumentVersion(doc.id, file, note), 'New version saved.')}
              onRestore={(n) => run('restore-version', () => api.restoreDocumentVersion(doc.id, n), `Version ${n} is current again.`)}
            />
          )}

          {tab === 'activity' && (
            <ol className="space-y-2">
              {doc.activity.map((entry, index) => (
                <li key={index} className="flex gap-3 rounded-lg bg-muted/60 px-3 py-2 text-sm">
                  <span className="w-36 shrink-0 text-xs text-[color:var(--color-text-muted)]">{formatDateTime(entry.at)}</span>
                  <span className="min-w-0 flex-1 text-[color:var(--color-text)]">
                    <span className="font-medium">{ACTION_LABEL[entry.action] ?? entry.action}</span>
                    {entry.by_name ? <span className="text-[color:var(--color-text-muted)]"> by {entry.by_name}</span> : null}
                    {entry.detail ? <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{entry.detail}</span> : null}
                  </span>
                </li>
              ))}
              {doc.activity.length === 100 && <li className="text-xs text-[color:var(--color-text-muted)]">Showing the latest 100.</li>}
            </ol>
          )}
        </div>
      )}
    </Drawer>
  )
}

function FilePreview({ doc, preview, onDownload, compact = false }: { doc: DocumentDetail; preview: { blob: Blob; type: string } | null; onDownload: () => void; compact?: boolean }) {
  const height = compact ? 'h-[min(26rem,48dvh)]' : 'h-[min(34rem,60dvh)]'
  const [url, setUrl] = useState('')
  const [full, setFull] = useState(false)
  useEffect(() => {
    if (!preview || preview.type === 'application/pdf') return
    const next = URL.createObjectURL(preview.blob)
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [preview])

  const expand = preview && doc.inline && (
    <div className="mb-2 flex justify-end">
      <Button variant="secondary" size="sm" onClick={() => setFull(true)}>
        <Maximize2 className="h-4 w-4" /> Full screen
      </Button>
    </div>
  )
  const viewer = full && preview && <FullScreenViewer blob={preview.blob} type={preview.type} title={doc.file_name} filename={doc.file_name} onClose={() => setFull(false)} />

  if (doc.inline && preview?.type === 'application/pdf') {
    return (
      <div>
        {expand}
        <PdfFrame blob={preview.blob} title={doc.file_name} className={height} />
        {viewer}
      </div>
    )
  }
  if (doc.inline && preview && url) {
    return (
      <div>
        {expand}
        <img src={url} alt={doc.file_name} className={`mx-auto max-w-full rounded-lg border border-[color:var(--color-border)] object-contain ${compact ? 'max-h-[min(26rem,48dvh)]' : 'max-h-[min(34rem,60dvh)]'}`} />
        {viewer}
      </div>
    )
  }
  if (doc.inline) return <div className="flex h-40 items-center justify-center rounded-xl bg-muted text-sm text-[color:var(--color-text-muted)]">Loading preview…</div>
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl bg-muted px-4 py-8 text-center">
      <FileTypeIcon type={doc.content_type} className="h-10 w-10 text-accent" />
      <p className="text-sm font-medium text-[color:var(--color-text)]">{doc.file_name}</p>
      <p className="text-xs text-[color:var(--color-text-muted)]">This kind of file cannot be shown here. Download it to open it.</p>
      <Button variant="secondary" size="sm" onClick={onDownload}>
        <Download className="h-4 w-4" /> Download
      </Button>
    </div>
  )
}

/** The four things people open a paper to find out, before anything else: does it run out, what is it, whose is it, which version. */
function KeyFacts({ doc }: { doc: DocumentDetail }) {
  const facts: { label: string; value: React.ReactNode }[] = [
    { label: 'Expires', value: doc.expiry_date ? <ExpiryBadge doc={doc} /> : 'No expiry' },
    { label: 'Kind', value: doc.category },
    { label: 'Belongs to', value: spaceLabel(doc) },
    { label: 'Version', value: `${doc.current_version} · ${fileSize(doc.size_bytes)}` },
  ]
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {facts.map(({ label, value }) => (
        <div key={label} className="min-w-0 rounded-2xl bg-muted/60 px-3 py-2.5">
          <dt className="t-caption text-[color:var(--color-text-faint)]">{label}</dt>
          <dd className="mt-0.5 truncate text-sm font-semibold text-[color:var(--color-text)]">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function Details({ doc }: { doc: DocumentDetail }) {
  const rows: [string, React.ReactNode][] = [
    ['Kind', doc.category],
    ['Belongs to', spaceLabel(doc)],
    ['Document date', day(doc.document_date) || '—'],
    ['Expires', doc.expiry_date ? `${day(doc.expiry_date)} (reminder ${doc.reminder_days} days before)` : '—'],
    ['Current file', `${doc.file_name} · ${fileSize(doc.size_bytes)} · version ${doc.current_version}`],
    ['Filed', `${formatDateTime(doc.created_timestamp)}${doc.created_by_name ? ` by ${doc.created_by_name}` : ''}`],
    ['Last changed', `${formatDateTime(doc.last_updated_timestamp)}${doc.updated_by_name ? ` by ${doc.updated_by_name}` : ''}`],
  ]
  return (
    <div className="space-y-4">
      {doc.source && (
        <div className="rounded-xl border border-[color:var(--color-border)] bg-muted/60 px-3 py-2 text-sm text-[color:var(--color-text)]">
          <p>
            Filed automatically from{' '}
            {doc.source.path ? (
              <TabLink to={doc.source.path} className="font-medium text-accent hover:underline">
                {doc.source.label}
              </TabLink>
            ) : (
              <span className="font-medium">{doc.source.label}</span>
            )}
            . It follows its source: change it there, and it is updated here.
          </p>
        </div>
      )}
      <DocumentDriveLinks documentId={doc.id} />
      {doc.placements.length > 0 && (
        <div className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm">
          <p className="eyebrow">Also filed in</p>
          <ul className="mt-1 space-y-0.5 text-[color:var(--color-text)]">
            {doc.placements.map((place, index) => (
              <li key={index}>
                {place.scope === 'client' ? place.client_name : place.scope === 'case' ? place.case_name : 'Company documents'}
                {place.folder_path.length ? ` · ${place.folder_path.map((f) => f.name).join(' / ')}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="eyebrow">{label}</dt>
            <dd className="mt-0.5 break-words text-sm text-[color:var(--color-text)]">{value}</dd>
          </div>
        ))}
      </dl>
      {doc.description && <p className="whitespace-pre-wrap rounded-lg bg-muted/60 px-3 py-2 text-sm text-[color:var(--color-text)]">{doc.description}</p>}
      {doc.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {doc.tags.map((tag) => (
            <Badge key={tag} variant="cyan">
              {tag}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

function EditForm({
  doc,
  filed,
  options,
  busy,
  onCancel,
  onSave,
}: {
  doc: DocumentDetail
  /** Filed automatically from a bill, an employee or an EMD: only its tags and description are changed here. */
  filed: boolean
  options: DocumentOptions
  busy: boolean
  onCancel: () => void
  onSave: (changes: Record<string, unknown>) => void
}) {
  const original: Space = {
    scope: doc.scope,
    case_code: doc.case_code ?? undefined,
    client_code: doc.scope === 'client' ? (doc.client_code ?? undefined) : undefined,
    label: spaceLabel(doc),
  }
  const [space, setSpace] = useState<Space | null>(original)
  const [title, setTitle] = useState(doc.title)
  const [category, setCategory] = useState(doc.category)
  const [status, setStatus] = useState<string>(doc.status)
  const [confidential, setConfidential] = useState(doc.confidentiality === 'Confidential')
  const [documentDate, setDocumentDate] = useState(doc.document_date ?? '')
  const [expiry, setExpiry] = useState(doc.expiry_date ?? '')
  const [reminder, setReminder] = useState(String(doc.reminder_days))
  const [tags, setTags] = useState<string[]>(doc.tags)
  const [description, setDescription] = useState(doc.description ?? '')
  const [folderId, setFolderId] = useState(doc.folder_id ? String(doc.folder_id) : '')
  const [folders, setFolders] = useState<DocumentFolder[]>([])
  const [moving, setMoving] = useState(false)

  const moved = space !== null && !sameSpace(space, original)
  const categories = space ? options.categories[space.scope] : []

  const [foldersLoading, setFoldersLoading] = useState(true)
  const [foldersError, setFoldersError] = useState('')

  // The folders of the place the document is (or is being moved) to. An answer for a place no longer chosen is dropped.
  useEffect(() => {
    if (!space) return
    let stale = false
    setFoldersLoading(true)
    setFoldersError('')
    api
      .documentFolders({ scope: space.scope, case_code: space.case_code, client_code: space.client_code })
      .then((r) => !stale && setFolders(r.folders))
      .catch((e: Error) => !stale && setFoldersError(e.message))
      .finally(() => !stale && setFoldersLoading(false))
    return () => {
      stale = true
    }
  }, [space])

  const save = () => {
    if (filed) {
      onSave({ tags, description })
      return
    }
    const changes: Record<string, unknown> = {
      title,
      category,
      status,
      confidentiality: confidential ? 'Confidential' : 'Standard',
      document_date: documentDate || null,
      expiry_date: expiry || null,
      reminder_days: Number(reminder) || 0,
      tags,
      description,
      folder_id: folderId ? Number(folderId) : null,
    }
    if (moved && space) {
      changes.scope = space.scope
      changes.case_code = space.case_code ?? null
      changes.client_code = space.client_code ?? null
    }
    onSave(changes)
  }

  if (filed) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-[color:var(--color-text-muted)]">
          This document was filed automatically from {doc.source?.label}. Its title, place and file are kept in step with it, so only its tags and
          description can be changed here.
        </p>
        <Field label="Tags">
          <TagPicker values={tags} onChange={setTags} max={options.max_tags} />
        </Field>
        <Field label="Description">
          <Textarea value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy}>
            Save changes
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Title" required className="sm:col-span-2">
          <Input value={title} maxLength={150} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Kind of document" required>
          <Select value={category} onChange={(e) => setCategory(e.target.value)}>
            {!categories.includes(category) && <option value="">— Choose —</option>}
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {options.statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Document date">
          <Input type="date" value={documentDate} onChange={(e) => setDocumentDate(e.target.value)} />
        </Field>
        <Field label="Expiry date">
          <Input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
        </Field>
        <Field label="Remind me this many days before expiry">
          <Input type="number" min={0} max={365} value={reminder} onChange={(e) => setReminder(e.target.value)} />
        </Field>
        <Field label="Folder">
          <Select value={folderId} onChange={(e) => setFolderId(e.target.value)}>
            <option value="">Not in a folder</option>
            {folderOrder(folders).map((f) => (
              <option key={f.id} value={f.id}>
                {f.path}
              </option>
            ))}
            {/* Until the list arrives the current folder must still be an option, or the box would show "Not in a folder". */}
            {foldersLoading && folderId && !folders.some((f) => String(f.id) === folderId) && <option value={folderId}>Loading…</option>}
          </Select>
          {foldersError && <p className="text-xs text-negative">The folders could not be loaded ({foldersError}).</p>}
        </Field>
        <Field label="Tags" className="sm:col-span-2">
          <TagPicker values={tags} onChange={setTags} max={options.max_tags} />
        </Field>
        <Field label="Description" className="sm:col-span-2">
          <Textarea value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm text-[color:var(--color-text)] sm:col-span-2">
          <input type="checkbox" checked={confidential} onChange={(e) => setConfidential(e.target.checked)} />
          Confidential: only people who can change documents, and admins, can see it
        </label>
      </div>

      <div className="rounded-xl border border-[color:var(--color-border)] p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-[color:var(--color-text)]">
            Belongs to <span className="font-medium">{space?.label ?? '—'}</span>
            {moved ? <span className="text-warning"> (will be moved)</span> : null}
          </p>
          <Button variant="ghost" size="sm" onClick={() => setMoving((m) => !m)}>
            {moving ? 'Done' : 'Move to another case, client or the company'}
          </Button>
        </div>
        {moving && (
          <div className="mt-3">
            <SpacePicker
              value={space}
              onChange={(next) => {
                setSpace(next ?? original)
                if (next && !options.categories[next.scope].includes(category)) setCategory('')
                setFolderId('')
                setFolders([])
              }}
            />
            {moved && <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">Pick the kind of document again if it no longer fits, and a folder in the new place.</p>}
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button onClick={save} loading={busy} disabled={!title.trim() || !category}>
          Save changes
        </Button>
      </div>
    </div>
  )
}

function Versions({
  doc,
  canWrite,
  busy,
  onDownload,
  onUpload,
  onRestore,
}: {
  doc: DocumentDetail
  canWrite: boolean
  busy: string
  onDownload: (version: number, name: string) => void
  onUpload: (file: File, note: string) => Promise<boolean>
  onRestore: (version: number) => Promise<boolean>
}) {
  const [file, setFile] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  return (
    <div className="space-y-4">
      {canWrite && (
        <div className="space-y-3 rounded-xl border border-[color:var(--color-border)] p-3">
          <p className="text-sm font-medium text-[color:var(--color-text)]">Upload a new version</p>
          <input
            ref={picker}
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-[color:var(--color-text-muted)] file:mr-3 file:rounded-lg file:border-0 file:bg-muted file:px-3 file:py-2 file:text-sm file:font-medium file:text-[color:var(--color-text)]"
          />
          <Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="What changed? For example Corrigendum 2 added" />
          <Button
            loading={busy === 'version'}
            disabled={!file}
            onClick={() =>
              file &&
              void onUpload(file, note).then((ok) => {
                if (!ok) return
                setFile(null)
                setNote('')
                if (picker.current) picker.current.value = ''
              })
            }
          >
            <Upload className="h-4 w-4" /> Upload version {doc.current_version + 1}
          </Button>
          <p className="text-xs text-[color:var(--color-text-muted)]">The earlier versions are kept. Nothing is overwritten.</p>
        </div>
      )}
      <ul className="divide-y divide-[color:var(--color-border)] rounded-xl border border-[color:var(--color-border)]">
        {doc.versions.map((v) => (
          <li key={v.version_no} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5">
            <span className="w-10 shrink-0 text-sm font-semibold text-[color:var(--color-text)]">v{v.version_no}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-[color:var(--color-text)]">
                {v.file_name} <span className="text-xs text-[color:var(--color-text-muted)]">· {fileSize(v.size_bytes)}</span>
                {v.version_no === doc.current_version && <span className="ml-2"><Badge variant="emerald">Current</Badge></span>}
              </p>
              <p className="truncate text-xs text-[color:var(--color-text-muted)]">
                {formatDateTime(v.uploaded_timestamp)}
                {v.uploaded_by_name ? ` · ${v.uploaded_by_name}` : ''}
                {v.change_note ? ` · ${v.change_note}` : ''}
              </p>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="secondary" size="sm" onClick={() => onDownload(v.version_no, v.file_name)}>
                <Download className="h-4 w-4" /> Download
              </Button>
              {canWrite && v.version_no !== doc.current_version && (
                <Button variant="ghost" size="sm" loading={busy === 'restore-version'} onClick={() => void onRestore(v.version_no)}>
                  <RotateCcw className="h-4 w-4" /> Make current
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
