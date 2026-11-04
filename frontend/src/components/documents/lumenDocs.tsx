import { useEffect, useRef, useState, type CSSProperties, type DragEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUp,
  Briefcase,
  Building2,
  CalendarClock,
  ChevronRight,
  Cloud,
  FilePen,
  FolderTree,
  FolderUp,
  Library,
  Search,
  Trash2,
  Upload,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { timeAgo } from '../../formatTime'
import { IconTile } from '../../lumen/IconTile'
import type { DocumentOverview, DocumentSummary, ExplorerEntry } from '../../types'
import { ExpiryBadge, fileSize, FileTypeIcon, spaceLabel } from './docUi'
import { DRAG_TYPE, type DragPayload } from './explorerUi'

/** Lumen's forms of the Document Center: the same places, documents and actions, drawn for someone who wants to find, add and open a paper rather than operate a file explorer. */

// ---------------------------------------------------------------------------------------------------------------- search

/** The search box, large and rounded: the first thing a person reaches for. */
export function LumenSearch({
  value,
  onChange,
  placeholder,
  onEnter,
  large = false,
  bare = false,
  focusOnMount = false,
}: {
  value: string
  onChange: (next: string) => void
  placeholder: string
  onEnter?: () => void
  large?: boolean
  /** Drawn on a light surface of its own (the front door's white pill): no fill or edge of its own. */
  bare?: boolean
  /** The box takes the cursor, at the end of what is typed: used when typing moves the person from the front door to the results, so they can go on typing. */
  focusOnMount?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const node = input.current
    if (!focusOnMount || !node) return
    node.focus()
    node.setSelectionRange(node.value.length, node.value.length)
    // takes the cursor when the box appears, and again only if asked to later
  }, [focusOnMount])
  return (
    <label className={`relative block w-full ${large ? '' : 'sm:max-w-md'}`}>
      <span className="sr-only">Search</span>
      <Search className={`pointer-events-none absolute top-1/2 -translate-y-1/2 text-[color:var(--color-text-faint)] ${large ? 'left-5 h-5 w-5' : 'left-4 h-4 w-4'}`} aria-hidden="true" />
      <input
        ref={input}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => event.key === 'Enter' && onEnter?.()}
        placeholder={placeholder}
        aria-label="Search"
        className={`w-full rounded-full ${large ? 'h-14 pr-14 text-base' : 'h-11 pr-10 text-sm'} ${bare ? '!border-0 !bg-transparent !text-ink !shadow-none' : ''}`}
        style={{ paddingLeft: large ? '3.25rem' : '2.75rem' }}
      />
      {value && (
        <button type="button" aria-label="Clear the search" onClick={() => onChange('')} className="interactive absolute right-3 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      )}
    </label>
  )
}

// -------------------------------------------------------------------------------------------------------------- crumbs

/** Where you are, as steps you can click (and drop on), with Back and Up. */
export function LumenCrumbs({
  crumbs,
  canDrop,
  canUp,
  onGo,
  onBack,
  onUp,
  onDropItems,
  treeButton,
}: {
  crumbs: { id: string; label: string }[]
  canDrop: (id: string) => boolean
  canUp: boolean
  onGo: (id: string) => void
  onBack: () => void
  onUp: () => void
  onDropItems: (payload: DragPayload, id: string, label: string) => void
  treeButton?: ReactNode
}) {
  const round = 'interactive grid h-9 w-9 shrink-0 place-items-center rounded-full border border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted disabled:opacity-40'
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" onClick={onBack} aria-label="Back" title="Back" className={round}>
        <ArrowLeft className="h-4 w-4" />
      </button>
      <button type="button" onClick={onUp} disabled={!canUp} aria-label="Up one level" title="Up one level" className={round}>
        <ArrowUp className="h-4 w-4" />
      </button>
      <ol className="scroll-quiet flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label="Where you are">
        {crumbs.map((step, index) => {
          const last = index === crumbs.length - 1
          const target = canDrop(step.id)
          const drop = (event: DragEvent) => {
            const raw = event.dataTransfer.getData(DRAG_TYPE)
            if (!target || !raw) return
            event.preventDefault()
            onDropItems(JSON.parse(raw) as DragPayload, step.id, step.label)
          }
          return (
            <li key={step.id} className="flex shrink-0 items-center gap-1">
              {index > 0 && <ChevronRight className="h-3.5 w-3.5 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
              <button
                type="button"
                onClick={() => onGo(step.id)}
                aria-current={last ? 'location' : undefined}
                onDragOver={(event) => target && event.dataTransfer.types.includes(DRAG_TYPE) && event.preventDefault()}
                onDrop={drop}
                className={`interactive rounded-full px-3 py-1.5 text-sm ${last ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}
              >
                {step.label}
              </button>
            </li>
          )
        })}
      </ol>
      {treeButton}
    </div>
  )
}

/** Show or hide the folder tree: a map for people who like one, out of the way for those who do not. */
export function TreeToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} aria-pressed={open} className={`interactive inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold ${open ? 'border-transparent bg-accent-dim text-[color:var(--color-text)]' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
      <FolderTree className="h-4 w-4" aria-hidden="true" /> Folder map
    </button>
  )
}

// --------------------------------------------------------------------------------------------------------- quick filters

export interface QuickState {
  expiry: string
  status: string
}

/** The questions people actually ask of a list of papers, as one-tap chips; the finer filters stay one tap further. */
export function QuickFilters({ state, onPick, moreOpen, moreActive, onMore }: { state: QuickState; onPick: (patch: { expiry?: string; status?: string }) => void; moreOpen: boolean; moreActive: boolean; onMore: () => void }) {
  const chips: { label: string; on: boolean; patch: { expiry?: string; status?: string } }[] = [
    { label: 'Everything', on: !state.expiry && !state.status, patch: { expiry: undefined, status: undefined } },
    { label: 'Expiring soon', on: state.expiry === 'expiring', patch: { expiry: 'expiring', status: undefined } },
    { label: 'Expired', on: state.expiry === 'expired', patch: { expiry: 'expired', status: undefined } },
    { label: 'Drafts', on: state.status === 'Draft', patch: { expiry: undefined, status: 'Draft' } },
  ]
  return (
    <div role="group" aria-label="Show" className="flex flex-wrap items-center gap-2">
      {chips.map((chip) => (
        <button key={chip.label} type="button" aria-pressed={chip.on} onClick={() => onPick(chip.patch)} className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${chip.on ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
          {chip.label}
        </button>
      ))}
      <button type="button" onClick={onMore} aria-expanded={moreOpen} className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${moreOpen || moreActive ? 'border-[color:var(--color-accent)] text-accent' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
        More filters{moreActive ? ' on' : ''}
      </button>
    </div>
  )
}

/** The bar of what can be done to what is ticked, floating at the foot of the screen so it is never scrolled away. */
export function SelectionBar({ count, onClear, children }: { count: number; onClear: () => void; children: ReactNode }) {
  // In the body, not in the page: the page is animated, and a fixed bar inside an animated block is fixed to the block, not to the window.
  return createPortal(
    <div role="region" aria-label="Selected items" className="pointer-events-none fixed inset-x-0 bottom-24 z-40 flex justify-center px-4 lg:bottom-5">
      <div className="panel pointer-events-auto flex max-w-full items-center gap-2 overflow-x-auto !rounded-full !px-3 !py-2 shadow-raised">
        <span className="shrink-0 whitespace-nowrap rounded-full bg-accent-dim px-3 py-1.5 text-sm font-bold text-[color:var(--color-text)]">{count} selected</span>
        {children}
        <button type="button" onClick={onClear} aria-label="Clear the selection" className="interactive grid h-9 w-9 shrink-0 place-items-center rounded-full text-[color:var(--color-text-muted)] hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>,
    document.body,
  )
}

// ------------------------------------------------------------------------------------------------------------ the rows

/** One line under a document's name, in words rather than codes. */
export function plainSubline(doc: DocumentSummary, withLocation: boolean): string {
  return [
    doc.category,
    withLocation ? `${spaceLabel(doc)}${doc.folder_name ? ` / ${doc.folder_name}` : ''}` : '',
    doc.source ? `Filed from ${doc.source.label}` : '',
    doc.current_version > 1 ? `version ${doc.current_version}` : '',
    `changed ${timeAgo(doc.last_updated_timestamp)}${doc.updated_by_name ? ` by ${doc.updated_by_name}` : ''}`,
  ]
    .filter(Boolean)
    .join(' · ')
}

export function FileSizeText({ bytes }: { bytes: number }) {
  return <span className="tabular-nums text-xs text-[color:var(--color-text-faint)]">{fileSize(bytes)}</span>
}

// ---------------------------------------------------------------------------------------------------------- the landing

const PLACE_ICON: Record<string, [LucideIcon, string, string]> = {
  company: [Building2, 'indigo', 'Company documents'],
  clients: [Users, 'teal', 'Clients'],
  cases: [Briefcase, 'coral', 'Cases'],
  gdrive: [Cloud, 'blue', 'Google Drive'],
}

/** A big, friendly door to one part of the Document Center. */
function PlaceCard({ icon: Icon, hue, title, hint, count, onClick }: { icon: LucideIcon; hue: string; title: string; hint: string; count?: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="panel lumen-kpi interactive relative flex flex-col items-start gap-3 overflow-hidden !p-5 text-left focus-visible:ring-2 focus-visible:ring-accent">
      <IconTile icon={Icon} hue={hue} className="h-10 w-10" />
      <span className="relative">
        <span className="font-display block text-lg font-semibold">{title}</span>
        <span className="t-caption block text-[color:var(--color-text-muted)]">{hint}</span>
      </span>
      {count && <span className="relative mt-auto rounded-full bg-muted px-2.5 py-0.5 text-xs font-bold tabular-nums">{count}</span>}
    </button>
  )
}

function Attention({ icon: Icon, hue, label, value, hint, onClick }: { icon: LucideIcon; hue: string; label: string; value: number; hint: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="panel lumen-kpi interactive relative flex flex-col gap-1 overflow-hidden !p-5 text-left focus-visible:ring-2 focus-visible:ring-accent">
      <span className="t-caption relative flex items-center gap-2 font-semibold text-[color:var(--color-text-muted)]">
        <Icon className="h-4 w-4" aria-hidden="true" /> {label}
      </span>
      <span className="lumen-figure relative block font-display font-semibold tabular-nums">{value}</span>
      <span className="t-caption relative text-[color:var(--color-text-faint)]">{hint}</span>
    </button>
  )
}

function DocLine({ doc, onOpen, showExpiry }: { doc: DocumentSummary; onOpen: (id: number) => void; showExpiry?: boolean }) {
  return (
    <li>
      <button type="button" onClick={() => onOpen(doc.id)} className="interactive flex w-full items-center gap-3 rounded-2xl px-2 py-2 text-left hover:bg-muted/70 focus-visible:ring-2 focus-visible:ring-accent">
        <FileTypeIcon type={doc.content_type} className="h-10 w-10" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{doc.title}</span>
          <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{plainSubline(doc, true)}</span>
        </span>
        {showExpiry && <ExpiryBadge doc={doc} />}
      </button>
    </li>
  )
}

/**
 * The front door. A large search, the way to add papers, what needs attention (what has expired or is about to), the few places papers live in plain words,
 * and what changed lately. Everything here opens the same places and filters the explorer does.
 */
export function LumenLanding({
  overview,
  places,
  driveOn,
  canWrite,
  search,
  onSearch,
  onSubmitSearch,
  onUpload,
  onUploadFolder,
  onGo,
  onOpen,
  onFilter,
}: {
  overview: DocumentOverview | null
  places: ExplorerEntry[]
  driveOn: boolean
  canWrite: boolean
  search: string
  onSearch: (next: string) => void
  onSubmitSearch: () => void
  onUpload: () => void
  onUploadFolder: () => void
  onGo: (node: string) => void
  onOpen: (id: number) => void
  onFilter: (filter: { expiry?: string; status?: string; tag?: string }) => void
}) {
  const [moreTags, setMoreTags] = useState(false)
  const count = (node: string) => {
    const entry = places.find((p) => p.node === node)
    return entry ? `${entry.documents} ${entry.documents === 1 ? 'document' : 'documents'}` : undefined
  }
  const hint: Record<string, string> = { company: 'Registrations, policies, licences, people', clients: 'Everything filed for each client', cases: 'Tenders, work orders and papers of each case', gdrive: 'The company’s Google Drive' }
  const doors = ['company', 'clients', 'cases', ...(driveOn ? ['gdrive'] : [])]
  const attention = overview ? [...overview.expired_documents, ...overview.expiring_documents].slice(0, 6) : []
  const tags = overview ? (moreTags ? overview.tags : overview.tags.slice(0, 14)) : []
  return (
    <div className="space-y-6">
      <section aria-label="Find a document" className="panel relative overflow-hidden !p-0 text-[color:var(--orion-on-primary)]" style={{ backgroundImage: 'var(--orion-highlight-fill)' }}>
        <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
        <div className="relative space-y-4 p-6 sm:p-8">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-85">Documents</p>
            <h1 className="font-display mt-1 text-3xl font-semibold leading-tight sm:text-4xl">Find any document</h1>
            <p className="mt-1 max-w-xl text-sm opacity-90">Type a name, a client, a case, a tag, or words that are inside a PDF or Word file.</p>
          </div>
          <div className="rounded-full bg-white/95 text-ink shadow-card">
            <LumenSearch value={search} onChange={onSearch} onEnter={onSubmitSearch} large bare placeholder="Search all documents" />
          </div>
          {canWrite && (
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={onUpload} className="interactive inline-flex h-11 items-center gap-2 rounded-full bg-white px-5 text-sm font-bold text-ink shadow-card">
                <Upload className="h-4 w-4" aria-hidden="true" /> Add documents
              </button>
              <button type="button" onClick={onUploadFolder} className="interactive inline-flex h-11 items-center gap-2 rounded-full bg-white/20 px-5 text-sm font-semibold backdrop-blur">
                <FolderUp className="h-4 w-4" aria-hidden="true" /> Add a whole folder
              </button>
              <span className="text-xs opacity-85">or drag files anywhere onto this page</span>
            </div>
          )}
        </div>
      </section>

      {overview && (
        <section aria-label="Needs attention">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Attention icon={AlertTriangle} hue={overview.expired ? 'coral' : 'green'} label="Expired" value={overview.expired} hint={overview.expired ? 'Renew or replace these' : 'Nothing has expired'} onClick={() => onFilter({ expiry: 'expired' })} />
            <Attention icon={CalendarClock} hue={overview.expiring ? 'amber' : 'green'} label="Expiring soon" value={overview.expiring} hint={overview.expiring ? 'Coming up for renewal' : 'Nothing is close to expiring'} onClick={() => onFilter({ expiry: 'expiring' })} />
            <Attention icon={FilePen} hue="indigo" label="Drafts" value={overview.drafts} hint="Not yet marked Active" onClick={() => onFilter({ status: 'Draft' })} />
            <Attention icon={Library} hue="teal" label="All documents" value={overview.total} hint={`${fileSize(overview.stored_bytes)} stored`} onClick={() => onFilter({})} />
          </div>
        </section>
      )}

      <section aria-label="Browse">
        <h2 className="t-h3 mb-3">Browse</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {doors.map((node) => {
            const [icon, hue, title] = PLACE_ICON[node]
            return <PlaceCard key={node} icon={icon} hue={hue} title={title} hint={hint[node]} count={count(node)} onClick={() => onGo(node)} />
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => onGo('all')} className="interactive inline-flex h-9 items-center gap-2 rounded-full border border-[color:var(--color-border)] px-4 text-sm font-semibold text-[color:var(--color-text-muted)] hover:bg-muted">
            <Library className="h-4 w-4" aria-hidden="true" /> Every document in one list
          </button>
          <button type="button" onClick={() => onGo('trash')} className="interactive inline-flex h-9 items-center gap-2 rounded-full border border-[color:var(--color-border)] px-4 text-sm font-semibold text-[color:var(--color-text-muted)] hover:bg-muted">
            <Trash2 className="h-4 w-4" aria-hidden="true" /> Trash
          </button>
        </div>
      </section>

      {overview && (
        <div className="grid items-start gap-5 xl:grid-cols-2">
          <section className="panel !p-4" aria-label="Needs attention list">
            <h2 className="t-h3 px-2">Needs a look</h2>
            {attention.length === 0 ? (
              <p className="mx-2 mt-3 rounded-2xl bg-positive-dim px-4 py-3 text-sm font-semibold text-positive">Everything with an expiry date is in date.</p>
            ) : (
              <ul className="mt-2">{attention.map((doc) => <DocLine key={doc.id} doc={doc} onOpen={onOpen} showExpiry />)}</ul>
            )}
          </section>
          <section className="panel !p-4" aria-label="Recently changed">
            <h2 className="t-h3 px-2">Changed lately</h2>
            {overview.recent.length === 0 ? (
              <p className="mx-2 mt-3 rounded-2xl bg-muted px-4 py-3 text-sm text-[color:var(--color-text-muted)]">Nothing has been filed yet. Use Add documents to file the first one.</p>
            ) : (
              <ul className="mt-2">{overview.recent.slice(0, 6).map((doc) => <DocLine key={doc.id} doc={doc} onOpen={onOpen} />)}</ul>
            )}
          </section>
        </div>
      )}

      {overview && overview.tags.length > 0 && (
        <section aria-label="Tags">
          <h2 className="t-h3 mb-3">Tags</h2>
          <div className="flex flex-wrap gap-2">
            {tags.map((t) => (
              <button key={t.tag} type="button" onClick={() => onFilter({ tag: t.tag })} className="interactive rounded-full bg-accent-dim px-3.5 py-1.5 text-sm font-semibold text-[color:var(--color-text)] hover:brightness-110">
                {t.tag} <span className="text-[color:var(--color-text-muted)]">{t.n}</span>
              </button>
            ))}
            {overview.tags.length > 14 && (
              <button type="button" onClick={() => setMoreTags((v) => !v)} className="interactive rounded-full border border-[color:var(--color-border)] px-3.5 py-1.5 text-sm font-semibold text-[color:var(--color-text-muted)] hover:bg-muted">
                {moreTags ? 'Fewer tags' : `All ${overview.tags.length} tags`}
              </button>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
