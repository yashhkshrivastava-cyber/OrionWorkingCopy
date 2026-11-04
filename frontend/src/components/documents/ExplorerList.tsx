import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent, type MouseEvent } from 'react'
import { ArrowDown, ArrowUp, Check, Lock, MoreHorizontal } from 'lucide-react'
import type { DocumentSummary, ExplorerEntry } from '../../types'
import { timeAgo } from '../../formatTime'
import { day, ExpiryBadge, fileSize, FileTypeIcon, spaceLabel, StatusBadge } from './docUi'
import { useLumen } from '../../lumen/useLumen'
import { DRAG_TYPE, EntryIcon, isDestination, type DragPayload } from './explorerUi'
import { FileSizeText, plainSubline } from './lumenDocs'

export type Row = { key: string; type: 'folder'; entry: ExplorerEntry } | { key: string; type: 'doc'; doc: DocumentSummary }

export type SortKey = 'title' | 'updated' | 'size' | 'expiry'

export const rowKey = {
  folder: (node: string) => `f:${node}`,
  doc: (id: number) => `d:${id}`,
}

/** The ids behind a set of selected rows, as the server takes them. */
export function payloadOf(rows: Row[], keys: Set<string>): DragPayload {
  const ids: number[] = []
  const folder_ids: number[] = []
  for (const row of rows) {
    if (!keys.has(row.key)) continue
    if (row.type === 'doc') ids.push(row.doc.id)
    else if (row.entry.kind === 'folder') folder_ids.push(Number(row.entry.node.split(':')[1]))
  }
  return { ids, folder_ids }
}

const boxClass = (large?: boolean) =>
  `w-full rounded-md border border-accent bg-surface px-1.5 py-0.5 text-[color:var(--color-text)] outline-none ring-2 ring-[color:var(--orion-ring)] ${large ? 'text-center text-xs' : 'text-sm'}`

/** The name of a row being renamed: Enter keeps it, Escape or leaving it unchanged does not. */
function NameBox({ initial, max, large, onCommit, onCancel }: { initial: string; max: number; large?: boolean; onCommit: (name: string) => void; onCancel: () => void }) {
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
      maxLength={max}
      aria-label="New name"
      onChange={(event) => setValue(event.target.value)}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation()
        if (event.key === 'Enter') onCommit(value)
        else if (event.key === 'Escape') onCancel()
      }}
      onBlur={() => (value.trim() && value.trim() !== initial ? onCommit(value) : onCancel())}
      className={boxClass(large)}
    />
  )
}

/** The name of a folder that is being made. */
function DraftBox({ large, onCommit, onCancel }: { large?: boolean; onCommit: (name: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState('New folder')
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    input.current?.focus()
    input.current?.select()
  }, [])
  return (
    <input
      ref={input}
      value={value}
      maxLength={80}
      aria-label="Name of the new folder"
      onChange={(event) => setValue(event.target.value)}
      onKeyDown={(event) => {
        event.stopPropagation()
        if (event.key === 'Enter') {
          if (value.trim()) onCommit(value)
        }
        else if (event.key === 'Escape') onCancel()
      }}
      onBlur={() => (value.trim() ? onCommit(value) : onCancel())}
      className={boxClass(large)}
    />
  )
}

/** The grey line under a document's name: its code, version, where a filed paper came from, and (in a search) where it is. One line. */
function subline(doc: DocumentSummary, withLocation: boolean): string {
  return [
    doc.code,
    doc.current_version > 1 ? `v${doc.current_version}` : '',
    doc.source ? `Filed from ${doc.source.label}` : '',
    withLocation ? `${spaceLabel(doc)}${doc.folder_name ? ` / ${doc.folder_name}` : ''}` : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

const coarse = () => typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches

/**
 * What is in a place, as a list or as icons, behaving as people expect of a file explorer: click to select, Ctrl or Shift to select
 * more, double-click (or Enter) to open, right-click for a menu, F2 to rename, drag onto a folder to move, drop files on a folder to
 * upload into it. The page owns the selection and does the work; this only draws and reports.
 */
export function ExplorerList({
  rows,
  view,
  selected,
  canWrite,
  showLocation,
  sort,
  renaming,
  draft,
  onSelect,
  onOpen,
  onMenu,
  onSort,
  onRename,
  onCancelRename,
  onDraft,
  onCancelDraft,
  onAction,
  onDropOnFolder,
  onFilesOnFolder,
}: {
  rows: Row[]
  view: 'list' | 'grid'
  selected: Set<string>
  canWrite: boolean
  showLocation: boolean
  sort: { key: SortKey; dir: 'asc' | 'desc' }
  renaming: string | null
  draft: boolean
  onSelect: (next: Set<string>) => void
  onOpen: (row: Row) => void
  onMenu: (row: Row | null, x: number, y: number) => void
  onSort: (key: SortKey) => void
  onRename: (row: Row, name: string) => void
  onCancelRename: () => void
  onDraft: (name: string) => void
  onCancelDraft: () => void
  onAction: (action: 'up' | 'delete' | 'rename' | 'back') => void
  onDropOnFolder: (row: Row, payload: DragPayload) => void
  /** Files or folders dropped from the computer onto a folder row; read them before the drop event ends. */
  onFilesOnFolder: (row: Row, transfer: DataTransfer) => void
}) {
  const lumen = useLumen()
  const anchor = useRef<string | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  const [dropOn, setDropOn] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  // Which columns fit is decided by the width of this list, not of the window: the tree and the menu on the left take room the window does not show.
  const [width, setWidth] = useState(900)
  useEffect(() => {
    const node = box.current
    if (!node) return
    const watch = new ResizeObserver(() => setWidth(node.clientWidth))
    watch.observe(node)
    setWidth(node.clientWidth)
    return () => watch.disconnect()
  }, [view])
  const cols = { expiry: width >= 640, kind: width >= 760, changed: width >= 900, size: width >= 1040 }

  useEffect(() => {
    if (focus && !rows.some((row) => row.key === focus)) setFocus(null)
  }, [rows, focus])

  const indexOf = (key: string | null) => rows.findIndex((row) => row.key === key)

  const choose = (row: Row, event: { ctrlKey: boolean; metaKey: boolean; shiftKey: boolean }) => {
    const additive = event.ctrlKey || event.metaKey
    if (event.shiftKey && anchor.current) {
      const from = indexOf(anchor.current)
      const to = indexOf(row.key)
      if (from >= 0 && to >= 0) {
        const [low, high] = from < to ? [from, to] : [to, from]
        onSelect(new Set(rows.slice(low, high + 1).map((r) => r.key)))
      }
    } else if (additive) {
      const next = new Set(selected)
      if (next.has(row.key)) next.delete(row.key)
      else next.add(row.key)
      onSelect(next)
      anchor.current = row.key
    } else {
      onSelect(new Set([row.key]))
      anchor.current = row.key
    }
    setFocus(row.key)
  }

  const onClickRow = (row: Row, event: MouseEvent) => {
    if (renaming) return
    choose(row, event)
    if (coarse() && !event.ctrlKey && !event.metaKey && !event.shiftKey) onOpen(row)
  }

  const onKey = (event: KeyboardEvent) => {
    if ((event.target as HTMLElement).tagName === 'INPUT') return
    const at = indexOf(focus ?? [...selected][0] ?? null)
    const step = (by: number) => {
      event.preventDefault()
      if (!rows.length) return
      const next = rows[Math.min(rows.length - 1, Math.max(0, (at < 0 ? (by > 0 ? -1 : rows.length) : at) + by))]
      choose(next, { ctrlKey: false, metaKey: false, shiftKey: event.shiftKey })
      box.current?.querySelector(`[data-key="${CSS.escape(next.key)}"]`)?.scrollIntoView({ block: 'nearest' })
    }
    if (event.key === 'ArrowDown' || (view === 'grid' && event.key === 'ArrowRight')) step(1)
    else if (event.key === 'ArrowUp' || (view === 'grid' && event.key === 'ArrowLeft')) step(-1)
    else if (event.key === 'Enter' && at >= 0) {
      event.preventDefault()
      onOpen(rows[at])
    } else if (event.key === 'F2') {
      event.preventDefault()
      onAction('rename')
    } else if (event.key === 'Delete') {
      event.preventDefault()
      onAction('delete')
    } else if (event.key === 'Backspace' || (event.altKey && event.key === 'ArrowUp')) {
      event.preventDefault()
      onAction('up')
    } else if (event.altKey && event.key === 'ArrowLeft') {
      event.preventDefault()
      onAction('back')
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
      event.preventDefault()
      onSelect(new Set(rows.map((row) => row.key)))
    } else if (event.key === 'Escape') onSelect(new Set())
  }

  // --- dragging -----------------------------------------------------------------------------------------------------
  const movable = (row: Row) => canWrite && !(row.type === 'folder' && (row.entry.kind !== 'folder' || row.entry.system))

  const dragStart = (row: Row, event: DragEvent) => {
    let keys = selected
    if (!selected.has(row.key)) {
      keys = new Set([row.key])
      onSelect(keys)
    }
    const payload = payloadOf(rows.filter((r) => movable(r)), keys)
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(payload))
    event.dataTransfer.effectAllowed = 'move'
  }

  const accepts = (row: Row, event: DragEvent) =>
    canWrite && row.type === 'folder' && isDestination(row.entry.kind) && (event.dataTransfer.types.includes(DRAG_TYPE) || event.dataTransfer.types.includes('Files'))

  const dragOver = (row: Row, event: DragEvent) => {
    if (!accepts(row, event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes(DRAG_TYPE) ? 'move' : 'copy'
    setDropOn(row.key)
  }

  const drop = (row: Row, event: DragEvent) => {
    setDropOn(null)
    if (!accepts(row, event)) return
    event.preventDefault()
    event.stopPropagation()
    const raw = event.dataTransfer.getData(DRAG_TYPE)
    if (raw) {
      const payload = JSON.parse(raw) as DragPayload
      if (row.type === 'folder' && payload.folder_ids.includes(Number(row.entry.node.split(':')[1]))) return
      onDropOnFolder(row, payload)
    } else if (event.dataTransfer.files.length) onFilesOnFolder(row, event.dataTransfer)
  }

  const common = (row: Row) => ({
    'data-key': row.key,
    draggable: movable(row) && renaming !== row.key,
    onClick: (event: MouseEvent) => onClickRow(row, event),
    onDoubleClick: () => !renaming && onOpen(row),
    onContextMenu: (event: MouseEvent) => {
      event.preventDefault()
      event.stopPropagation()
      if (!selected.has(row.key)) {
        onSelect(new Set([row.key]))
        anchor.current = row.key
      }
      setFocus(row.key)
      onMenu(row, event.clientX, event.clientY)
    },
    onDragStart: (event: DragEvent) => dragStart(row, event),
    onDragEnd: () => setDropOn(null),
    onDragOver: (event: DragEvent) => dragOver(row, event),
    onDragLeave: () => setDropOn((now) => (now === row.key ? null : now)),
    onDrop: (event: DragEvent) => drop(row, event),
  })

  const tone = (row: Row) =>
    dropOn === row.key
      ? 'bg-accent-dim ring-2 ring-inset ring-accent'
      : selected.has(row.key)
        ? 'bg-accent-dim/40'
        : focus === row.key
          ? 'bg-muted/70'
          : 'hover:bg-muted/60'

  const nameOf = (row: Row) => (row.type === 'folder' ? row.entry.name : row.doc.title)

  const sortHead = (id: SortKey, label: string, className = '') => (
    <th className={`px-2 py-2.5 font-medium ${className}`} aria-sort={sort.key === id ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(id)} className="inline-flex items-center gap-1 hover:text-[color:var(--color-text)] focus-visible:ring-2 focus-visible:ring-accent">
        {label}
        {sort.key === id && (sort.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )

  if (lumen) {
    // Lumen: a click opens (a file or a folder); a tick box on each row selects; the three dots open the same menu as a right-click.
    const folders = rows.filter((row): row is Extract<Row, { type: 'folder' }> => row.type === 'folder')
    const docs = rows.filter((row): row is Extract<Row, { type: 'doc' }> => row.type === 'doc')
    const handlers = (row: Row) => ({
      ...common(row),
      onClick: (event: MouseEvent) => {
        if (renaming) return
        if (event.ctrlKey || event.metaKey || event.shiftKey) choose(row, event)
        else onOpen(row)
      },
      onDoubleClick: undefined,
    })
    const tick = (row: Row) => (
      <button
        type="button"
        role="checkbox"
        aria-checked={selected.has(row.key)}
        aria-label={`Select ${nameOf(row)}`}
        onClick={(event) => {
          event.stopPropagation()
          choose(row, { ctrlKey: true, metaKey: false, shiftKey: false })
        }}
        className={`interactive grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 ${selected.has(row.key) ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)]' : 'border-[color:var(--color-border-strong)] text-transparent hover:border-[color:var(--color-accent)]'}`}
      >
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      </button>
    )
    const dots = (row: Row) => (
      <button
        type="button"
        aria-label={`More for ${nameOf(row)}`}
        onClick={(event) => {
          event.stopPropagation()
          if (!selected.has(row.key)) onSelect(new Set([row.key]))
          const at = event.currentTarget.getBoundingClientRect()
          onMenu(row, at.right - 8, at.bottom + 4)
        }}
        className="interactive grid h-8 w-8 shrink-0 place-items-center rounded-full text-[color:var(--color-text-muted)] hover:bg-muted"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
    )
    const ring = (row: Row) => (dropOn === row.key ? 'ring-2 ring-accent bg-accent-dim' : selected.has(row.key) ? 'ring-2 ring-[color:var(--color-accent)]' : '')
    const heading = (text: string, n: number) => (
      <h3 className="t-caption mb-2 mt-1 px-1 font-bold uppercase tracking-[0.1em] text-[color:var(--color-text-faint)]">
        {text} <span className="tabular-nums">{n}</span>
      </h3>
    )
    return (
      <div
        ref={box}
        role="listbox"
        aria-multiselectable="true"
        aria-label="Items"
        tabIndex={0}
        onKeyDown={onKey}
        onContextMenu={(event) => {
          event.preventDefault()
          onMenu(null, event.clientX, event.clientY)
        }}
        className="space-y-5 p-3 outline-none sm:p-4"
      >
        {(folders.length > 0 || draft) && (
          <section aria-label="Folders">
            {heading('Folders', folders.length)}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {draft && (
                <div className="flex items-center gap-3 rounded-2xl border border-dashed border-[color:var(--color-accent)] bg-accent-dim/30 p-3">
                  <EntryIcon kind="folder" className="h-10 w-10" />
                  <DraftBox onCommit={onDraft} onCancel={onCancelDraft} />
                </div>
              )}
              {folders.map((row) => (
                <div key={row.key} role="option" aria-selected={selected.has(row.key)} {...handlers(row)} title={row.entry.name} className={`group panel interactive flex cursor-pointer select-none items-center gap-3 !p-3 ${ring(row)}`}>
                  <EntryIcon kind={row.entry.kind} system={row.entry.system} className="h-10 w-10" />
                  <div className="min-w-0 flex-1">
                    {renaming === row.key ? (
                      <NameBox initial={row.entry.name} max={80} onCommit={(name) => onRename(row, name)} onCancel={onCancelRename} />
                    ) : (
                      <p className="truncate text-sm font-semibold">{row.entry.name}</p>
                    )}
                    <p className="truncate text-xs text-[color:var(--color-text-muted)]">
                      {row.entry.sub || `${row.entry.documents} ${row.entry.documents === 1 ? 'document' : 'documents'}`}
                      {row.entry.attention ? <span className="ml-2 rounded-full bg-warning-dim px-2 py-0.5 text-[11px] font-bold text-warning">{row.entry.attention} need attention</span> : null}
                    </p>
                  </div>
                  {canWrite && row.entry.kind === 'folder' && <span className="opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">{dots(row)}</span>}
                </div>
              ))}
            </div>
          </section>
        )}

        {docs.length > 0 && (
          <section aria-label="Documents">
            {heading('Documents', docs.length)}
            {view === 'grid' ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {docs.map((row) => (
                  <div key={row.key} role="option" aria-selected={selected.has(row.key)} {...handlers(row)} title={row.doc.title} className={`group panel interactive relative flex cursor-pointer select-none flex-col gap-3 !p-4 ${ring(row)}`}>
                    <div className="flex items-start justify-between gap-2">
                      <FileTypeIcon type={row.doc.content_type} className="h-14 w-14" />
                      <span className="flex items-center gap-1">
                        {tick(row)}
                        {dots(row)}
                      </span>
                    </div>
                    <div className="min-w-0">
                      {renaming === row.key ? (
                        <NameBox initial={row.doc.title} max={200} onCommit={(name) => onRename(row, name)} onCancel={onCancelRename} />
                      ) : (
                        <p className="line-clamp-2 text-sm font-semibold">{row.doc.title}</p>
                      )}
                      <p className="mt-0.5 line-clamp-2 text-xs text-[color:var(--color-text-muted)]">{plainSubline(row.doc, showLocation)}</p>
                    </div>
                    <div className="mt-auto flex flex-wrap items-center gap-1.5">
                      <StatusBadge status={row.doc.status} />
                      <ExpiryBadge doc={row.doc} />
                      {row.doc.confidentiality === 'Confidential' && <Lock className="h-3.5 w-3.5 text-violet" aria-label="Confidential" />}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {docs.map((row) => (
                  <div key={row.key} role="option" aria-selected={selected.has(row.key)} {...handlers(row)} className={`group panel interactive flex cursor-pointer select-none items-center gap-3 !p-3 ${ring(row)}`}>
                    {tick(row)}
                    <FileTypeIcon type={row.doc.content_type} className="h-10 w-10" />
                    <div className="min-w-0 flex-1">
                      {renaming === row.key ? (
                        <NameBox initial={row.doc.title} max={200} onCommit={(name) => onRename(row, name)} onCancel={onCancelRename} />
                      ) : (
                        <p className="flex items-center gap-2">
                          <span className="min-w-0 truncate text-sm font-semibold" title={row.doc.title}>
                            {row.doc.title}
                          </span>
                          {row.doc.confidentiality === 'Confidential' && (
                            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-violet-dim px-2 py-0.5 text-[11px] font-bold text-violet" title="Only people who may change documents, and admins, can see this">
                              <Lock className="h-3 w-3" aria-hidden="true" /> Confidential
                            </span>
                          )}
                        </p>
                      )}
                      <p className="truncate text-xs text-[color:var(--color-text-muted)]" title={plainSubline(row.doc, showLocation)}>
                        {plainSubline(row.doc, showLocation)}
                      </p>
                    </div>
                    <div className="hidden shrink-0 items-center gap-2 md:flex">
                      <StatusBadge status={row.doc.status} />
                      <ExpiryBadge doc={row.doc} />
                      <FileSizeText bytes={row.doc.size_bytes} />
                    </div>
                    {dots(row)}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    )
  }

  if (view === 'grid') {
    return (
      <div ref={box} role="listbox" aria-multiselectable="true" aria-label="Items" tabIndex={0} onKeyDown={onKey} onContextMenu={(event) => {
        event.preventDefault()
        onMenu(null, event.clientX, event.clientY)
      }} className="grid min-h-[16rem] grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] content-start gap-2 p-3 outline-none">
        {draft && (
          <div className="flex flex-col items-center gap-1.5 rounded-xl p-3">
            <EntryIcon kind="folder" className="h-12 w-12 text-accent" />
            <DraftBox large onCommit={onDraft} onCancel={onCancelDraft} />
          </div>
        )}
        {rows.map((row) => (
          <div
            key={row.key}
            role="option"
            aria-selected={selected.has(row.key)}
            {...common(row)}
            title={nameOf(row)}
            className={`flex cursor-default select-none flex-col items-center gap-1.5 rounded-xl p-3 text-center ${tone(row)}`}
          >
            {row.type === 'folder' ? (
              <EntryIcon kind={row.entry.kind} system={row.entry.system} className="h-12 w-12 text-accent" />
            ) : (
              <FileTypeIcon type={row.doc.content_type} className="h-12 w-12 text-accent" />
            )}
            {renaming === row.key ? (
              <NameBox initial={nameOf(row)} max={row.type === 'folder' ? 80 : 200} large onCommit={(name) => onRename(row, name)} onCancel={onCancelRename} />
            ) : (
              <span className="line-clamp-2 w-full break-words text-xs font-medium text-[color:var(--color-text)]">{nameOf(row)}</span>
            )}
            <span className="text-[11px] text-[color:var(--color-text-faint)]">
              {row.type === 'folder' ? `${row.entry.documents} ${row.entry.documents === 1 ? 'document' : 'documents'}` : fileSize(row.doc.size_bytes)}
            </span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div ref={box} role="group" aria-label="Items" className="overflow-x-auto outline-none" tabIndex={0} onKeyDown={onKey} onContextMenu={(event) => {
      event.preventDefault()
      onMenu(null, event.clientX, event.clientY)
    }}>
      <table className="w-full min-w-[24rem] table-fixed text-left text-sm" role="grid" aria-multiselectable="true">
        <thead>
          <tr className="border-b border-[color:var(--color-border)] text-xs text-[color:var(--color-text-muted)]">
            {sortHead('title', 'Name', 'pl-4')}
            {cols.kind && <th className="w-44 px-2 py-2.5 font-medium">Kind</th>}
            <th className="w-24 px-2 py-2.5 font-medium">Status</th>
            {cols.expiry && sortHead('expiry', 'Expiry', 'w-36')}
            {cols.size && sortHead('size', 'Size', 'w-28')}
            {cols.changed && sortHead('updated', 'Changed', 'w-32')}
          </tr>
        </thead>
        <tbody className="divide-y divide-[color:var(--color-border)]">
          {draft && (
            <tr className="bg-accent-dim/20">
              <td className="py-2 pl-4 pr-2" colSpan={6}>
                <div className="flex max-w-md items-center gap-3">
                  <EntryIcon kind="folder" className="h-5 w-5 shrink-0 text-accent" />
                  <DraftBox onCommit={onDraft} onCancel={onCancelDraft} />
                </div>
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <tr key={row.key} aria-selected={selected.has(row.key)} {...common(row)} className={`cursor-default select-none ${tone(row)}`}>
              <td className="max-w-0 py-2 pl-4 pr-2">
                <div className="flex items-center gap-3">
                  {row.type === 'folder' ? (
                    <EntryIcon kind={row.entry.kind} system={row.entry.system} className="h-5 w-5 shrink-0 text-accent" />
                  ) : (
                    <FileTypeIcon type={row.doc.content_type} className="h-5 w-5 shrink-0 text-accent" />
                  )}
                  <div className="min-w-0 flex-1">
                    {renaming === row.key ? (
                      <NameBox initial={nameOf(row)} max={row.type === 'folder' ? 80 : 200} onCommit={(name) => onRename(row, name)} onCancel={onCancelRename} />
                    ) : (
                      <p className="flex items-center gap-2">
                        <span className="min-w-0 truncate font-medium text-[color:var(--color-text)]" title={nameOf(row)}>
                          {nameOf(row)}
                        </span>
                        {row.type === 'doc' && row.doc.confidentiality === 'Confidential' && (
                          <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-violet-dim px-1.5 py-0.5 text-[11px] font-medium text-violet" title="Only people who may change documents, and admins, can see this">
                            <Lock className="h-3 w-3" aria-hidden="true" /> Confidential
                          </span>
                        )}
                        {row.type === 'folder' && row.entry.attention ? (
                          <span className="inline-flex shrink-0 whitespace-nowrap rounded-full bg-warning-dim px-1.5 py-0.5 text-[11px] font-medium text-warning">{row.entry.attention} need attention</span>
                        ) : null}
                      </p>
                    )}
                    {row.type === 'folder' ? (
                      row.entry.sub && <p className="truncate text-xs text-[color:var(--color-text-muted)]">{row.entry.sub}</p>
                    ) : (
                      <p className="truncate text-xs text-[color:var(--color-text-muted)]" title={subline(row.doc, showLocation)}>
                        {subline(row.doc, showLocation)}
                      </p>
                    )}
                  </div>
                </div>
              </td>
              {cols.kind && <td className="px-2 py-2 text-[color:var(--color-text-muted)]">
                {row.type === 'folder' ? (row.entry.kind === 'folder' ? 'Folder' : row.entry.kind === 'client' ? 'Client' : row.entry.kind === 'case' ? 'Case' : 'Place') : row.doc.category}
              </td>}
              <td className="px-2 py-2">{row.type === 'doc' && <StatusBadge status={row.doc.status} />}</td>
              {cols.expiry && <td className="px-2 py-2">
                {row.type === 'doc' && (
                  <>
                    <ExpiryBadge doc={row.doc} />
                    {!row.doc.expiry_date && <span className="text-[color:var(--color-text-faint)]">—</span>}
                  </>
                )}
              </td>}
              {cols.size && <td className="px-2 py-2 tabular-nums text-[color:var(--color-text-muted)]">
                {row.type === 'doc' ? fileSize(row.doc.size_bytes) : `${row.entry.documents} ${row.entry.documents === 1 ? 'document' : 'documents'}`}
              </td>}
              {cols.changed && <td className="px-2 py-2 text-xs text-[color:var(--color-text-muted)]" title={row.type === 'doc' ? day(row.doc.last_updated_timestamp) : undefined}>
                {row.type === 'doc' && (
                  <>
                    {timeAgo(row.doc.last_updated_timestamp)}
                    {row.doc.updated_by_name ? <span className="block">{row.doc.updated_by_name}</span> : null}
                  </>
                )}
              </td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
