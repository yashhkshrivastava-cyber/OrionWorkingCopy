import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, ArrowUp, ChevronRight, Download, ExternalLink, FolderInput, FolderPlus, HardDrive, Pencil, RefreshCw, Search, Settings, Trash2, Upload, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { formatDateTime } from '../../formatTime'
import type { DriveItem, DriveListing, DriveStatus } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { saveBlob } from '../ui/PdfPreview'
import { useToast } from '../ui/Toast'
import { fileSize, FileTypeIcon } from './docUi'
import { driveFolderOf, driveNode } from './driveNodes'
import { ContextMenu, DRAG_TYPE, DRIVE_DRAG_TYPE, EntryIcon, type DragPayload, type MenuItem } from './explorerUi'
import { FolderPicker } from './FolderPicker'

/**
 * Google Drive, inside the Document Center. It is laid out like the rest (the way in at the top, a list below, a right-click menu, drag and drop)
 * and works on whichever Drive the server is connected to: the real Google Drive once its credentials are in the .env, a stand-in kept on this
 * computer until then. Files go between Orion and Drive by copy (or move: the original is put in the trash only after the copy exists).
 */
export function DriveSection({
  node,
  status,
  canWrite,
  isAdmin,
  version,
  go,
  onTrail,
  onStatus,
  onChanged,
  onDropOrion,
}: {
  node: string
  status: DriveStatus | null
  canWrite: boolean
  isAdmin: boolean
  /** Changes when something happened elsewhere on the page (a copy into Orion), so this list is read again. */
  version: number
  go: (node: string) => void
  onTrail: (trail: { id: string; label: string }[]) => void
  onStatus: () => void
  onChanged: () => void
  /** Documents of Orion dropped on a Drive folder here: copy them. */
  onDropOrion: (payload: DragPayload, driveFolderId: string, label: string) => void
}) {
  const navigate = useNavigate()
  const toast = useToast()
  const folder = driveFolderOf(node)
  const [listing, setListing] = useState<DriveListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [problems, setProblems] = useState<{ name: string; message: string }[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [reload, setReload] = useState(0)
  const [menu, setMenu] = useState<{ x: number; y: number; item: DriveItem | null } | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState(false)
  const [into, setInto] = useState<{ ids: string[]; move: boolean } | null>(null)
  const [moving, setMoving] = useState<string[] | null>(null)
  const [settings, setSettings] = useState(false)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState<string | null>(null)
  const anchor = useRef<string | null>(null)
  const picker = useRef<HTMLInputElement>(null)

  const connected = Boolean(status?.connected)
  const refresh = useCallback(() => setReload((n) => n + 1), [])

  useEffect(() => {
    const timer = window.setTimeout(() => setQ(search), 300)
    return () => window.clearTimeout(timer)
  }, [search])
  useEffect(() => setSearch(''), [folder])

  useEffect(() => {
    if (!connected) {
      setListing(null)
      return
    }
    let stale = false
    setLoading(true)
    api
      .driveBrowse(folder, q || undefined)
      .then((found) => {
        if (stale) return
        setListing(found)
        setError('')
        onTrail(found.trail.map((step) => ({ id: driveNode(step.id), label: step.name })))
      })
      .catch((e: Error) => {
        if (stale) return
        setError(e.message)
        if (folder !== 'root') go('gdrive')
      })
      .finally(() => !stale && setLoading(false))
    return () => {
      stale = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, folder, q, reload, version])

  useEffect(() => setSelected(new Set()), [folder, q])

  // Coming back from Google (or Google refusing): the address says which, and is then cleaned.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('drive_connected')) toast.show('Google Drive is connected.')
    if (params.get('drive_error')) setError(params.get('drive_error') ?? '')
    if (params.has('drive_connected') || params.has('drive_error')) {
      params.delete('drive_connected')
      params.delete('drive_error')
      navigate(`/documents?${params}`, { replace: true })
      onStatus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const rows: DriveItem[] = useMemo(() => [...(listing?.folders ?? []), ...(listing?.files ?? [])], [listing])
  const chosen = rows.filter((row) => selected.has(row.id))
  const here = listing?.trail[listing.trail.length - 1]
  const parent = listing && listing.trail.length > 1 ? listing.trail[listing.trail.length - 2].id : null
  const write = canWrite && connected

  const fail = (e: unknown) => setError((e as Error).message)

  const open = (item: DriveItem) => {
    if (item.is_folder) go(driveNode(item.id))
    else void download(item)
  }

  const download = async (item: DriveItem) => {
    try {
      saveBlob(await api.driveDownload(item.id), item.name)
    } catch (e) {
      fail(e)
    }
  }

  const report = (r: { done: number; failed: { name: string; message: string }[]; to: string; moved: boolean }, verb: string) => {
    setProblems(r.failed)
    if (r.done) toast.show(`${r.moved ? 'Moved' : 'Copied'} ${r.done} ${r.done === 1 ? 'file' : 'files'} ${verb} ${r.to}.`)
    else if (!r.failed.length) toast.show('Nothing was copied.')
    onChanged()
    refresh()
  }

  const copyInto = async (ids: string[], move: boolean, to: string) => {
    try {
      report(await api.driveCopyFrom(ids, to, move), 'to')
      setSelected(new Set())
    } catch (e) {
      fail(e)
    }
  }

  const moveWithin = async (ids: string[], folderId: string) => {
    try {
      for (const id of ids) await api.driveMove(id, folderId)
      toast.show(`Moved ${ids.length} ${ids.length === 1 ? 'item' : 'items'}.`)
      setSelected(new Set())
      refresh()
      onChanged()
    } catch (e) {
      fail(e)
    }
  }

  const trashItems = async (items: DriveItem[]) => {
    if (!items.length || !window.confirm(`Move ${items.length === 1 ? `"${items[0].name}"` : `${items.length} items`} to the trash in Google Drive?`)) return
    try {
      for (const item of items) await api.driveTrash(item.id)
      setSelected(new Set())
      refresh()
      onChanged()
    } catch (e) {
      fail(e)
    }
  }

  const rename = async (item: DriveItem, name: string) => {
    setRenaming(null)
    if (!name.trim() || name.trim() === item.name) return
    try {
      await api.driveRename(item.id, name.trim())
      refresh()
    } catch (e) {
      fail(e)
    }
  }

  const makeFolder = async (name: string) => {
    setDraft(false)
    if (!name.trim()) return
    try {
      await api.driveNewFolder(folder, name.trim())
      refresh()
      onChanged()
    } catch (e) {
      fail(e)
    }
  }

  const uploadFiles = async (files: File[]) => {
    setBusy(true)
    const failed: { name: string; message: string }[] = []
    for (const file of files) {
      try {
        await api.driveUpload(folder, file)
      } catch (e) {
        failed.push({ name: file.name, message: (e as Error).message })
      }
    }
    setBusy(false)
    setProblems(failed)
    if (files.length > failed.length) toast.show(`Uploaded ${files.length - failed.length} ${files.length - failed.length === 1 ? 'file' : 'files'} to Drive.`)
    refresh()
  }

  const connect = async () => {
    setBusy(true)
    try {
      const r = await api.driveConnect()
      if (r.url) {
        window.location.href = r.url // to Google; it sends the admin back to /api/gdrive/callback
        return
      }
      onStatus()
      toast.show('Connected.')
    } catch (e) {
      fail(e)
    } finally {
      setBusy(false)
    }
  }

  const select = (item: DriveItem, event: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) => {
    if (event.shiftKey && anchor.current) {
      const from = rows.findIndex((r) => r.id === anchor.current)
      const to = rows.findIndex((r) => r.id === item.id)
      const [low, high] = from < to ? [from, to] : [to, from]
      setSelected(new Set(rows.slice(low, high + 1).map((r) => r.id)))
    } else if (event.ctrlKey || event.metaKey) {
      const next = new Set(selected)
      if (next.has(item.id)) next.delete(item.id)
      else next.add(item.id)
      setSelected(next)
      anchor.current = item.id
    } else {
      setSelected(new Set([item.id]))
      anchor.current = item.id
    }
  }

  const menuItems = (item: DriveItem | null): MenuItem[] => {
    if (!item) {
      return [
        ...(write ? [{ label: 'New folder', icon: <FolderPlus className="h-4 w-4" />, onClick: () => setDraft(true) }] : []),
        ...(write ? [{ label: 'Upload files…', icon: <Upload className="h-4 w-4" />, onClick: () => picker.current?.click() }] : []),
        { label: 'Refresh', icon: <RefreshCw className="h-4 w-4" />, onClick: refresh },
      ]
    }
    const own = chosen.length > 1 && selected.has(item.id) ? chosen : [item]
    const files = own.filter((r) => r.copyable)
    return [
      { label: item.is_folder ? 'Open' : 'Download', icon: item.is_folder ? undefined : <Download className="h-4 w-4" />, onClick: () => open(item) },
      ...(item.url ? [{ label: 'Open in Google Drive', icon: <ExternalLink className="h-4 w-4" />, onClick: () => window.open(item.url ?? '', '_blank', 'noopener,noreferrer') }] : []),
      { label: 'Copy into Orion…', icon: <FolderInput className="h-4 w-4" />, divider: true, disabled: !canWrite || files.length === 0, onClick: () => setInto({ ids: files.map((r) => r.id), move: false }) },
      { label: 'Move into Orion…', icon: <FolderInput className="h-4 w-4" />, disabled: !canWrite || files.length === 0, onClick: () => setInto({ ids: files.map((r) => r.id), move: true }) },
      { label: 'Rename', icon: <Pencil className="h-4 w-4" />, divider: true, disabled: !write || own.length > 1, onClick: () => setRenaming(item.id) },
      { label: 'Move to…', icon: <FolderInput className="h-4 w-4" />, disabled: !write, onClick: () => setMoving(own.map((r) => r.id)) },
      { label: own.length > 1 ? `Move ${own.length} items to the Drive trash` : 'Move to the Drive trash', icon: <Trash2 className="h-4 w-4" />, danger: true, disabled: !write, onClick: () => void trashItems(own) },
    ]
  }

  // --- not connected ---------------------------------------------------------------------------------------------------------
  if (!status) return <p className="text-sm text-[color:var(--color-text-muted)]">Loading…</p>

  if (status.mode === 'off') {
    return (
      <section className="panel space-y-2 p-6">
        <div className="flex items-center gap-3">
          <HardDrive className="h-6 w-6 text-accent" aria-hidden="true" />
          <h2 className="t-h2 text-[color:var(--color-text)]">Google Drive is not set up here</h2>
        </div>
        <p className="text-sm text-[color:var(--color-text-muted)]">
          To use it, an administrator adds Orion's Google client ID and secret to this server's settings and restarts it. The steps are in DEPLOYMENT.md, under
          &ldquo;Google Drive&rdquo;.
        </p>
      </section>
    )
  }

  if (!connected) {
    return (
      <section className="panel space-y-3 p-6">
        {error && (
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        )}
        <div className="flex items-center gap-3">
          <HardDrive className="h-6 w-6 text-accent" aria-hidden="true" />
          <h2 className="t-h2 text-[color:var(--color-text)]">{status.mode === 'fake' ? 'Connect the practice Drive' : 'Connect Google Drive'}</h2>
        </div>
        <p className="text-sm text-[color:var(--color-text-muted)]">
          {status.mode === 'fake'
            ? 'This server has no Google credentials yet, so Drive is a stand-in kept on this computer: it works like Google Drive so the feature can be tried, but nothing goes to Google.'
            : 'Connect the company’s Google account once. People then browse its folders here, copy documents to and from Orion, and bills can be saved to it. The sign-in happens on Google’s own page; Orion never sees the password.'}
        </p>
        {status.reconnect && (
          <p className="text-sm text-warning">The connection was made before this server was set up differently, so it has to be made again. Nothing in Drive or Orion is lost.</p>
        )}
        {status.can_connect ? (
          <Button onClick={connect} loading={busy}>
            <HardDrive className="h-4 w-4" /> {status.mode === 'fake' ? 'Connect the practice Drive' : 'Connect Google Drive'}
          </Button>
        ) : (
          <p className="text-sm text-[color:var(--color-text-muted)]">Ask an administrator to connect it.</p>
        )}
      </section>
    )
  }

  // --- connected ---------------------------------------------------------------------------------------------------------------
  return (
    <div
      className="space-y-3"
      onDragOver={(e) => write && e.dataTransfer.types.includes('Files') && e.preventDefault()}
      onDrop={(e) => {
        if (!write || !e.dataTransfer.files.length) return
        e.preventDefault()
        void uploadFiles(Array.from(e.dataTransfer.files))
      }}
    >
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow mb-1">Documents</p>
          <h1 className="truncate t-h1 text-[color:var(--color-text)]">{listing?.searching ? 'Search results' : (here?.name ?? 'My Drive')}</h1>
          <p className="mt-0.5 text-sm text-[color:var(--color-text-muted)]">
            {status.account ? `Connected as ${status.account}` : 'Connected'}
            {status.mode === 'fake' ? ' · practice Drive on this computer' : ''}
            {listing ? ` · ${listing.folders.length} ${listing.folders.length === 1 ? 'folder' : 'folders'}, ${listing.files.length} ${listing.files.length === 1 ? 'file' : 'files'}` : ''}
          </p>
        </div>
        {isAdmin && (
          <Button variant="secondary" onClick={() => setSettings(true)}>
            <Settings className="h-4 w-4" /> Drive settings
          </Button>
        )}
      </header>

      {status.mode === 'fake' && (
        <Alert variant="info">
          This is a practice Drive stored on this computer. To use the real Google Drive, add the Google client ID and secret to the server settings and restart: the
          same screens then work on the company’s Drive (see DEPLOYMENT.md, “Google Drive”).
        </Alert>
      )}
      {error && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}
      {problems.length > 0 && (
        <Alert variant="error" onDismiss={() => setProblems([])}>
          {problems.length === 1 ? 'One file was not copied:' : `${problems.length} files were not copied:`}{' '}
          {problems.slice(0, 4).map((p) => `${p.name} (${p.message})`).join('; ')}
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center">
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)} aria-label="Back" title="Back">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => navigate(1)} aria-label="Forward" title="Forward">
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" disabled={!parent} onClick={() => parent && go(driveNode(parent))} aria-label="Up one level" title="Up one level">
            <ArrowUp className="h-4 w-4" />
          </Button>
        </div>
        <ol className="panel scroll-quiet flex min-w-[15rem] flex-1 items-center gap-0.5 overflow-x-auto px-2 py-1 text-sm" aria-label="Where you are">
          {[{ id: 'root', name: 'Documents' }, { id: 'gdrive', name: 'Google Drive' }, ...(listing?.trail.slice(1) ?? []).map((s) => ({ id: s.id, name: s.name }))].map((step, index, all) => {
            const last = index === all.length - 1
            const target = index === 0 ? 'root' : index === 1 ? 'gdrive' : driveNode(step.id)
            const droppable = write && index >= 1
            return (
              <li key={`${step.id}-${index}`} className="flex shrink-0 items-center gap-0.5">
                {index > 0 && <ChevronRight className="h-3.5 w-3.5 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
                <button
                  type="button"
                  onClick={() => go(target)}
                  aria-current={last ? 'location' : undefined}
                  onDragOver={(e) => droppable && (e.dataTransfer.types.includes(DRAG_TYPE) || e.dataTransfer.types.includes(DRIVE_DRAG_TYPE)) && e.preventDefault()}
                  onDrop={(e) => {
                    if (!droppable) return
                    const orion = e.dataTransfer.getData(DRAG_TYPE)
                    const drive = e.dataTransfer.getData(DRIVE_DRAG_TYPE)
                    if (!orion && !drive) return
                    e.preventDefault()
                    if (orion) onDropOrion(JSON.parse(orion) as DragPayload, driveFolderOf(target), step.name)
                    else void moveWithin(JSON.parse(drive) as string[], driveFolderOf(target))
                  }}
                  className={`rounded-md px-1.5 py-1 transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-accent ${last ? 'font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)]'}`}
                >
                  {step.name}
                </button>
              </li>
            )
          })}
        </ol>
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search all of Drive" aria-label="Search Drive" className="pl-9" />
        </div>
      </div>

      <div className="flex min-h-[2.75rem] items-center gap-2">
        <div className="scroll-quiet flex min-w-0 flex-1 items-center gap-2 overflow-x-auto py-1">
          {chosen.length === 0 ? (
            <>
              {write && (
                <Button variant="secondary" size="sm" onClick={() => setDraft(true)} disabled={draft} aria-label="New folder">
                  <FolderPlus className="h-4 w-4" /> <span className="hidden sm:inline">New folder</span>
                </Button>
              )}
              {write && (
                <Button size="sm" onClick={() => picker.current?.click()} loading={busy}>
                  <Upload className="h-4 w-4" /> Upload
                </Button>
              )}
            </>
          ) : (
            <div className="flex items-center gap-2" role="region" aria-label="Selected items">
              <span className="shrink-0 whitespace-nowrap rounded-full bg-accent-dim px-2.5 py-1 text-xs font-semibold text-[color:var(--color-text)]">{chosen.length} selected</span>
              {chosen.length === 1 && !chosen[0].is_folder && (
                <Button variant="secondary" size="sm" onClick={() => void download(chosen[0])}>
                  <Download className="h-4 w-4" /> Download
                </Button>
              )}
              {canWrite && chosen.some((r) => r.copyable) && (
                <>
                  <Button size="sm" onClick={() => setInto({ ids: chosen.filter((r) => r.copyable).map((r) => r.id), move: false })}>
                    <FolderInput className="h-4 w-4" /> Copy into Orion…
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setInto({ ids: chosen.filter((r) => r.copyable).map((r) => r.id), move: true })}>
                    Move into Orion…
                  </Button>
                </>
              )}
              {write && (
                <>
                  <Button variant="secondary" size="sm" onClick={() => setMoving(chosen.map((r) => r.id))}>
                    Move to…
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => void trashItems(chosen)}>
                    <Trash2 className="h-4 w-4" /> Trash
                  </Button>
                </>
              )}
              <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())} aria-label="Clear the selection">
                <X className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      </div>

      <div className="panel min-h-[18rem]" onContextMenu={(e) => {
        e.preventDefault()
        setMenu({ x: e.clientX, y: e.clientY, item: null })
      }}>
        {rows.length === 0 && !draft && !loading ? (
          <div className="flex min-h-[18rem] flex-col items-center justify-center gap-2 px-6 py-10 text-center">
            <p className="text-sm font-medium text-[color:var(--color-text)]">{listing?.searching ? 'Nothing in Drive matches.' : 'This folder is empty.'}</p>
            {write && !listing?.searching && <p className="text-sm text-[color:var(--color-text-muted)]">Drop files here, or use Upload or New folder.</p>}
          </div>
        ) : (
          <div className="overflow-x-auto outline-none" tabIndex={0} role="group" aria-label="Items in Drive" onKeyDown={(e) => {
            if ((e.target as HTMLElement).tagName === 'INPUT') return
            if (e.key === 'Backspace' && parent) {
              e.preventDefault()
              go(driveNode(parent))
            } else if (e.key === 'F2' && chosen.length === 1 && write) setRenaming(chosen[0].id)
            else if (e.key === 'Enter' && chosen.length === 1) open(chosen[0])
            else if (e.key === 'Escape') setSelected(new Set())
          }}>
            <table className="w-full min-w-[22rem] table-fixed text-left text-sm">
              <thead>
                <tr className="border-b border-[color:var(--color-border)] text-xs text-[color:var(--color-text-muted)]">
                  <th className="py-2.5 pl-4 pr-2 font-medium">Name</th>
                  <th className="hidden w-44 px-2 py-2.5 font-medium md:table-cell">Changed</th>
                  <th className="hidden w-28 px-2 py-2.5 font-medium sm:table-cell">Size</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[color:var(--color-border)]">
                {draft && (
                  <tr className="bg-accent-dim/20">
                    <td className="py-2 pl-4 pr-2" colSpan={3}>
                      <div className="flex max-w-md items-center gap-3">
                        <EntryIcon kind="driveFolder" className="h-5 w-5 shrink-0 text-accent" />
                        <NameInput initial="New folder" onCommit={(name) => void makeFolder(name)} onCancel={() => setDraft(false)} />
                      </div>
                    </td>
                  </tr>
                )}
                {rows.map((item) => (
                  <tr
                    key={item.id}
                    aria-selected={selected.has(item.id)}
                    draggable={write && renaming !== item.id}
                    onClick={(e) => select(item, e)}
                    onDoubleClick={() => open(item)}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      if (!selected.has(item.id)) setSelected(new Set([item.id]))
                      setMenu({ x: e.clientX, y: e.clientY, item })
                    }}
                    onDragStart={(e) => {
                      const ids = selected.has(item.id) ? [...selected] : [item.id]
                      e.dataTransfer.setData(DRIVE_DRAG_TYPE, JSON.stringify(ids))
                      e.dataTransfer.effectAllowed = 'copyMove'
                    }}
                    onDragEnd={() => setOver(null)}
                    onDragOver={(e) => {
                      if (!write || !item.is_folder || !(e.dataTransfer.types.includes(DRAG_TYPE) || e.dataTransfer.types.includes(DRIVE_DRAG_TYPE))) return
                      e.preventDefault()
                      setOver(item.id)
                    }}
                    onDragLeave={() => setOver((now) => (now === item.id ? null : now))}
                    onDrop={(e) => {
                      setOver(null)
                      if (!write || !item.is_folder) return
                      const orion = e.dataTransfer.getData(DRAG_TYPE)
                      const drive = e.dataTransfer.getData(DRIVE_DRAG_TYPE)
                      if (!orion && !drive) return
                      e.preventDefault()
                      e.stopPropagation()
                      if (orion) onDropOrion(JSON.parse(orion) as DragPayload, item.id, item.name)
                      else {
                        const ids = (JSON.parse(drive) as string[]).filter((id) => id !== item.id)
                        if (ids.length) void moveWithin(ids, item.id)
                      }
                    }}
                    className={`cursor-default select-none ${over === item.id ? 'bg-accent-dim ring-2 ring-inset ring-accent' : selected.has(item.id) ? 'bg-accent-dim/40' : 'hover:bg-muted/60'}`}
                  >
                    <td className="max-w-0 py-2 pl-4 pr-2">
                      <div className="flex items-center gap-3">
                        {item.is_folder ? <EntryIcon kind="driveFolder" className="h-5 w-5 shrink-0 text-accent" /> : <FileTypeIcon type={item.mime} className="h-5 w-5 shrink-0 text-accent" />}
                        {renaming === item.id ? (
                          <NameInput initial={item.name} onCommit={(name) => void rename(item, name)} onCancel={() => setRenaming(null)} />
                        ) : (
                          <span className="min-w-0 truncate font-medium text-[color:var(--color-text)]" title={item.name}>
                            {item.name}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="hidden px-2 py-2 text-xs text-[color:var(--color-text-muted)] md:table-cell">{item.modified ? formatDateTime(item.modified) : ''}</td>
                    <td className="hidden px-2 py-2 tabular-nums text-[color:var(--color-text-muted)] sm:table-cell">{item.size ? fileSize(item.size) : item.is_folder ? '' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {loading && <p className="px-4 py-3 text-sm text-[color:var(--color-text-muted)]">Loading…</p>}
        {listing?.next && !loading && <p className="border-t border-[color:var(--color-border)] px-4 py-3 text-center text-xs text-[color:var(--color-text-muted)]">Only the first 200 are shown. Search to find the rest.</p>}
      </div>
      <p className="text-xs text-[color:var(--color-text-faint)]">
        Double-click opens a folder or downloads a file · drag files onto a folder here, or onto a folder in the list on the left to copy them into Orion · drop files from your computer to upload.
      </p>

      <input
        ref={picker}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) void uploadFiles(Array.from(e.target.files))
          e.target.value = ''
        }}
      />

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.item)} onClose={() => setMenu(null)} />}

      <FolderPicker
        open={into !== null}
        title={into?.move ? 'Move into Orion…' : 'Copy into Orion…'}
        hint="Choose where in Orion the files should be kept: a folder, a case, a client or Company documents. Each becomes a document there (a Google Doc or Sheet as a PDF or Excel file)."
        confirmLabel={into?.move ? 'Move here' : 'Copy here'}
        canMakeFolders={canWrite}
        onClose={() => setInto(null)}
        onPick={async (to) => {
          if (!into) return
          await copyInto(into.ids, into.move, to)
          setInto(null)
        }}
      />
      <FolderPicker
        open={moving !== null}
        title="Move to…"
        hint="Choose the folder in Google Drive."
        confirmLabel="Move here"
        source="drive"
        startNode="gdrive"
        canMakeFolders={write}
        onClose={() => setMoving(null)}
        onPick={async (to) => {
          if (!moving) return
          await moveWithin(moving.filter((id) => driveFolderOf(to) !== id), driveFolderOf(to))
          setMoving(null)
        }}
      />
      {settings && <DriveSettings status={status} onClose={() => setSettings(false)} onSaved={onStatus} />}
    </div>
  )
}

function NameInput({ initial, onCommit, onCancel }: { initial: string; onCommit: (name: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState(initial)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    input.current?.focus()
    input.current?.select()
  }, [])
  return (
    <input
      ref={input}
      value={value}
      maxLength={200}
      aria-label="Name"
      onChange={(e) => setValue(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Enter') {
          if (value.trim()) onCommit(value)
        } else if (e.key === 'Escape') onCancel()
      }}
      onBlur={() => (value.trim() && value.trim() !== initial ? onCommit(value) : onCancel())}
      className="w-full rounded-md border border-accent bg-surface px-1.5 py-0.5 text-sm text-[color:var(--color-text)] outline-none ring-2 ring-[color:var(--orion-ring)]"
    />
  )
}

/** The company's settings for Drive: whether a new bill is also saved to it, and where; and disconnecting. Admins only. */
function DriveSettings({ status, onClose, onSaved }: { status: DriveStatus; onClose: () => void; onSaved: () => void }) {
  const [mode, setMode] = useState<string>(status.bills.mode)
  const [folder, setFolder] = useState<{ id: string; label: string } | null>(status.bills.folder_id ? { id: status.bills.folder_id, label: status.bills.folder_label ?? '' } : null)
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await api.driveSettings(mode, mode === 'off' ? null : (folder?.id ?? null))
      onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    if (!window.confirm('Disconnect Google Drive? Nothing in Drive or Orion is deleted, and it can be connected again.')) return
    try {
      await api.driveDisconnect()
      onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Modal
      open
      title="Drive settings"
      onClose={onClose}
      footer={
        <>
          <Button variant="danger" className="mr-auto" onClick={disconnect}>
            Disconnect
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy} disabled={mode === 'on' && !folder}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && <Alert variant="error">{error}</Alert>}
        <Field label="New bills" hint="Each bill’s PDF is the file in Drive, and an edit or a cancellation of the bill updates it. Whoever issues a bill can still choose otherwise for that bill.">
          <Select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="off">Never saved to Drive</option>
            <option value="ask">Ask each time (the tick starts off)</option>
            <option value="on">Always saved to Drive (the tick starts on)</option>
          </Select>
        </Field>
        {mode !== 'off' && (
          <Field label={mode === 'on' ? 'Folder for bills' : 'Folder suggested for bills'}>
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate rounded-lg border border-[color:var(--color-border)] px-3 py-2 text-sm text-[color:var(--color-text)]">{folder?.label || 'No folder chosen'}</span>
              <Button variant="secondary" onClick={() => setPicking(true)}>
                Choose…
              </Button>
            </div>
          </Field>
        )}
        <p className="text-xs text-[color:var(--color-text-muted)]">Confidential documents and employees’ papers are never sent to Drive unless a person confirms it for that document.</p>
      </div>
      <FolderPicker
        open={picking}
        title="Folder for bills in Drive"
        confirmLabel="Use this folder"
        source="drive"
        startNode="gdrive"
        canMakeFolders
        onClose={() => setPicking(false)}
        onPick={(node, label) => {
          setFolder({ id: driveFolderOf(node), label })
          setPicking(false)
        }}
      />
    </Modal>
  )
}
