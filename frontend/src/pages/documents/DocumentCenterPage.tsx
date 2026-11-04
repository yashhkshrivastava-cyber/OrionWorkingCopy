import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronRight,
  Download,
  FolderInput,
  FolderPlus,
  FolderTree,
  Info,
  LayoutGrid,
  List,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
  FolderUp,
  X,
} from 'lucide-react'
import { api } from '../../api/client'
import { AskAiButton } from '../../components/assistant/Launcher'
import { DocumentDrawer } from '../../components/documents/DocumentDrawer'
import { ExplorerList, payloadOf, rowKey, type Row, type SortKey } from '../../components/documents/ExplorerList'
import { ExplorerTree } from '../../components/documents/ExplorerTree'
import { ContextMenu, DRAG_TYPE, isDestination, type DragPayload, type MenuItem } from '../../components/documents/explorerUi'
import { FolderPicker } from '../../components/documents/FolderPicker'
import { DriveSection } from '../../components/documents/DriveSection'
import { driveFolderOf, isDriveNode } from '../../components/documents/driveNodes'
import { LumenCrumbs, LumenLanding, LumenSearch, QuickFilters, SelectionBar, TreeToggle } from '../../components/documents/lumenDocs'
import { Overview } from '../../components/documents/Overview'
import { type Space } from '../../components/documents/SpacePicker'
import { UploadModal } from '../../components/documents/UploadModal'
import { fromDrop, fromFileList, type Picked, type PickedFile } from '../../components/documents/uploadFolders'
import { Alert, Badge } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Input, Select } from '../../components/ui/Field'
import { saveBlob } from '../../components/ui/PdfPreview'
import { useToast } from '../../components/ui/Toast'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import { useLumen } from '../../lumen/useLumen'
import type { DocumentOptions, DocumentOverview, DocumentSummary, DriveStatus, ExplorerPage, FolderContents } from '../../types'
import { DropFolderDialog } from '../../components/documents/DropFolderDialog'

const PAGE = 100

const SORT_LABEL: Record<SortKey, string> = { title: 'Name', updated: 'Date changed', size: 'Size', expiry: 'Expiry date' }
const SORT_KEYS = Object.keys(SORT_LABEL) as SortKey[]

/** The address of the page before places were nodes: ?view=case&code=CS-1&folder=12. Old links and bookmarks still open the right place. */
function legacyNode(params: URLSearchParams): string | null {
  const view = params.get('view')
  if (!view) return null
  const folder = params.get('folder')
  if (folder && /^\d+$/.test(folder)) return `folder:${folder}`
  const code = params.get('code')
  if ((view === 'case' || view === 'client') && code) return `${view}:${code}`
  return ['home', 'all', 'trash', 'company'].includes(view) ? view : null
}

const flat = (node: string) => node === 'all' || node === 'trash'

/**
 * The Document Center, laid out like the file explorer on a computer: the folders as a tree on the left, the way you came in a bar at the top
 * (every step can be clicked, and it takes what you drop on it), and what is in the place you are in as a list or as icons. Documents and
 * folders are dragged to where they should go, a bill or an employee's paper that Orion filed is moved the same way and stays there. Where
 * you are, and how you are looking at it, are in the address, so a link opens the same place for a colleague.
 */
export function DocumentCenterPage() {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const lumen = useLumen()
  const navigate = useNavigate()
  const toast = useToast()
  const canWrite = Boolean(user?.can_documents_write)
  const isAdmin = user?.role === 'admin'
  const [params, setParams] = useSearchParams()

  const node = params.get('node') ?? legacyNode(params) ?? 'root'
  const q = params.get('q') ?? ''
  const category = params.get('category') ?? ''
  const status = params.get('status') ?? ''
  const expiry = params.get('expiry') ?? ''
  const tag = params.get('tag') ?? ''
  const layout = params.get('layout') === 'grid' ? 'grid' : 'list'
  const defaultSort: { key: SortKey; dir: 'asc' | 'desc' } = flat(node) ? { key: 'updated', dir: 'desc' } : { key: 'title', dir: 'asc' }
  const sortParam = params.get('sort') as SortKey | null
  const sort = {
    key: sortParam && SORT_KEYS.includes(sortParam) ? sortParam : defaultSort.key,
    dir: (params.get('dir') as 'asc' | 'desc' | null) ?? (sortParam ? 'asc' : defaultSort.dir),
  }
  const openId = Number(params.get('doc')) || null
  const filtered = Boolean(category || status || expiry || tag)
  const placesOnly = node === 'clients' || node === 'cases' // typing here finds a client or case by name, it does not search documents

  const update = useCallback(
    (patch: Record<string, string | undefined>, replace = false) =>
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          for (const key of ['view', 'code', 'folder']) next.delete(key) // the old address, now written as a node
          if (!next.get('node') && previous.get('node') === null) next.set('node', legacyNode(previous) ?? 'root')
          for (const [key, value] of Object.entries(patch)) {
            if (value) next.set(key, value)
            else next.delete(key)
          }
          return next
        },
        { replace },
      ),
    [setParams],
  )

  const go = useCallback(
    (next: string) => {
      setParams(
        (previous) => {
          const out = new URLSearchParams()
          out.set('node', next)
          const view = previous.get('layout')
          if (view) out.set('layout', view)
          const doc = previous.get('doc')
          if (doc) out.set('doc', doc)
          return out
        },
        { replace: false },
      )
    },
    [setParams],
  )

  const [options, setOptions] = useState<DocumentOptions | null>(null)
  const [overview, setOverview] = useState<DocumentOverview | null>(null)
  const [page, setPage] = useState<ExplorerPage | null>(null)
  const [items, setItems] = useState<DocumentSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [treeVersion, setTreeVersion] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState(q)
  const [showFilters, setShowFilters] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  // Lumen keeps the folder tree out of the way until it is asked for, and remembers the answer on this device.
  const [treeOpen, setTreeOpen] = useState(() => {
    try {
      return localStorage.getItem('orion-docs-tree') === '1'
    } catch {
      return false
    }
  })
  const toggleTree = () =>
    setTreeOpen((open) => {
      try {
        localStorage.setItem('orion-docs-tree', open ? '0' : '1')
      } catch {
        // the choice is only a convenience
      }
      return !open
    })
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState(false)
  const [menu, setMenu] = useState<{ x: number; y: number; row: Row | null } | null>(null)
  const [mover, setMover] = useState<DragPayload | null>(null)
  const [upload, setUpload] = useState<{ files: PickedFile[]; emptyFolders?: string[]; leftOut?: { hidden: number; tooMany: boolean }; category?: string; folderId?: number | null } | null>(null)
  const folderInput = useRef<HTMLInputElement>(null)

  /** Opens the upload dialog with what was dropped or chosen from the computer (folders read all the way down). */
  const startUpload = (picked: Picked, folderId: number | null) =>
    setUpload({ files: picked.files, emptyFolders: picked.emptyFolders, leftOut: { hidden: picked.hidden, tooMany: picked.tooMany }, folderId })
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const [filing, setFiling] = useState(false)
  const [driveStatus, setDriveStatus] = useState<DriveStatus | null>(null)
  const [driveTrail, setDriveTrail] = useState<{ id: string; label: string }[]>([])
  const [driveVersion, setDriveVersion] = useState(0)
  const [toDrive, setToDrive] = useState<{ payload: DragPayload; move: boolean } | null>(null)
  const [checklist, setChecklist] = useState<{ category: string; count: number; present: boolean }[]>([])

  const isDrive = isDriveNode(node)
  const landing = node === 'home' || node === 'root'
  // Lumen's front door stands in for both the Overview and the top level; a search shows its results instead.
  const showLanding = lumen && landing && !search
  const browseNode = node === 'home' ? 'root' : node

  const refresh = useCallback(() => {
    setReload((n) => n + 1)
    setTreeVersion((n) => n + 1)
  }, [])

  const loadDrive = useCallback(() => {
    api.driveStatus().then(setDriveStatus).catch(() => setDriveStatus(null))
  }, [])
  useEffect(loadDrive, [loadDrive])

  useEffect(() => {
    api.documentOptions().then(setOptions).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (node !== 'home' && !(lumen && node === 'root')) return
    api.documentOverview().then(setOverview).catch((e: Error) => setError(e.message))
  }, [node, lumen, reload, generation])

  // The papers every case should have, shown at the top of the case itself.
  const caseCode = node.startsWith('case:') ? node.slice(5) : ''
  useEffect(() => {
    if (!caseCode) {
      setChecklist([])
      return
    }
    api
      .caseChecklist(caseCode)
      .then((r) => setChecklist(r.checklist))
      .catch(() => setChecklist([]))
  }, [caseCode, reload, generation])

  // The search box keeps what is typed; the address follows a moment later.
  useEffect(() => setSearch(q), [q])
  useEffect(() => {
    if (search === q) return
    const timer = window.setTimeout(() => update({ q: search || undefined }, true), 300)
    return () => window.clearTimeout(timer)
  }, [search, q, update])

  const sortKey = `${sort.key}:${sort.dir}`
  const serverQ = placesOnly ? '' : q
  const browseKey = JSON.stringify([node, serverQ, category, status, expiry, tag, sortKey])

  useEffect(() => {
    if ((node === 'home' && !lumen) || isDrive) return
    let stale = false
    setLoading(true)
    api
      .documentBrowse(browseNode, { q: serverQ, category, status, expiry, tag, sort: sort.key, direction: sort.dir, limit: PAGE })
      .then((found) => {
        if (stale) return
        setPage(found)
        setItems(found.documents?.items ?? [])
        setTotal(found.documents?.total ?? 0)
        setError('')
      })
      .catch((e: Error) => {
        if (stale) return
        setError(e.message)
        if (node !== 'root') go('root') // a place that is gone (a folder that was deleted) leaves you at the top, not on an error
      })
      .finally(() => !stale && setLoading(false))
    return () => {
      stale = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browseKey, reload, generation])

  useEffect(() => setSelected(new Set()), [browseKey])

  const loadMore = () => {
    setLoading(true)
    api
      .documentBrowse(browseNode, { q: serverQ, category, status, expiry, tag, sort: sort.key, direction: sort.dir, limit: PAGE, offset: items.length })
      .then((found) => {
        const more = found.documents?.items ?? []
        setItems((current) => [...current, ...more.filter((item) => !current.some((c) => c.id === item.id))])
        setTotal(found.documents?.total ?? 0)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  // --- what is shown ------------------------------------------------------------------------------------------------------
  const searching = Boolean(page?.searching)
  const rows: Row[] = useMemo(() => {
    const text = placesOnly ? q.trim().toLowerCase() : ''
    const folders = (searching ? [] : (page?.folders ?? []))
      .filter((entry) => !text || entry.name.toLowerCase().includes(text))
      .sort((a, b) => (sort.key === 'title' && sort.dir === 'desc' ? b.name.localeCompare(a.name) : 0))
      .map<Row>((entry) => ({ key: rowKey.folder(entry.node), type: 'folder', entry }))
    return [...folders, ...items.map<Row>((doc) => ({ key: rowKey.doc(doc.id), type: 'doc', doc }))]
  }, [page, items, searching, placesOnly, q, sort.key, sort.dir])

  const chosen = rows.filter((row) => selected.has(row.key))
  const chosenDocs = chosen.filter((row): row is Extract<Row, { type: 'doc' }> => row.type === 'doc')
  const chosenFolders = chosen.filter((row): row is Extract<Row, { type: 'folder' }> => row.type === 'folder')
  const inTrash = node === 'trash'
  const canMake = canWrite && Boolean(page?.can_create_folder) && !inTrash
  const parent = page && page.trail.length > 1 ? page.trail[page.trail.length - 2].id : node === 'home' || flat(node) ? 'root' : null
  const here = page?.node.label ?? ''

  const space: Space | null = useMemo(() => {
    const s = page?.space
    if (!s || !s.scope) return null
    return { scope: s.scope, case_code: s.case_code ?? undefined, client_code: s.client_code ?? undefined, label: here }
  }, [page, here])

  // --- doing things -------------------------------------------------------------------------------------------------------
  const fail = (e: unknown) => setError((e as Error).message)

  const open = (row: Row) => {
    if (row.type === 'folder') go(row.entry.node)
    else update({ doc: String(row.doc.id) })
  }

  /** Copy (or move) documents of Orion to a Drive folder. Confidential ones, and employees' papers, are only sent when the person confirms it. */
  const sendToDrive = async (payload: DragPayload, folderId: string, move: boolean, label: string) => {
    if (payload.folder_ids.length) {
      setError('A folder cannot be sent to Drive as one yet. Open it and choose its documents.')
      return
    }
    const touchy = items.filter((doc) => payload.ids.includes(doc.id) && (doc.confidentiality === 'Confidential' || doc.source?.type === 'employee_document'))
    let allow = false
    if (touchy.length) {
      allow = window.confirm(
        `${touchy.length === 1 ? `"${touchy[0].title}" is` : `${touchy.length} of these documents are`} Confidential or a personal paper of an employee. Send ${touchy.length === 1 ? 'it' : 'them'} to Google Drive?`,
      )
      if (!allow) return
    }
    try {
      const r = await api.driveCopyTo(payload.ids, folderId, move, allow)
      if (r.failed.length) setError(`${r.failed.length === 1 ? 'One document was' : `${r.failed.length} documents were`} not sent: ${r.failed.slice(0, 3).map((f) => `${f.name} (${f.message})`).join('; ')}`)
      if (r.done) toast.show(`${move ? 'Moved' : 'Copied'} ${r.done} ${r.done === 1 ? 'document' : 'documents'} to ${label || r.to}.`)
      setSelected(new Set())
      setDriveVersion((n) => n + 1)
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  /** Files of Drive dropped on the tree: into Orion's folder, or (on a Drive folder) to that folder in Drive. */
  const dropDrive = async (to: string, fileIds: string[]) => {
    try {
      if (isDriveNode(to)) {
        for (const id of fileIds) if (id !== driveFolderOf(to)) await api.driveMove(id, driveFolderOf(to))
        toast.show('Moved.')
      } else {
        const r = await api.driveCopyFrom(fileIds, to, false)
        if (r.failed.length) setError(`${r.failed.length} not copied: ${r.failed.slice(0, 3).map((f) => `${f.name} (${f.message})`).join('; ')}`)
        if (r.done) toast.show(`Copied ${r.done} ${r.done === 1 ? 'file' : 'files'} to ${r.to}.`)
      }
      setDriveVersion((n) => n + 1)
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  const moveTo = async (payload: DragPayload, to: string, label?: string) => {
    if (!payload.ids.length && !payload.folder_ids.length) return
    if (isDriveNode(to)) {
      await sendToDrive(payload, driveFolderOf(to), false, label ?? 'Google Drive')
      return
    }
    try {
      const r = await api.moveDocuments(payload, to)
      const count = r.moved + r.folders
      toast.show(count ? `Moved ${count} ${count === 1 ? 'item' : 'items'} to ${label ?? r.to}.` : 'Nothing needed moving.')
      setSelected(new Set())
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  const createFolder = async (name: string) => {
    setDraft(false)
    if (!page?.space?.scope) return
    try {
      const made = await api.createDocumentFolder(
        { scope: page.space.scope, case_code: page.space.case_code ?? undefined, client_code: page.space.client_code ?? undefined },
        name.trim(),
        page.space.folder_id,
      )
      refresh()
      setSelected(new Set([rowKey.folder(`folder:${made.id}`)]))
    } catch (e) {
      fail(e)
    }
  }

  const rename = async (row: Row, name: string) => {
    if (renaming !== row.key) return
    setRenaming(null)
    const next = name.trim()
    if (!next) return
    try {
      if (row.type === 'folder') await api.renameDocumentFolder(Number(row.entry.node.split(':')[1]), next)
      else await api.updateDocument(row.doc.id, { title: next })
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  const startRename = (row: Row | undefined) => {
    if (!row || !canWrite || inTrash) return
    if (row.type === 'folder' && (row.entry.kind !== 'folder' || row.entry.system)) {
      setError(row.entry.kind === 'folder' ? 'This folder is kept by Orion, which names it after what is filed in it, so it cannot be renamed.' : 'Clients and cases are renamed where they are kept.')
      return
    }
    setRenaming(row.key)
  }

  const [dropping, setDropping] = useState<{ items: FolderContents[]; ids: number[]; folderIds: number[] } | null>(null)

  const remove = async () => {
    const ids = chosenDocs.map((row) => row.doc.id)
    const folderIds = chosenFolders.filter((row) => row.entry.kind === 'folder').map((row) => Number(row.entry.node.split(':')[1]))
    if (!ids.length && !folderIds.length) return
    // A folder with things in it is not deleted by a bare "are you sure": what it holds is looked up and shown first.
    const looked = await Promise.all(folderIds.map((id) => api.documentFolderContents(id).catch(() => null)))
    const full = looked.filter((info): info is FolderContents => Boolean(info) && (info!.documents > 0 || info!.subfolders > 0 || info!.filed > 0 || !info!.can_drop))
    if (full.length) {
      setDropping({ items: full, ids, folderIds })
      return
    }
    const what = [ids.length ? `${ids.length} ${ids.length === 1 ? 'document' : 'documents'} (they go to the trash)` : '', folderIds.length ? `${folderIds.length} empty ${folderIds.length === 1 ? 'folder' : 'folders'}` : ''].filter(Boolean).join(' and ')
    if (!window.confirm(`Delete ${what}?`)) return
    await carryOutDelete(ids, folderIds, [])
  }

  /** Does the deleting once it has been agreed to: the selected documents to the trash, empty folders deleted, and the folders that were shown dropped with what is in them. */
  const carryOutDelete = async (ids: number[], folderIds: number[], dropped: FolderContents[]) => {
    const problems: string[] = []
    try {
      if (ids.length) await api.bulkDocuments(ids, 'delete')
    } catch (e) {
      problems.push((e as Error).message)
    }
    const droppedIds = new Set(dropped.map((info) => info.folder_id))
    for (const info of dropped) {
      try {
        await api.dropDocumentFolder(info.folder_id, { seen_documents: info.documents, seen_subfolders: info.subfolders })
      } catch (e) {
        problems.push((e as Error).message)
      }
    }
    for (const id of folderIds.filter((folder) => !droppedIds.has(folder))) {
      try {
        await api.deleteDocumentFolder(id)
      } catch (e) {
        problems.push((e as Error).message)
      }
    }
    setSelected(new Set())
    if (problems.length) setError(problems[0])
    else toast.show('Deleted.')
    refresh()
  }

  const restore = async () => {
    try {
      const r = await api.bulkDocuments(chosenDocs.map((row) => row.doc.id), 'restore')
      toast.show(`${r.changed} restored.`)
      setSelected(new Set())
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  const setStatus = async (value: string) => {
    try {
      const r = await api.bulkDocuments(chosenDocs.map((row) => row.doc.id), 'status', { status: value })
      toast.show(`${r.changed} updated.`)
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  const download = async (row: Row | undefined) => {
    if (!row || row.type !== 'doc') return
    try {
      saveBlob(await api.documentFile(row.doc.id), row.doc.file_name)
    } catch (e) {
      fail(e)
    }
  }

  const updateFiling = async () => {
    setFiling(true)
    try {
      const r = await api.updateDocumentFiling()
      const changed = r.filed + r.updated + r.retired
      toast.show(`${changed ? `${r.filed} filed, ${r.updated} updated, ${r.retired} removed.` : 'Everything is already filed.'}${r.failed ? ` ${r.failed} could not be filed; see the System page.` : ''}`)
      refresh()
    } catch (e) {
      fail(e)
    } finally {
      setFiling(false)
    }
  }

  const sortBy = (key: SortKey) =>
    update({ sort: key, dir: sort.key === key ? (sort.dir === 'asc' ? 'desc' : 'asc') : key === 'updated' || key === 'size' ? 'desc' : 'asc' }, true)

  const dropOnFolderRow = (row: Row, payload: DragPayload) => {
    if (row.type === 'folder') void moveTo(payload, row.entry.node, row.entry.name)
  }

  const filesOnFolderRow = (row: Row, transfer: DataTransfer) => {
    if (row.type !== 'folder' || !isDestination(row.entry.kind)) return
    const id = row.entry.kind === 'folder' ? Number(row.entry.node.split(':')[1]) : null
    void fromDrop(transfer).then((picked) => startUpload(picked, id)) // the dropped items are read at once, inside fromDrop
  }

  const menuItems = (row: Row | null): MenuItem[] => {
    const many = chosen.length > 1
    if (!row) {
      return [
        ...(canMake ? [{ label: 'New folder', icon: <FolderPlus className="h-4 w-4" />, onClick: () => setDraft(true) }] : []),
        ...(canWrite && !inTrash && options ? [{ label: 'Upload files…', icon: <Upload className="h-4 w-4" />, onClick: () => setUpload({ files: [] }) }] : []),
        ...(canWrite && !inTrash && options ? [{ label: 'Upload folder…', icon: <FolderUp className="h-4 w-4" />, onClick: () => folderInput.current?.click() }] : []),
        ...(lumen && canWrite && options ? [{ label: 'Update filing', icon: <RefreshCw className="h-4 w-4" />, onClick: () => void updateFiling() }] : []),
        { label: layout === 'grid' ? 'View as list' : 'View as icons', icon: layout === 'grid' ? <List className="h-4 w-4" /> : <LayoutGrid className="h-4 w-4" />, divider: true, onClick: () => update({ layout: layout === 'grid' ? undefined : 'grid' }, true) },
        { label: 'Refresh', icon: <RefreshCw className="h-4 w-4" />, onClick: refresh },
      ]
    }
    const system = row.type === 'folder' && (row.entry.kind !== 'folder' || row.entry.system)
    const own = chosen.length ? chosen : [row]
    const movable = canWrite && !inTrash && own.every((r) => !(r.type === 'folder' && (r.entry.kind !== 'folder' || r.entry.system)))
    return [
      { label: 'Open', onClick: () => open(row) },
      ...(row.type === 'doc' ? [{ label: 'Details and versions', icon: <Info className="h-4 w-4" />, onClick: () => update({ doc: String(row.doc.id) }) }] : []),
      ...(row.type === 'doc' && !many ? [{ label: 'Download', icon: <Download className="h-4 w-4" />, onClick: () => void download(row) }] : []),
      ...(inTrash
        ? [{ label: 'Restore', icon: <RotateCcw className="h-4 w-4" />, disabled: !canWrite, divider: true, onClick: () => void restore() }]
        : [
            { label: 'Rename', icon: <Pencil className="h-4 w-4" />, disabled: !canWrite || many || system, divider: true, onClick: () => startRename(row) },
            { label: 'Move to…', icon: <FolderInput className="h-4 w-4" />, disabled: !movable, onClick: () => setMover(payloadOf(rows, new Set(own.map((r) => r.key)))) },
            ...(driveStatus?.connected && canWrite && own.every((r) => r.type === 'doc')
              ? [
                  { label: 'Copy to Google Drive…', icon: <Upload className="h-4 w-4" />, divider: true, onClick: () => setToDrive({ payload: payloadOf(rows, new Set(own.map((r) => r.key))), move: false }) },
                  { label: 'Move to Google Drive…', icon: <Upload className="h-4 w-4" />, disabled: own.some((r) => r.type === 'doc' && r.doc.source), onClick: () => setToDrive({ payload: payloadOf(rows, new Set(own.map((r) => r.key))), move: true }) },
                ]
              : []),
            { label: many ? `Delete ${own.length} items` : 'Delete', icon: <Trash2 className="h-4 w-4" />, danger: true, disabled: !canWrite || (row.type === 'folder' && system), onClick: () => void remove() },
          ]),
    ]
  }

  const onAction = (action: 'up' | 'delete' | 'rename' | 'back') => {
    if (action === 'up') {
      if (parent) go(parent)
    } else if (action === 'back') navigate(-1)
    else if (action === 'rename') startRename(chosen.length === 1 ? chosen[0] : undefined)
    else if (canWrite && !inTrash && chosen.length) void remove()
  }

  // --- drag and drop of files from the computer ---------------------------------------------------------------------------
  const filesDragged = (event: React.DragEvent) => canWrite && !inTrash && event.dataTransfer.types.includes('Files')

  const title = node === 'home' ? 'Overview' : (page?.node.label ?? 'Documents')
  const subtitle = (() => {
    if (node === 'home') return 'What needs attention, and what changed lately.'
    if (!page) return ''
    if (inTrash) return 'Deleted documents are kept here. Restore one, or (admins) delete it for good from its details.'
    const folders = searching ? 0 : page.folders.length
    const parts = [folders ? `${folders} ${folders === 1 ? 'folder' : 'folders'}` : '', page.documents ? `${total} ${total === 1 ? 'document' : 'documents'}` : ''].filter(Boolean)
    return searching ? `${total} ${total === 1 ? 'match' : 'matches'} in ${here}` : parts.join(' · ')
  })()

  const selectionTools = (
    <>
                    {chosenDocs.length === 1 && chosen.length === 1 && (
                      <>
                        <Button variant="secondary" size="sm" onClick={() => update({ doc: String(chosenDocs[0].doc.id) })}>
                          <Info className="h-4 w-4" /> Details
                        </Button>
                        <Button variant="secondary" size="sm" onClick={() => void download(chosenDocs[0])}>
                          <Download className="h-4 w-4" /> Download
                        </Button>
                      </>
                    )}
                    {canWrite && inTrash && (
                      <Button size="sm" onClick={() => void restore()}>
                        <RotateCcw className="h-4 w-4" /> Restore
                      </Button>
                    )}
                    {canWrite && !inTrash && (
                      <>
                        <Button variant="secondary" size="sm" onClick={() => setMover(payloadOf(rows, selected))} disabled={chosenFolders.some((r) => r.entry.kind !== 'folder' || r.entry.system)}>
                          <FolderInput className="h-4 w-4" /> Move to…
                        </Button>
                        {driveStatus?.connected && chosenDocs.length > 0 && chosenFolders.length === 0 && (
                          <Button variant="secondary" size="sm" onClick={() => setToDrive({ payload: payloadOf(rows, selected), move: false })}>
                            <Upload className="h-4 w-4" /> Copy to Drive…
                          </Button>
                        )}
                        {chosen.length === 1 && (
                          <Button variant="secondary" size="sm" onClick={() => startRename(chosen[0])}>
                            <Pencil className="h-4 w-4" /> Rename
                          </Button>
                        )}
                        {chosenDocs.length > 0 && (
                          <Select aria-label="Set status" value="" className="!w-auto" onChange={(e) => e.target.value && void setStatus(e.target.value)}>
                            <option value="">Set status…</option>
                            {(options?.statuses ?? []).map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </Select>
                        )}
                        <Button variant="secondary" size="sm" onClick={() => void remove()} disabled={chosenFolders.some((r) => r.entry.kind !== 'folder' || r.entry.system)}>
                          <Trash2 className="h-4 w-4" /> Delete
                        </Button>
                      </>
                    )}
    </>
  )

  const moreButton = (
    <button
      type="button"
      aria-label="More"
      title="More"
      onClick={(event) => {
        const at = event.currentTarget.getBoundingClientRect()
        setMenu({ x: at.right - 8, y: at.bottom + 4, row: null })
      }}
      className="interactive grid h-10 w-10 place-items-center rounded-full border border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted"
    >
      <MoreHorizontal className="h-4 w-4" />
    </button>
  )

  const crumbs = node === 'home' ? [{ id: 'home', label: 'Overview' }] : (page?.trail ?? [{ id: 'root', label: 'Documents' }])

  return (
    <div
      className="mx-auto w-full max-w-[1600px]"
      onDragEnter={(e) => {
        if (!filesDragged(e)) return
        dragDepth.current += 1
        setDragging(true)
      }}
      onDragLeave={(e) => {
        if (!filesDragged(e)) return
        dragDepth.current = Math.max(0, dragDepth.current - 1)
        if (dragDepth.current === 0) setDragging(false)
      }}
      onDragOver={(e) => filesDragged(e) && e.preventDefault()}
      onDrop={(e) => {
        dragDepth.current = 0
        setDragging(false)
        if (!filesDragged(e) || !e.dataTransfer.files.length) return
        e.preventDefault()
        const into = page?.space?.folder_id ?? null
        void fromDrop(e.dataTransfer).then((picked) => startUpload(picked, into)) // folders are read all the way down
      }}
    >
      {dragging && (
        <div className="pointer-events-none fixed inset-0 z-[70] flex items-center justify-center bg-accent-dim/70 backdrop-blur-[2px]">
          <p className="rounded-2xl border-2 border-dashed border-accent bg-surface px-8 py-6 text-lg font-semibold text-[color:var(--color-text)]">
            Drop to upload{space ? ` to ${space.label}` : ''}
          </p>
        </div>
      )}

      <div className={`grid gap-4 ${!lumen || treeOpen ? 'lg:grid-cols-[16rem_minmax(0,1fr)]' : ''}`}>
        {(!lumen || treeOpen) && (
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <button
            type="button"
            onClick={() => setNavOpen((o) => !o)}
            className={`panel flex w-full items-center gap-2 px-3 py-2.5 text-sm font-medium text-[color:var(--color-text)] ${lumen ? 'hidden' : 'lg:hidden'}`}
            aria-expanded={navOpen}
          >
            <FolderTree className="h-4 w-4 text-accent" /> Folders
            <ChevronRight className={`ml-auto h-4 w-4 transition-transform ${navOpen ? 'rotate-90' : ''}`} />
          </button>
          <div className={`panel scroll-quiet mt-2 max-h-[calc(100dvh-7rem)] overflow-y-auto p-2 lg:mt-0 lg:block ${navOpen || lumen ? 'block' : 'hidden'}`}>
            <ExplorerTree
              current={node}
              trail={isDrive ? driveTrail : (page?.trail ?? [])}
              version={treeVersion + driveVersion}
              canWrite={canWrite}
              drive={driveStatus && driveStatus.mode !== 'off' ? { connected: driveStatus.connected } : null}
              onOpen={(next) => {
                setNavOpen(false)
                go(next)
              }}
              onDropTo={(to, payload) => void moveTo(payload, to)}
              onDropDrive={(to, ids) => void dropDrive(to, ids)}
            />
          </div>
        </aside>
        )}

        <main className="min-w-0 space-y-3">
          {isDrive ? (
            <>
              {lumen && (
                <LumenCrumbs
                  crumbs={[{ id: 'root', label: 'Documents' }, { id: 'gdrive', label: 'Google Drive' }]}
                  canDrop={() => false}
                  canUp
                  onGo={go}
                  onBack={() => navigate(-1)}
                  onUp={() => go('root')}
                  onDropItems={() => undefined}
                  treeButton={<TreeToggle open={treeOpen} onToggle={toggleTree} />}
                />
              )}
            <DriveSection
              node={node}
              status={driveStatus}
              canWrite={canWrite}
              isAdmin={isAdmin}
              version={driveVersion}
              go={go}
              onTrail={setDriveTrail}
              onStatus={() => {
                loadDrive()
                setDriveVersion((n) => n + 1)
              }}
              onChanged={() => {
                setDriveVersion((n) => n + 1)
                refresh()
              }}
              onDropOrion={(payload, folderId, label) => void sendToDrive(payload, folderId, false, label)}
            />
            </>
          ) : (
            <>
          {lumen ? (
            showLanding ? (
              <div className="flex flex-wrap items-center justify-end gap-2">
                <AskAiButton variant="secondary" prompt="Which documents have expired or are about to, and what do they belong to?">
                  Ask AI
                </AskAiButton>
                {moreButton}
              </div>
            ) : (
              <header className="flex flex-wrap items-end justify-between gap-3">
                <div className="min-w-0">
                  <p className="eyebrow mb-1">Documents</p>
                  <h1 className="t-h1 truncate text-[color:var(--color-text)]">{title}</h1>
                  <p className="mt-0.5 text-sm text-[color:var(--color-text-muted)]">{subtitle}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <AskAiButton variant="secondary" prompt="Which documents have expired or are about to, and what do they belong to?">
                    Ask AI
                  </AskAiButton>
                  {canMake && (
                    <Button variant="secondary" onClick={() => setDraft(true)} disabled={draft}>
                      <FolderPlus className="h-4 w-4" /> New folder
                    </Button>
                  )}
                  {canWrite && !inTrash && options && (
                    <>
                      <Button variant="secondary" onClick={() => folderInput.current?.click()}>
                        <FolderUp className="h-4 w-4" /> Upload folder
                      </Button>
                      <Button onClick={() => setUpload({ files: [], folderId: page?.space?.folder_id ?? null })}>
                        <Upload className="h-4 w-4" /> Add documents
                      </Button>
                    </>
                  )}
                  {moreButton}
                </div>
              </header>
            )
          ) : (
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <p className="eyebrow mb-1">Documents</p>
              <h1 className="truncate t-h1 text-[color:var(--color-text)]">{title}</h1>
              <p className="mt-0.5 text-sm text-[color:var(--color-text-muted)]">{subtitle}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <AskAiButton variant="secondary" prompt="Which documents have expired or are about to, and what do they belong to?">
                Ask AI
              </AskAiButton>
              {canWrite && options && (
                <Button variant="secondary" loading={filing} onClick={updateFiling} title="File the bills, employee papers and EMD papers that are not here yet, and bring the filed ones up to date">
                  <RefreshCw className="h-4 w-4" /> Update filing
                </Button>
              )}
            </div>
          </header>
          )}

          {error && (
            <Alert variant="error" onDismiss={() => setError('')}>
              {error}
            </Alert>
          )}

          {lumen ? (
            !showLanding && (
              <div className="space-y-3">
                <LumenCrumbs
                  crumbs={node === 'home' ? [{ id: 'root', label: 'Documents' }] : crumbs}
                  canDrop={(id) => canWrite && (id === 'company' || /^(client|case|folder):/.test(id))}
                  canUp={Boolean(parent)}
                  onGo={go}
                  onBack={() => navigate(-1)}
                  onUp={() => parent && go(parent)}
                  onDropItems={(payload, id, label) => void moveTo(payload, id, label)}
                  treeButton={<TreeToggle open={treeOpen} onToggle={toggleTree} />}
                />
                <LumenSearch
                  value={search}
                  onChange={setSearch}
                  focusOnMount={Boolean(search)}
                  placeholder={placesOnly ? `Find a ${node === 'clients' ? 'client' : 'case'}` : `Search ${flat(node) || node === 'root' || node === 'home' ? 'all documents' : here}`}
                />
              </div>
            )
          ) : (
            <>
          {/* The address bar: back, forward, up, where you are (each step opens it and takes a drop), and a search. */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center">
              <Button variant="ghost" size="sm" onClick={() => navigate(-1)} aria-label="Back" title="Back (Alt+←)">
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => navigate(1)} aria-label="Forward" title="Forward">
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="sm" disabled={!parent} onClick={() => parent && go(parent)} aria-label="Up one level" title="Up one level (Backspace)">
                <ArrowUp className="h-4 w-4" />
              </Button>
            </div>
            <ol className="panel scroll-quiet flex min-w-[15rem] flex-1 items-center gap-0.5 overflow-x-auto px-2 py-1 text-sm" aria-label="Where you are">
              {crumbs.map((step, index) => {
                const last = index === crumbs.length - 1
                const target = canWrite && (step.id === 'company' || /^(client|case|folder):/.test(step.id))
                return (
                  <li key={step.id} className="flex shrink-0 items-center gap-0.5">
                    {index > 0 && <ChevronRight className="h-3.5 w-3.5 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
                    <button
                      type="button"
                      onClick={() => go(step.id)}
                      aria-current={last ? 'location' : undefined}
                      onDragOver={(e) => target && e.dataTransfer.types.includes(DRAG_TYPE) && e.preventDefault()}
                      onDrop={(e) => {
                        const raw = e.dataTransfer.getData(DRAG_TYPE)
                        if (!target || !raw) return
                        e.preventDefault()
                        void moveTo(JSON.parse(raw) as DragPayload, step.id, step.label)
                      }}
                      className={`rounded-md px-1.5 py-1 transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-accent ${last ? 'font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)]'}`}
                    >
                      {step.label}
                    </button>
                  </li>
                )
              })}
            </ol>
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={node === 'home' ? 'Search all documents' : placesOnly ? `Find a ${node === 'clients' ? 'client' : 'case'}` : `Search ${flat(node) || node === 'root' ? 'all documents' : here}`}
                aria-label="Search"
                className="pl-9"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && node === 'home' && search) go('all')
                }}
              />
            </div>
          </div>
            </>
          )}

          {showLanding ? (
            <LumenLanding
              overview={overview}
              places={page?.folders ?? []}
              driveOn={Boolean(driveStatus && driveStatus.mode !== 'off')}
              canWrite={canWrite && Boolean(options)}
              search={search}
              onSearch={setSearch}
              onSubmitSearch={() => update({ q: search || undefined }, true)}
              onUpload={() => setUpload({ files: [] })}
              onUploadFolder={() => folderInput.current?.click()}
              onGo={go}
              onOpen={(id) => update({ doc: String(id) })}
              onFilter={(f) => setParams({ node: 'all', ...(Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as Record<string, string>) })}
            />
          ) : node === 'home' && !lumen ? (
            overview ? (
              <Overview
                data={overview}
                onOpen={(id) => update({ doc: String(id) })}
                onFilter={(f) => setParams({ node: 'all', ...(Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as Record<string, string>) })}
              />
            ) : (
              <p className="text-sm text-[color:var(--color-text-muted)]">Loading…</p>
            )
          ) : (
            <>
              {caseCode && checklist.length > 0 && (
                <section className="panel p-3" aria-label="Papers every case should have">
                  <p className="eyebrow mb-2">Papers on file for this case</p>
                  <div className="flex flex-wrap gap-2">
                    {checklist.map((item) => (
                      <button
                        key={item.category}
                        type="button"
                        disabled={item.present || !canWrite}
                        onClick={() => setUpload({ files: [], category: item.category })}
                        title={item.present ? `${item.count} on file` : canWrite ? 'Missing. Click to upload it.' : 'Missing'}
                        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                          item.present ? 'border-positive/30 bg-positive-dim text-positive' : 'border-warning/40 bg-warning-dim text-warning enabled:hover:brightness-95'
                        }`}
                      >
                        {item.present ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
                        {item.category}
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {/* The actions: what can be done here, and what can be done to what is selected. */}
              <div className="flex min-h-[2.75rem] items-center gap-2">
                <div className="scroll-quiet flex min-w-0 flex-1 items-center gap-2 overflow-x-auto py-1">
                {lumen ? (
                  page?.documents && !inTrash ? (
                    <QuickFilters
                      state={{ expiry, status }}
                      onPick={(patch) => update({ expiry: patch.expiry, status: patch.status })}
                      moreOpen={showFilters}
                      moreActive={Boolean(category || tag)}
                      onMore={() => setShowFilters((v) => !v)}
                    />
                  ) : null
                ) : chosen.length === 0 ? (
                  <>
                    {canMake && (
                      <Button variant="secondary" size="sm" onClick={() => setDraft(true)} disabled={draft} aria-label="New folder">
                        <FolderPlus className="h-4 w-4" /> <span className="hidden sm:inline">New folder</span>
                      </Button>
                    )}
                    {canWrite && !inTrash && options && (
                      <>
                        <Button variant="secondary" size="sm" onClick={() => folderInput.current?.click()} aria-label="Upload a folder">
                          <FolderUp className="h-4 w-4" /> <span className="hidden sm:inline">Upload folder</span>
                        </Button>
                        <Button size="sm" onClick={() => setUpload({ files: [], folderId: page?.space?.folder_id ?? null })}>
                          <Upload className="h-4 w-4" /> Upload
                        </Button>
                      </>
                    )}
                  </>
                ) : (
                  <div className="flex items-center gap-2" role="region" aria-label="Selected items">
                    <span className="shrink-0 whitespace-nowrap rounded-full bg-accent-dim px-2.5 py-1 text-xs font-semibold text-[color:var(--color-text)]">{chosen.length} selected</span>
                    {selectionTools}
                    <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())} aria-label="Clear the selection">
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {!lumen && page?.documents && (
                    <Button variant={showFilters || filtered ? 'secondary' : 'ghost'} size="sm" onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>
                      <SlidersHorizontal className="h-4 w-4" /> <span className="hidden xl:inline">Filters{filtered ? ' on' : ''}</span>
                    </Button>
                  )}
                  <Select aria-label="Sort by" value={sort.key} onChange={(e) => sortBy(e.target.value as SortKey)} className={`!w-auto ${layout === 'grid' ? '' : 'hidden xl:block'}`}>
                    {SORT_KEYS.map((key) => (
                      <option key={key} value={key}>
                        {SORT_LABEL[key]}
                      </option>
                    ))}
                  </Select>
                  <div className="flex overflow-hidden rounded-lg border border-[color:var(--color-border-strong)]" role="group" aria-label="View">
                    {(['list', 'grid'] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        aria-pressed={layout === mode}
                        aria-label={mode === 'list' ? 'List' : 'Icons'}
                        title={mode === 'list' ? 'List' : 'Icons'}
                        onClick={() => update({ layout: mode === 'grid' ? 'grid' : undefined }, true)}
                        className={`px-2.5 py-1.5 transition-colors focus-visible:ring-2 focus-visible:ring-accent ${layout === mode ? 'bg-accent-dim text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}
                      >
                        {mode === 'list' ? <List className="h-4 w-4" /> : <LayoutGrid className="h-4 w-4" />}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {(showFilters || (filtered && !lumen)) && page?.documents && (
                <div className="flex flex-wrap items-center gap-2">
                  <Select aria-label="Kind of document" value={category} onChange={(e) => update({ category: e.target.value || undefined })} className="!w-auto max-w-[14rem]">
                    <option value="">Any kind</option>
                    {[...new Set(Object.values(options?.categories ?? {}).flat())].sort().map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                  <Select aria-label="Status" value={status} onChange={(e) => update({ status: e.target.value || undefined })} className="!w-auto">
                    <option value="">Any status</option>
                    {(options?.statuses ?? []).map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </Select>
                  <Select aria-label="Expiry" value={expiry} onChange={(e) => update({ expiry: e.target.value || undefined })} className="!w-auto">
                    <option value="">Any expiry</option>
                    <option value="expired">Expired</option>
                    <option value="expiring">Expiring soon</option>
                    <option value="valid">Valid</option>
                    <option value="none">No expiry</option>
                  </Select>
                  {tag && (
                    <button type="button" onClick={() => update({ tag: undefined })} aria-label={`Remove tag ${tag}`}>
                      <Badge variant="cyan">tag: {tag} ×</Badge>
                    </button>
                  )}
                  {filtered && (
                    <Button variant="ghost" size="sm" onClick={() => update({ category: undefined, status: undefined, expiry: undefined, tag: undefined })}>
                      Clear filters
                    </Button>
                  )}
                </div>
              )}

              <div className="panel min-h-[18rem]">
                {rows.length === 0 && !draft && !loading ? (
                  <div className="flex min-h-[18rem] flex-col items-center justify-center gap-2 px-6 py-10 text-center" onContextMenu={(e) => {
                    e.preventDefault()
                    setMenu({ x: e.clientX, y: e.clientY, row: null })
                  }}>
                    <p className="text-sm font-medium text-[color:var(--color-text)]">
                      {q || filtered ? (placesOnly ? 'Nothing is called that.' : 'No document matches. Try fewer words or clear the filters.') : inTrash ? 'The trash is empty.' : 'This folder is empty.'}
                    </p>
                    {!q && !filtered && !inTrash && canWrite && page?.documents !== null && (
                      <p className="text-sm text-[color:var(--color-text-muted)]">Drop files or folders here, or use Upload{canMake ? ' or New folder' : ''}.</p>
                    )}
                    {lumen && !q && !filtered && !inTrash && canWrite && page?.documents !== null && (
                      <div className="mt-2 flex flex-wrap justify-center gap-2">
                        <Button onClick={() => setUpload({ files: [], folderId: page?.space?.folder_id ?? null })}>
                          <Upload className="h-4 w-4" /> Add documents
                        </Button>
                        {canMake && (
                          <Button variant="secondary" onClick={() => setDraft(true)}>
                            <FolderPlus className="h-4 w-4" /> New folder
                          </Button>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <ExplorerList
                    rows={rows}
                    view={layout}
                    selected={selected}
                    canWrite={canWrite && !inTrash}
                    showLocation={searching || flat(node)}
                    sort={sort}
                    renaming={renaming}
                    draft={draft}
                    onSelect={setSelected}
                    onOpen={open}
                    onMenu={(row, x, y) => setMenu({ x, y, row })}
                    onSort={sortBy}
                    onRename={(row, name) => void rename(row, name)}
                    onCancelRename={() => setRenaming(null)}
                    onDraft={(name) => void createFolder(name)}
                    onCancelDraft={() => setDraft(false)}
                    onAction={onAction}
                    onDropOnFolder={dropOnFolderRow}
                    onFilesOnFolder={filesOnFolderRow}
                  />
                )}
                {loading && <p className="px-4 py-3 text-sm text-[color:var(--color-text-muted)]">Loading…</p>}
                {!loading && items.length < total && (
                  <div className="border-t border-[color:var(--color-border)] px-4 py-3 text-center">
                    <Button variant="secondary" size="sm" onClick={loadMore}>
                      Show more ({total - items.length} left)
                    </Button>
                  </div>
                )}
              </div>
              {!lumen && (
              <p className="text-xs text-[color:var(--color-text-faint)]">
                {canWrite && !inTrash
                  ? 'Double-click to open · drag onto a folder (or a folder in the list on the left) to move · right-click for more · F2 renames · Backspace goes up.'
                  : 'Double-click to open · right-click for more · Backspace goes up.'}
              </p>
              )}
            </>
          )}
            </>
          )}
        </main>
      </div>

      {lumen && chosen.length > 0 && !isDrive && !showLanding && (
        <SelectionBar count={chosen.length} onClear={() => setSelected(new Set())}>
          {selectionTools}
        </SelectionBar>
      )}

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.row)} onClose={() => setMenu(null)} />}

      <FolderPicker
        open={mover !== null}
        title={mover && mover.ids.length + mover.folder_ids.length > 1 ? `Move ${mover.ids.length + mover.folder_ids.length} items to…` : 'Move to…'}
        hint="Open a folder, a case, a client or Company documents, then choose it. A bill or an employee's paper that Orion filed is kept where you put it."
        confirmLabel="Move here"
        startNode={page?.trail && page.trail.length > 1 && isDestination(page.node.kind) ? page.node.id : 'root'}
        canMakeFolders={canWrite}
        onClose={() => setMover(null)}
        onPick={async (to, label) => {
          if (!mover) return
          await moveTo(mover, to, label)
          setMover(null)
        }}
      />

      <FolderPicker
        open={toDrive !== null}
        title={toDrive?.move ? 'Move to Google Drive…' : 'Copy to Google Drive…'}
        hint="Choose the folder in Google Drive. Confidential documents and employees’ papers are sent only if you confirm."
        confirmLabel={toDrive?.move ? 'Move here' : 'Copy here'}
        source="drive"
        startNode="gdrive"
        canMakeFolders={canWrite}
        onClose={() => setToDrive(null)}
        onPick={async (to, label) => {
          if (!toDrive) return
          await sendToDrive(toDrive.payload, driveFolderOf(to), toDrive.move, label)
          setToDrive(null)
        }}
      />

      {dropping && (
        <DropFolderDialog
          items={dropping.items}
          alsoDocuments={dropping.ids.length}
          onClose={() => setDropping(null)}
          onConfirm={async () => {
            const { items, ids, folderIds } = dropping
            setDropping(null)
            const blocked = new Set(items.filter((info) => !info.can_drop).map((info) => info.folder_id)) // said why in the dialog; left alone
            await carryOutDelete(ids, folderIds.filter((id) => !blocked.has(id)), items.filter((info) => info.can_drop))
          }}
        />
      )}

      <DocumentDrawer
        id={openId}
        options={options ?? EMPTY_OPTIONS}
        canWrite={canWrite}
        isAdmin={isAdmin}
        onClose={() => update({ doc: undefined })}
        onChanged={(message) => {
          if (message) toast.show(message)
          refresh()
        }}
      />

      <input
        ref={folderInput}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        // A folder chooser is not in React's types; the browser then gives every file in the folder, with its path.
        {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
        onChange={(e) => {
          if (e.target.files?.length) startUpload(fromFileList(e.target.files), page?.space?.folder_id ?? null)
          e.target.value = ''
        }}
      />

      {options && (
        <UploadModal
          open={upload !== null}
          initialFiles={upload?.files ?? []}
          initialEmptyFolders={upload?.emptyFolders}
          initialLeftOut={upload?.leftOut}
          initialSpace={space}
          initialFolders={[]}
          initialCategory={upload?.category}
          initialFolderId={upload?.folderId}
          options={options}
          onClose={() => setUpload(null)}
          onUploaded={(message) => {
            if (message) toast.show(message)
            refresh()
          }}
          onFolderCreated={refresh}
        />
      )}
    </div>
  )
}

const EMPTY_OPTIONS: DocumentOptions = {
  scopes: [],
  categories: { company: [], case: [], client: [] },
  statuses: [],
  confidentiality: [],
  checklist: [],
  standard_folders: { company: [], case: [], client: [] },
  accepted: '',
  max_mb: 0,
  max_tags: 0,
}
