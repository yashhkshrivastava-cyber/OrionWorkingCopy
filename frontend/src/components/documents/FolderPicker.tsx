import { useCallback, useEffect, useState } from 'react'
import { ArrowUp, ChevronRight, FolderPlus } from 'lucide-react'
import { api } from '../../api/client'
import type { DriveListing, ExplorerPage } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Input } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { EntryIcon, isDestination } from './explorerUi'
import { driveFolderOf, driveNode } from './driveNodes'

/** A Drive folder shown the way the picker shows an Orion one, so one list draws both. */
function fromDrive(listing: DriveListing): ExplorerPage {
  const id = driveNode(listing.folder)
  return {
    node: { id, kind: 'folder', label: listing.trail[listing.trail.length - 1]?.name ?? 'My Drive', system: false },
    trail: listing.trail.map((step) => ({ id: driveNode(step.id), label: step.name })),
    space: null, can_create_folder: true, documents: null, searching: false,
    folders: listing.folders.map((f) => ({ node: driveNode(f.id), name: f.name, kind: 'driveFolder', documents: 0 })),
  }
}

/**
 * Choose a folder the way you do in a file explorer: open the company, a client or a case, open the folders inside it, and press
 * Choose here. A new folder can be made on the way. Only the company, a client, a case or a folder can be chosen; the levels above
 * them are for finding the way. `onPick` may answer with a message to show when the choice cannot be used (the dialog then stays open).
 */
export function FolderPicker({
  open,
  title,
  hint,
  confirmLabel = 'Choose this folder',
  startNode = 'root',
  canMakeFolders,
  source = 'orion',
  onPick,
  onClose,
}: {
  open: boolean
  title: string
  hint?: string
  confirmLabel?: string
  startNode?: string
  canMakeFolders: boolean
  /** Whose folders: Orion's own, or the connected Google Drive's. */
  source?: 'orion' | 'drive'
  onPick: (node: string, label: string) => Promise<string | void> | string | void
  onClose: () => void
}) {
  const [node, setNode] = useState(startNode)
  const [page, setPage] = useState<ExplorerPage | null>(null)
  const [filter, setFilter] = useState('')
  const [name, setName] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const go = useCallback((next: string) => {
    setNode(next)
    setFilter('')
    setName(null)
    setError('')
  }, [])

  useEffect(() => {
    if (open) go(startNode)
  }, [open, startNode, go])

  const [reload, setReload] = useState(0)
  useEffect(() => {
    if (!open) return
    let stale = false
    setPage(null)
    const looking = source === 'drive'
      ? api.driveBrowse(driveFolderOf(node.startsWith('gdrive') ? node : 'gdrive')).then(fromDrive)
      : api.documentBrowse(node, { foldersOnly: true })
    looking
      .then((found) => !stale && setPage(found))
      .catch((e: Error) => {
        if (stale) return
        setError(e.message)
        if (node !== (source === 'drive' ? 'gdrive' : 'root')) setNode(source === 'drive' ? 'gdrive' : 'root')
      })
    return () => {
      stale = true
    }
  }, [open, node, reload, source])

  const here = page?.trail.slice(source === 'drive' ? 0 : 1).map((step) => step.label).join(' › ') ?? ''
  const valid = page ? isDestination(page.node.kind) : false
  const entries = (page?.folders ?? []).filter((entry) => !filter.trim() || entry.name.toLowerCase().includes(filter.trim().toLowerCase()))

  const createFolder = async () => {
    if (!page || !name?.trim()) return
    try {
      if (source === 'drive') {
        const made = await api.driveNewFolder(driveFolderOf(page.node.id), name.trim())
        go(driveNode(made.id))
        setReload((n) => n + 1)
        return
      }
      if (!page.space) return
      const made = await api.createDocumentFolder(
        { scope: page.space.scope ?? 'company', case_code: page.space.case_code ?? undefined, client_code: page.space.client_code ?? undefined },
        name.trim(),
        page.space.folder_id,
      )
      go(`folder:${made.id}`)
      setReload((n) => n + 1)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const choose = async () => {
    if (!page || !valid) return
    setBusy(true)
    setError('')
    try {
      const problem = await onPick(page.node.id, here)
      if (typeof problem === 'string' && problem) setError(problem)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const up = page && page.trail.length > 1 ? page.trail[page.trail.length - 2].id : null

  return (
    <Modal
      open={open}
      title={title}
      size="xl"
      onClose={onClose}
      footer={
        <>
          <p className="mr-auto min-w-0 truncate text-sm text-[color:var(--color-text-muted)]" title={here}>
            {valid ? here : source === 'drive' ? 'Open a folder in Drive' : 'Open a folder, a case, a client or Company documents'}
          </p>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={choose} loading={busy} disabled={!valid}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {hint && <p className="mb-3 text-sm text-[color:var(--color-text-muted)]">{hint}</p>}
      {error && (
        <div className="mb-3">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}
      <div className="mb-3 flex items-center gap-1">
        <Button variant="ghost" size="sm" disabled={!up} onClick={() => up && go(up)} aria-label="Up one level" title="Up one level">
          <ArrowUp className="h-4 w-4" />
        </Button>
        <ol className="scroll-quiet flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto text-sm" aria-label="Where you are">
          {(page?.trail ?? [{ id: source === 'drive' ? 'gdrive' : 'root', label: source === 'drive' ? 'My Drive' : 'Documents' }]).map((step, index, all) => (
            <li key={step.id} className="flex shrink-0 items-center gap-0.5">
              {index > 0 && <ChevronRight className="h-3.5 w-3.5 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
              <button
                type="button"
                onClick={() => go(step.id)}
                aria-current={index === all.length - 1 ? 'location' : undefined}
                className={`rounded-md px-1.5 py-1 hover:bg-muted ${index === all.length - 1 ? 'font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)]'}`}
              >
                {step.label}
              </button>
            </li>
          ))}
        </ol>
        {canMakeFolders && page?.can_create_folder && name === null && (
          <Button variant="secondary" size="sm" onClick={() => setName('')}>
            <FolderPlus className="h-4 w-4" /> New folder
          </Button>
        )}
      </div>

      {name !== null && (
        <form
          className="mb-3 flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void createFolder()
          }}
        >
          <Input autoFocus value={name} maxLength={80} placeholder={`New folder in ${page?.node.label ?? ''}`} aria-label="New folder name" onChange={(event) => setName(event.target.value)} />
          <Button type="submit" disabled={!name.trim()}>
            Create
          </Button>
          <Button variant="secondary" onClick={() => setName(null)}>
            Cancel
          </Button>
        </form>
      )}

      {(page?.folders.length ?? 0) > 8 && (
        <Input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Find by name" aria-label="Find by name" className="mb-2" />
      )}

      <ul className="divide-y divide-[color:var(--color-border)] rounded-xl border border-[color:var(--color-border)]" aria-label="Folders here">
        {!page && <li className="px-4 py-6 text-sm text-[color:var(--color-text-muted)]">Loading…</li>}
        {page && entries.length === 0 && (
          <li className="px-4 py-6 text-sm text-[color:var(--color-text-muted)]">
            {filter ? 'Nothing is called that.' : 'No folders here yet.'}
            {valid ? ' You can choose this place, or make a folder in it.' : ''}
          </li>
        )}
        {entries.map((entry) => (
          <li key={entry.node}>
            <button
              type="button"
              onClick={() => go(entry.node)}
              className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-muted focus-visible:ring-2 focus-visible:ring-accent"
            >
              <EntryIcon kind={entry.kind} system={entry.system} className="h-5 w-5 shrink-0 text-accent" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-[color:var(--color-text)]">{entry.name}</span>
                {entry.sub && <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{entry.sub}</span>}
              </span>
              <span className="text-xs tabular-nums text-[color:var(--color-text-faint)]">{entry.documents}</span>
              <ChevronRight className="h-4 w-4 text-[color:var(--color-text-faint)]" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
