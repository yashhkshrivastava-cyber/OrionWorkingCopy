import { useCallback, useEffect, useRef, useState } from 'react'
import { CircleCheck, CircleX, FolderPlus, FolderUp, Trash2, Upload } from 'lucide-react'
import { api } from '../../api/client'
import { useLumen } from '../../lumen/useLumen'
import type { DocumentFolder, DocumentOptions } from '../../types'
import { AiButton, AiNotice, AiProvenance, useAiTask } from '../ai/AiTask'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Checkbox, Field, Input, Select } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { fileSize, folderOrder, guessCategory } from './docUi'
import { FolderPicker } from './FolderPicker'
import { sameSpace, SpacePicker, type Space } from './SpacePicker'
import { TagPicker } from './TagPicker'
import { describe, fromDrop, fromFileList, type Picked, type PickedFile } from './uploadFolders'

type Row = {
  key: number
  file: File
  /** The folder it is in inside a folder that was chosen or dropped ('' for a file chosen on its own). */
  folder: string
  title: string
  category: string
  expiry: string
  state: 'ready' | 'sending' | 'done' | 'error'
  message: string
}

let nextKey = 1
const stem = (name: string) => name.replace(/\.[^.]+$/, '')

/** What is wrong with a file, if anything, as the server would see it. The server decides; this only saves a round trip. */
function problemWith(file: File, options: DocumentOptions): string {
  const extension = file.name.includes('.') ? `.${file.name.split('.').pop()!.toLowerCase()}` : ''
  if (!options.accepted.split(', ').includes(extension)) return `A file of that type cannot be kept. Upload one of: ${options.accepted}.`
  if (file.size > options.max_mb * 1024 * 1024) return `Larger than ${options.max_mb} MB.`
  if (file.size === 0) return 'The file is empty.'
  return ''
}

/** What a file in an uploaded folder is taken to be when its name says nothing: the folder is the person's own order, not a kind. */
function kindFor(file: File, folder: string, categories: string[]): string {
  const guessed = guessCategory(file.name, categories)
  return guessed || (folder && categories.includes('Other') ? 'Other' : '')
}

/** A file of a type that cannot be kept, inside an uploaded folder, is left out (a folder holds many such files); one chosen alone is shown with its problem. */
function keepable(item: PickedFile, options: DocumentOptions): boolean {
  return !item.folder || !problemWith(item.file, options).startsWith('A file of that type')
}

function buildRows(items: PickedFile[], categories: string[], options: DocumentOptions, preset?: string): Row[] {
  return items.map(({ file, folder }) => {
    const problem = problemWith(file, options)
    return {
      key: nextKey++,
      file,
      folder,
      title: stem(file.name),
      category: preset && categories.includes(preset) ? preset : kindFor(file, folder, categories),
      expiry: '',
      state: problem ? 'error' : 'ready',
      message: problem,
    }
  })
}

type Suggestion = { title: string; category: string; document_date: string; expiry_date: string; tags: string[]; description: string }

/**
 * "Suggest details" for one file: the AI reads the start of it and proposes a title, kind, expiry date and tags. Nothing
 * is filled in until the person presses "Use these"; the kind and the tags are checked again by the server.
 */
function SuggestDetails({
  file,
  scope,
  categories,
  onUse,
}: {
  file: File
  scope: string
  categories: string[]
  onUse: (suggestion: Suggestion) => void
}) {
  const task = useAiTask<{ suggestion: Suggestion; read_text: boolean }>()
  const found = task.result?.suggestion
  const kind = found && categories.includes(found.category) ? found.category : ''
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <AiButton
          disabled={task.busy}
          title="Reads the start of this file and suggests a title, kind, expiry date and tags. You check them before they are used."
          onClick={() => task.run((cloudOnce) => api.documentSuggestAi(file, scope, cloudOnce))}
        >
          Suggest details
        </AiButton>
      </div>
      <AiNotice task={task} />
      {task.phase === 'ok' && task.result && found && (
        <div className="space-y-2 rounded-lg border border-[color:var(--color-border)] bg-muted/50 p-3 text-xs">
          <div className="flex items-center justify-between gap-2">
            <p className="font-semibold">Suggested for this file</p>
            <AiProvenance where={task.result.where} provider={task.result.provider} />
          </div>
          {!task.result.read_text && (
            <p className="text-warning">The text of this file could not be read, so this is a guess from its name only.</p>
          )}
          <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1">
            {found.title && (
              <>
                <dt className="text-[color:var(--color-text-muted)]">Title</dt>
                <dd>{found.title}</dd>
              </>
            )}
            {kind && (
              <>
                <dt className="text-[color:var(--color-text-muted)]">Kind</dt>
                <dd>{kind}</dd>
              </>
            )}
            {found.expiry_date && (
              <>
                <dt className="text-[color:var(--color-text-muted)]">Expires</dt>
                <dd>{found.expiry_date}</dd>
              </>
            )}
            {found.tags.length > 0 && (
              <>
                <dt className="text-[color:var(--color-text-muted)]">Tags</dt>
                <dd>{found.tags.join(', ')}</dd>
              </>
            )}
            {found.description && (
              <>
                <dt className="text-[color:var(--color-text-muted)]">About</dt>
                <dd>{found.description}</dd>
              </>
            )}
          </dl>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                onUse({ ...found, category: kind })
                task.reset()
              }}
            >
              Use these
            </Button>
            <Button size="sm" variant="ghost" onClick={task.reset}>
              Ignore
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

type UploadModalProps = {
  open: boolean
  initialFiles: PickedFile[]
  /** Folders with nothing in them that were dropped with the files: they are made too. */
  initialEmptyFolders?: string[]
  /** How many files of a dropped folder were not read (hidden or temporary files), and whether the drop was cut at the most that is taken. */
  initialLeftOut?: { hidden: number; tooMany: boolean }
  initialSpace: Space | null
  /** The folders of `initialSpace` as the page already has them, so the Folder list is full the moment the dialog opens. */
  initialFolders: DocumentFolder[]
  initialCategory?: string
  initialFolderId?: number | null
  options: DocumentOptions
  onClose: () => void
  onUploaded: (summary: string) => void
  /** A folder was made in the dialog, so the page behind should reload its folders. */
  onFolderCreated: () => void
}

/**
 * File one or more documents: choose where they belong, then give each its title, kind and (if it has one) expiry date.
 * What the server will refuse (a type it does not keep, a file too large) is flagged here first, but the server decides.
 *
 * The dialog is built afresh each time it opens, so nothing from the last time (a different case, its folders, files
 * already sent) can be left over.
 */
export function UploadModal(props: UploadModalProps) {
  return props.open ? <UploadDialog {...props} /> : null
}

function UploadDialog({
  initialFiles,
  initialEmptyFolders,
  initialLeftOut,
  initialSpace,
  initialFolders,
  initialCategory,
  initialFolderId,
  options,
  onClose,
  onUploaded,
  onFolderCreated,
}: UploadModalProps) {
  const [space, setSpace] = useState<Space | null>(initialSpace)
  const [rows, setRows] = useState<Row[]>(() =>
    buildRows(
      initialFiles.filter((item) => keepable(item, options)),
      initialSpace ? options.categories[initialSpace.scope] : [],
      options,
      initialCategory,
    ),
  )
  const [emptyFolders, setEmptyFolders] = useState<string[]>(initialEmptyFolders ?? [])
  const [leftOut, setLeftOut] = useState(() => ({
    types: initialFiles.filter((item) => !keepable(item, options)).length,
    hidden: initialLeftOut?.hidden ?? 0,
    tooMany: initialLeftOut?.tooMany ?? false,
  }))
  const [progress, setProgress] = useState('')
  const folderPicker = useRef<HTMLInputElement>(null)
  const [status, setStatus] = useState('Active')
  const [confidential, setConfidential] = useState(false)
  const [tags, setTags] = useState<string[]>([])
  const [folderId, setFolderId] = useState(initialFolderId ? String(initialFolderId) : '')
  const [folders, setFolders] = useState<DocumentFolder[]>(initialFolders)
  const [foldersLoading, setFoldersLoading] = useState(false)
  const [foldersError, setFoldersError] = useState('')
  const [foldersTry, setFoldersTry] = useState(0)
  const [newFolder, setNewFolder] = useState<string | null>(null)
  const [makingFolder, setMakingFolder] = useState(false)
  const [busy, setBusy] = useState(false)
  const [browsing, setBrowsing] = useState(false)
  const lumen = useLumen()
  const [error, setError] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  const categories = space ? options.categories[space.scope] : []
  const check = useCallback((file: File) => problemWith(file, options), [options])

  // The folders of whichever place is chosen. An answer for a place that is no longer chosen is thrown away.
  useEffect(() => {
    if (!space) {
      setFolders([])
      setFoldersLoading(false)
      setFoldersError('')
      return
    }
    let stale = false
    setFoldersLoading(true)
    setFoldersError('')
    api
      .documentFolders({ scope: space.scope, case_code: space.case_code, client_code: space.client_code })
      .then((r) => {
        if (stale) return
        setFolders(r.folders)
        setFolderId((current) => (current && !r.folders.some((f) => String(f.id) === current) ? '' : current))
      })
      .catch((e: Error) => !stale && setFoldersError(e.message))
      .finally(() => !stale && setFoldersLoading(false))
    return () => {
      stale = true
    }
  }, [space, foldersTry])

  /** A folder chosen in the explorer: its case, client or the company becomes the place, and the folder is chosen in it. */
  const browsed = async (node: string, label: string) => {
    const found = await api.documentBrowse(node, { foldersOnly: true })
    const at = found.space
    if (!at?.scope) return 'Choose a folder, a case, a client or Company documents.'
    changeSpace({ scope: at.scope, case_code: at.case_code ?? undefined, client_code: at.client_code ?? undefined, label: at.scope === 'company' ? 'Company documents' : (label.split(' › ')[1] ?? label) })
    setFolderId(at.folder_id ? String(at.folder_id) : '')
    setBrowsing(false)
  }

  const changeSpace = (next: Space | null) => {
    if (next && space && sameSpace(next, space)) return
    setSpace(next)
    setFolderId('')
    setNewFolder(null)
    setFolders(next && initialSpace && sameSpace(next, initialSpace) ? initialFolders : [])
    const cats = next ? options.categories[next.scope] : []
    setRows((current) => current.map((row) => ({ ...row, category: cats.includes(row.category) ? row.category : kindFor(row.file, row.folder, cats) })))
  }

  /** Adds what was chosen or dropped: loose files as rows to fill in, files inside folders as rows that keep their folder. */
  const addPicked = (picked: Picked) => {
    const keep = picked.files.filter((item) => keepable(item, options))
    setLeftOut((current) => ({
      types: current.types + picked.files.length - keep.length,
      hidden: current.hidden + picked.hidden,
      tooMany: current.tooMany || picked.tooMany,
    }))
    setEmptyFolders((current) => [...new Set([...current, ...picked.emptyFolders])])
    setRows((current) => [...current, ...buildRows(keep, categories, options)])
  }

  const addFiles = (list: FileList | null) => {
    if (!list?.length) return
    addPicked(fromFileList(list))
    if (picker.current) picker.current.value = ''
  }

  const addFolder = (list: FileList | null) => {
    if (!list?.length) return
    addPicked(fromFileList(list))
    if (folderPicker.current) folderPicker.current.value = ''
  }

  const patch = (key: number, changes: Partial<Row>) => setRows((current) => current.map((row) => (row.key === key ? { ...row, ...changes } : row)))

  /** Puts a suggestion in the row. Only what was suggested replaces what is there; tags join the ones already typed. */
  const applySuggestion = (key: number, suggestion: Suggestion) => {
    const changes: Partial<Row> = {}
    if (suggestion.title.trim()) changes.title = suggestion.title.trim().slice(0, 150)
    if (suggestion.category) changes.category = suggestion.category
    if (suggestion.expiry_date) changes.expiry = suggestion.expiry_date
    patch(key, changes)
    if (suggestion.tags.length) {
      setTags((current) => {
        const lower = new Set(current.map((tag) => tag.toLowerCase()))
        return [...current, ...suggestion.tags.filter((tag) => !lower.has(tag.toLowerCase()))]
      })
    }
  }

  const sendable = rows.filter((row) => row.state === 'ready' || (row.state === 'error' && !check(row.file)))
  const ready = Boolean(space) && (sendable.length > 0 || emptyFolders.length > 0) && sendable.every((row) => row.category && row.title.trim())
  const inFolders = describe(
    rows.filter((row) => row.state !== 'done').map((row) => ({ file: row.file, folder: row.folder })),
    emptyFolders,
  )
  const looseRows = rows.filter((row) => !row.folder)
  const folderRows = rows.filter((row) => row.folder)

  const send = async () => {
    if (!space) return
    setBusy(true)
    setError('')
    let done = 0
    let failures = 0
    let madeFolders = 0
    const duplicates: string[] = []
    // The folders of an uploaded folder are made first (those that exist already are used), then every file goes into its own.
    let made: Record<string, number | null> = {}
    const wanted = [...new Set([...sendable.map((row) => row.folder).filter(Boolean), ...emptyFolders])]
    if (wanted.length) {
      try {
        const result = await api.createDocumentFolderTree({ scope: space.scope, case_code: space.case_code, client_code: space.client_code }, wanted, folderId ? Number(folderId) : null)
        made = result.folders
        madeFolders = result.created
        onFolderCreated()
        if (result.flattened) setError(`${result.flattened} ${result.flattened === 1 ? 'folder is' : 'folders are'} nested deeper than Orion keeps, so what was inside went into the deepest folder that fits.`)
      } catch (e) {
        setError((e as Error).message)
        setBusy(false)
        return
      }
    }
    let position = 0
    for (const row of sendable) {
      position += 1
      if (sendable.length > 1) setProgress(`Filing ${position} of ${sendable.length}…`)
      patch(row.key, { state: 'sending', message: '' })
      try {
        const into = row.folder ? made[row.folder] : folderId ? Number(folderId) : null
        const result = await api.uploadDocument(
          {
            scope: space.scope,
            case_code: space.case_code ?? '',
            client_code: space.client_code ?? '',
            folder_id: into ?? undefined,
            title: row.title.trim(),
            category: row.category,
            tags: tags.join(','),
            status,
            confidentiality: confidential ? 'Confidential' : 'Standard',
            expiry_date: row.expiry,
          },
          row.file,
        )
        done += 1
        if (result.duplicates.length) duplicates.push(`${row.file.name} (same file as ${result.duplicates.join(', ')})`)
        patch(row.key, { state: 'done', message: result.duplicates.length ? `Same file is already filed as ${result.duplicates.join(', ')}` : '' })
      } catch (e) {
        failures += 1
        patch(row.key, { state: 'error', message: (e as Error).message })
      }
    }
    setBusy(false)
    setProgress('')
    if (done > 0 || madeFolders > 0) {
      onUploaded(
        `${done} ${done === 1 ? 'document' : 'documents'} filed` +
          (madeFolders ? `, ${madeFolders} ${madeFolders === 1 ? 'folder' : 'folders'} made.` : '.') +
          (duplicates.length ? ` Already on file elsewhere: ${duplicates.join('; ')}.` : ''),
      )
    }
    if (failures === 0) onClose()
    else setRows((current) => current.filter((row) => row.state !== 'done'))
  }

  const ordered = folderOrder(folders)
  const chosenFolder = ordered.find((f) => String(f.id) === folderId)

  /** Makes the folder in the chosen place (inside the chosen folder, if one is chosen) and selects it. */
  const makeFolder = async () => {
    if (!space || newFolder === null || !newFolder.trim()) return
    setMakingFolder(true)
    setFoldersError('')
    try {
      const made = await api.createDocumentFolder(
        { scope: space.scope, case_code: space.case_code, client_code: space.client_code },
        newFolder,
        chosenFolder?.id ?? null,
      )
      const list = await api.documentFolders({ scope: space.scope, case_code: space.case_code, client_code: space.client_code })
      setFolders(list.folders)
      setFolderId(String(made.id))
      setNewFolder(null)
      onFolderCreated()
    } catch (e) {
      setFoldersError((e as Error).message)
    } finally {
      setMakingFolder(false)
    }
  }

  return (
    <Modal
      open
      title={lumen ? 'Add documents' : 'Upload documents'}
      size="2xl"
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={send} loading={busy} disabled={!ready}>
            <Upload className="h-4 w-4" /> {progress || (sendable.length === 0 && emptyFolders.length ? 'Make the folders' : `${lumen ? 'Add' : 'File'} ${sendable.length > 1 ? `${sendable.length} documents` : 'document'}`)}
          </Button>
        </>
      }
    >
      <div className={lumen ? 'flex flex-col gap-5' : 'space-y-5'}>
        {error && (
          <div className="order-first">
            <Alert variant="error">{error}</Alert>
          </div>
        )}

        <Field label={lumen ? 'Where should these be kept?' : 'Where does this belong?'} required className={lumen ? 'order-1' : undefined}>
          <SpacePicker value={space} onChange={changeSpace} />
          <div className="mt-1">
            <Button variant="ghost" size="sm" onClick={() => setBrowsing(true)}>
              Browse all folders…
            </Button>
          </div>
          {space && <p className="text-xs text-[color:var(--color-text-muted)]">Filing under: <span className="font-medium text-[color:var(--color-text)]">{space.label}</span></p>}
        </Field>

        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            void fromDrop(e.dataTransfer).then(addPicked)
          }}
          className={`border-2 border-dashed border-[color:var(--color-border-strong)] bg-muted/50 text-center ${lumen ? 'order-first rounded-[1.75rem] px-6 py-9' : 'rounded-xl px-4 py-5'}`}
        >
          {lumen && (
            <span className="lumen-orb mx-auto mb-3 grid h-14 w-14 place-items-center rounded-3xl text-white shadow-lg [background:linear-gradient(135deg,var(--lumen-indigo),var(--lumen-pink))]">
              <Upload className="h-7 w-7" aria-hidden="true" />
            </span>
          )}
          <p className={lumen ? 'font-display text-lg font-semibold text-[color:var(--color-text)]' : 'text-sm text-[color:var(--color-text)]'}>Drop files or whole folders here, or</p>
          <input ref={picker} type="file" multiple accept={options.accepted} className="sr-only" id="doc-upload-picker" onChange={(e) => addFiles(e.target.files)} />
          <input
            ref={folderPicker}
            type="file"
            className="sr-only"
            id="doc-upload-folder-picker"
            // A folder chooser is not in React's types; the browser then gives every file in the folder, with its path.
            {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
            onChange={(e) => addFolder(e.target.files)}
          />
          <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
            <label htmlFor="doc-upload-picker" className="interactive inline-flex h-8 cursor-pointer items-center rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 text-xs font-medium text-[color:var(--color-text)] shadow-card hover:bg-surface-hover">
              Choose files
            </label>
            <label htmlFor="doc-upload-folder-picker" className="interactive inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 text-xs font-medium text-[color:var(--color-text)] shadow-card hover:bg-surface-hover">
              <FolderUp className="h-3.5 w-3.5" aria-hidden="true" /> Choose a folder
            </label>
          </div>
          <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">
            {options.accepted}, up to {options.max_mb} MB each. A folder keeps its folders and subfolders.
          </p>
        </div>

        {(inFolders.folders > 0 || leftOut.types > 0 || leftOut.hidden > 0 || leftOut.tooMany) && (
          <div className="space-y-1 rounded-lg border border-[color:var(--color-border)] bg-muted/50 px-3 py-2 text-xs text-[color:var(--color-text-muted)]">
            {inFolders.folders > 0 && (
              <p className="text-[color:var(--color-text)]">
                {inFolders.files} {inFolders.files === 1 ? 'file' : 'files'} in {inFolders.folders} {inFolders.folders === 1 ? 'folder' : 'folders'} will be filed
                {chosenFolder ? ` inside ${chosenFolder.name}` : space ? ` in ${space.label}` : ''}, with the same folders made here (a folder that is already there is used, not doubled).
              </p>
            )}
            {leftOut.types > 0 && <p>{leftOut.types} {leftOut.types === 1 ? 'file' : 'files'} in the folder of a type Orion does not keep {leftOut.types === 1 ? 'was' : 'were'} left out.</p>}
            {leftOut.hidden > 0 && <p>{leftOut.hidden} hidden or temporary {leftOut.hidden === 1 ? 'file was' : 'files were'} left out.</p>}
            {leftOut.tooMany && <p className="text-warning">Only the first 1,000 files were taken. Upload the rest as a second folder.</p>}
          </div>
        )}

        {folderRows.length > 0 && (
          <ul className="max-h-72 divide-y divide-[color:var(--color-border)] overflow-y-auto rounded-xl border border-[color:var(--color-border)]" aria-label="Files in the folder">
            {folderRows.map((row) => (
              <li key={row.key} className="px-3 py-1.5">
                <div className="flex items-center gap-2">
                  {row.state === 'done' && <CircleCheck className="h-4 w-4 shrink-0 text-positive" aria-label="Filed" />}
                  {row.state === 'error' && <CircleX className="h-4 w-4 shrink-0 text-negative" aria-label="Problem" />}
                  {row.state === 'sending' && <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent text-accent" />}
                  <p className="min-w-0 flex-1 truncate text-xs text-[color:var(--color-text-muted)]" title={`${row.folder}/${row.file.name}`}>
                    <span>{row.folder}/</span>
                    <span className="font-medium text-[color:var(--color-text)]">{row.file.name}</span> · {fileSize(row.file.size)}
                  </p>
                  {row.state !== 'done' && row.state !== 'sending' && !check(row.file) && (
                    <Select value={row.category} aria-label={`Kind of ${row.file.name}`} onChange={(e) => patch(row.key, { category: e.target.value })} className="!h-7 !w-40 !py-0 text-xs">
                      <option value="">— Kind —</option>
                      {categories.map((category) => (
                        <option key={category} value={category}>
                          {category}
                        </option>
                      ))}
                    </Select>
                  )}
                  {row.state !== 'sending' && row.state !== 'done' && (
                    <button
                      type="button"
                      aria-label={`Remove ${row.file.name}`}
                      onClick={() => setRows((current) => current.filter((other) => other.key !== row.key))}
                      className="rounded p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {row.message && <p className={`pl-6 text-xs ${row.state === 'error' ? 'text-negative' : 'text-warning'}`}>{row.message}</p>}
              </li>
            ))}
          </ul>
        )}

        {looseRows.length > 0 && (
          <ul className="divide-y divide-[color:var(--color-border)] rounded-xl border border-[color:var(--color-border)]">
            {looseRows.map((row) => (
              <li key={row.key} className="space-y-2 px-3 py-3">
                <div className="flex items-center gap-2">
                  {row.state === 'done' && <CircleCheck className="h-4 w-4 shrink-0 text-positive" aria-label="Filed" />}
                  {row.state === 'error' && <CircleX className="h-4 w-4 shrink-0 text-negative" aria-label="Problem" />}
                  {row.state === 'sending' && <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent text-accent" />}
                  <p className="min-w-0 flex-1 truncate text-xs text-[color:var(--color-text-muted)]">
                    {row.file.name} · {fileSize(row.file.size)}
                  </p>
                  {row.state !== 'sending' && row.state !== 'done' && (
                    <button
                      type="button"
                      aria-label={`Remove ${row.file.name}`}
                      onClick={() => setRows((current) => current.filter((other) => other.key !== row.key))}
                      className="rounded p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {row.message && <p className={`text-xs ${row.state === 'error' ? 'text-negative' : 'text-warning'}`}>{row.message}</p>}
                {row.state !== 'done' && !check(row.file) && (
                  <div className="grid gap-2 sm:grid-cols-[1fr_12rem_9rem]">
                    <Input value={row.title} maxLength={150} aria-label="Title" placeholder="Title" onChange={(e) => patch(row.key, { title: e.target.value })} />
                    <Select value={row.category} aria-label="Kind of document" onChange={(e) => patch(row.key, { category: e.target.value })}>
                      <option value="">— Kind —</option>
                      {categories.map((category) => (
                        <option key={category} value={category}>
                          {category}
                        </option>
                      ))}
                    </Select>
                    <Input type="date" value={row.expiry} aria-label="Expiry date (if it has one)" title="Expiry date, if it has one" onChange={(e) => patch(row.key, { expiry: e.target.value })} />
                  </div>
                )}
                {row.state !== 'done' && row.state !== 'sending' && !check(row.file) && space && (
                  <SuggestDetails
                    file={row.file}
                    scope={space.scope}
                    categories={categories}
                    onUse={(suggestion) => applySuggestion(row.key, suggestion)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}

        <div className={`grid gap-3 sm:grid-cols-2 ${lumen ? 'order-2' : ''}`}>
          <Field label="Folder">
            <Select value={folderId} onChange={(e) => setFolderId(e.target.value)} disabled={!space}>
              <option value="">{!space ? 'Choose where it belongs first' : 'Not in a folder'}</option>
              {ordered.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  {folder.path}
                </option>
              ))}
            </Select>
            {space && foldersLoading && ordered.length === 0 && (
              <p className="text-xs text-[color:var(--color-text-muted)]">Loading folders…</p>
            )}
            {space && !foldersLoading && !foldersError && ordered.length === 0 && (
              <p className="text-xs text-[color:var(--color-text-muted)]">This place has no folders yet. It will be filed at the top level.</p>
            )}
            {foldersError && (
              <p className="text-xs text-negative">
                {foldersError}{' '}
                <button type="button" className="underline" onClick={() => setFoldersTry((n) => n + 1)}>
                  Reload the folders
                </button>
              </p>
            )}
            {space && newFolder === null && (
              <button
                type="button"
                onClick={() => setNewFolder('')}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline focus-visible:ring-2 focus-visible:ring-accent"
              >
                <FolderPlus className="h-3.5 w-3.5" aria-hidden="true" />
                {chosenFolder ? `New folder inside ${chosenFolder.name}` : 'New folder'}
              </button>
            )}
            {space && newFolder !== null && (
              <div className="flex gap-2">
                <Input
                  autoFocus
                  value={newFolder}
                  maxLength={80}
                  aria-label="New folder name"
                  placeholder={chosenFolder ? `Folder inside ${chosenFolder.name}` : 'Folder name'}
                  onChange={(e) => setNewFolder(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      void makeFolder()
                    }
                    if (e.key === 'Escape') {
                      e.preventDefault()
                      e.stopPropagation()
                      setNewFolder(null)
                    }
                  }}
                />
                <Button size="sm" loading={makingFolder} disabled={!newFolder.trim()} onClick={() => void makeFolder()}>
                  Create
                </Button>
                <Button size="sm" variant="secondary" disabled={makingFolder} onClick={() => setNewFolder(null)}>
                  Cancel
                </Button>
              </div>
            )}
          </Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {options.statuses
                .filter((s) => s === 'Active' || s === 'Draft')
                .map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Tags" className="sm:col-span-2">
            <TagPicker values={tags} onChange={setTags} max={options.max_tags} />
          </Field>
          <div className="sm:col-span-2">
            <Checkbox label="Confidential: only people who can change documents, and admins, can see it" checked={confidential} onChange={setConfidential} />
          </div>
        </div>
      </div>
      <FolderPicker
        open={browsing}
        title="Keep the documents in…"
        hint="Open a case, a client or Company documents, then the folder, and choose it."
        confirmLabel="Keep them here"
        startNode={space ? (space.scope === 'company' ? 'company' : `${space.scope}:${space.case_code ?? space.client_code}`) : 'root'}
        canMakeFolders
        onClose={() => setBrowsing(false)}
        onPick={browsed}
      />
    </Modal>
  )
}
