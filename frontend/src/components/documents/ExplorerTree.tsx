import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronRight, FileStack, Home, Trash2, X } from 'lucide-react'
import { api } from '../../api/client'
import type { ExplorerEntry } from '../../types'
import { DRAG_TYPE, DRIVE_DRAG_TYPE, EntryIcon, isDestination, type DragPayload } from './explorerUi'
import { driveFolderOf, driveNode, isDriveNode } from './driveNodes'

const DRIVE: ExplorerEntry = { node: 'gdrive', name: 'Google Drive', kind: 'drive', documents: 0 }

const TOP: ExplorerEntry[] = [
  { node: 'company', name: 'Company documents', kind: 'company', documents: 0 },
  { node: 'clients', name: 'Clients', kind: 'group', documents: 0 },
  { node: 'cases', name: 'Cases', kind: 'group', documents: 0 },
]

/**
 * The folders of the Document Center as a tree on the left, like the navigation pane of a file explorer: the company, then every client and
 * case, then the folders inside each. A branch is fetched when it is opened. The place being looked at is highlighted and its way
 * in is opened. A folder, case, client or the company takes what is dropped on it.
 */
export function ExplorerTree({
  current,
  trail,
  version,
  canWrite,
  drive,
  onOpen,
  onDropTo,
  onDropDrive,
}: {
  current: string
  trail: { id: string }[]
  /** Changes whenever something was made, moved or deleted, so the open branches are read again. */
  version: number
  canWrite: boolean
  /** Shown when this server can reach a Drive: whether it is connected (an unconnected Drive is a row that opens the connect screen). */
  drive: { connected: boolean } | null
  onOpen: (node: string) => void
  onDropTo: (node: string, payload: DragPayload) => void
  /** Files of Drive dropped on a place of the tree: copied into Orion, or (on a Drive folder) moved there. */
  onDropDrive: (node: string, fileIds: string[]) => void
}) {
  const [children, setChildren] = useState<Record<string, ExplorerEntry[]>>({})
  const [open, setOpen] = useState<Set<string>>(() => new Set(['root']))
  const [over, setOver] = useState('')
  const [failed, setFailed] = useState('')
  const asked = useRef(new Set<string>())

  const load = useCallback((node: string) => {
    asked.current.add(node)
    const reading = isDriveNode(node)
      ? api.driveBrowse(driveFolderOf(node)).then((listing) =>
          listing.folders.map<ExplorerEntry>((f) => ({ node: driveNode(f.id), name: f.name, kind: 'driveFolder', documents: 0 })),
        )
      : api.documentBrowse(node, { foldersOnly: true }).then((page) => page.folders)
    reading
      .then((folders) => {
        setChildren((all) => ({ ...all, [node]: folders }))
        setFailed('')
      })
      .catch((e: Error) => {
        if (node === 'root') {
          setFailed(e.message)
          return
        }
        // A branch that cannot be read any more (a folder that was deleted) is dropped from the tree, quietly: its parent no longer lists it.
        asked.current.delete(node)
        setOpen((now) => {
          const next = new Set(now)
          next.delete(node)
          return next
        })
        setChildren((all) => {
          const { [node]: _gone, ...rest } = all
          return rest
        })
      })
  }, [])

  useEffect(() => {
    if (!asked.current.has('root')) load('root')
  }, [load])

  // The branch the person is in is opened, down to where they are.
  useEffect(() => {
    const ways = trail.map((step) => step.id).filter((id) => id !== 'all' && id !== 'trash' && (!isDriveNode(id) || drive?.connected))
    setOpen((now) => {
      const next = new Set(now)
      for (const id of ways) next.add(id)
      return next
    })
    for (const id of ways) if (!asked.current.has(id)) load(id)
  }, [trail, load, drive?.connected])

  // Something changed: every branch that is open is read again, so counts and new folders show.
  const seen = useRef(version)
  useEffect(() => {
    if (seen.current === version) return
    seen.current = version
    for (const id of open) load(id)
  }, [version, open, load])

  const toggle = (node: string) => {
    setOpen((now) => {
      const next = new Set(now)
      if (next.has(node)) next.delete(node)
      else {
        next.add(node)
        if (!asked.current.has(node)) load(node)
      }
      return next
    })
  }

  const dropHere = (event: React.DragEvent, node: string) => {
    setOver('')
    const raw = event.dataTransfer.getData(DRAG_TYPE)
    const files = event.dataTransfer.getData(DRIVE_DRAG_TYPE)
    if ((!raw && !files) || !canWrite) return
    event.preventDefault()
    event.stopPropagation()
    if (raw) onDropTo(node, JSON.parse(raw) as DragPayload)
    else onDropDrive(node, JSON.parse(files) as string[])
  }

  const row = (entry: ExplorerEntry, depth: number) => {
    const expandable = entry.kind === 'folder' ? (entry.children ?? 0) > 0 : entry.kind === 'drive' ? Boolean(drive?.connected) : true
    const isOpen = open.has(entry.node)
    const active = current === entry.node
    const target = canWrite && isDestination(entry.kind)
    return (
      <li key={entry.node} role="none">
        <div
          role="treeitem"
          aria-expanded={expandable ? isOpen : undefined}
          aria-selected={active}
          onDragOver={(event) => {
            if (!target || !(event.dataTransfer.types.includes(DRAG_TYPE) || event.dataTransfer.types.includes(DRIVE_DRAG_TYPE))) return
            event.preventDefault()
            setOver(entry.node)
          }}
          onDragLeave={() => setOver((now) => (now === entry.node ? '' : now))}
          onDrop={(event) => target && dropHere(event, entry.node)}
          className={`group flex items-center rounded-lg text-sm transition-colors ${
            over === entry.node ? 'bg-accent-dim ring-2 ring-accent' : active ? 'bg-accent-dim font-semibold' : 'hover:bg-muted'
          }`}
          style={{ paddingLeft: `${depth * 0.9}rem` }}
        >
          <button
            type="button"
            tabIndex={-1}
            aria-label={isOpen ? `Close ${entry.name}` : `Open ${entry.name}`}
            onClick={() => toggle(entry.node)}
            className={`flex h-8 w-6 shrink-0 items-center justify-center text-[color:var(--color-text-faint)] ${expandable ? '' : 'invisible'}`}
          >
            <ChevronRight className={`h-3.5 w-3.5 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
          </button>
          <button
            type="button"
            onClick={() => onOpen(entry.node)}
            title={entry.name}
            className="flex min-w-0 flex-1 items-center gap-2 py-1.5 pr-2 text-left focus-visible:ring-2 focus-visible:ring-accent"
          >
            <EntryIcon kind={entry.kind} system={entry.system} className="h-4 w-4 shrink-0 text-accent" />
            <span className="min-w-0 flex-1 truncate text-[color:var(--color-text)]">{entry.name}</span>
            {entry.attention ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" title={`${entry.attention} need attention`} /> : null}
          </button>
        </div>
        {isOpen && children[entry.node] && children[entry.node].length > 0 && (
          <ul role="group" className="mt-px">
            {children[entry.node].map((child) => row(child, depth + 1))}
          </ul>
        )}
        {isOpen && children[entry.node]?.length === 0 && entry.kind !== 'folder' && (
          <p className="py-1 text-xs text-[color:var(--color-text-faint)]" style={{ paddingLeft: `${(depth + 1) * 0.9 + 1.6}rem` }}>
            Nothing here yet
          </p>
        )}
      </li>
    )
  }

  const quick = (node: string, label: string, icon: React.ReactNode) => (
    <button
      type="button"
      onClick={() => onOpen(node)}
      aria-current={current === node ? 'page' : undefined}
      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
        current === node ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]'
      }`}
    >
      <span className="text-accent">{icon}</span>
      {label}
    </button>
  )

  return (
    <nav aria-label="Folders" className="space-y-3">
      <div className="space-y-0.5">
        {quick('home', 'Overview', <Home className="h-4 w-4" />)}
        {quick('all', 'All documents', <FileStack className="h-4 w-4" />)}
      </div>
      <div>
        <p className="eyebrow mb-1 px-2.5">Folders</p>
        <ul role="tree" aria-label="Folders">
          <li role="none">
            <div
              role="treeitem"
              aria-selected={current === 'root'}
              className={`flex items-center rounded-lg text-sm ${current === 'root' ? 'bg-accent-dim font-semibold' : 'hover:bg-muted'}`}
            >
              <button
                type="button"
                tabIndex={-1}
                aria-label={open.has('root') ? 'Close Documents' : 'Open Documents'}
                onClick={() => toggle('root')}
                className="flex h-8 w-6 shrink-0 items-center justify-center text-[color:var(--color-text-faint)]"
              >
                <ChevronRight className={`h-3.5 w-3.5 transition-transform ${open.has('root') ? 'rotate-90' : ''}`} />
              </button>
              <button type="button" onClick={() => onOpen('root')} className="flex min-w-0 flex-1 items-center gap-2 py-1.5 pr-2 text-left focus-visible:ring-2 focus-visible:ring-accent">
                <EntryIcon kind="root" className="h-4 w-4 shrink-0 text-accent" />
                <span className="truncate text-[color:var(--color-text)]">Documents</span>
              </button>
            </div>
            {open.has('root') && <ul role="group">{[...(children.root ?? TOP), ...(drive ? [DRIVE] : [])].map((entry) => row(entry, 1))}</ul>}
          </li>
        </ul>
      </div>
      <div className="space-y-0.5">{quick('trash', 'Trash', <Trash2 className="h-4 w-4" />)}</div>
      {failed && (
        <p className="flex items-start gap-1.5 px-2.5 text-xs text-negative">
          <span className="min-w-0 flex-1">{failed}</span>
          <button type="button" onClick={() => setFailed('')} aria-label="Dismiss" className="shrink-0 rounded p-0.5 hover:bg-muted">
            <X className="h-3 w-3" />
          </button>
        </p>
      )}
    </nav>
  )
}
