import type { ReactNode } from 'react'
import { AlertTriangle, CalendarClock, FilePen, HardDrive, Library } from 'lucide-react'
import { formatDateTime } from '../../formatTime'
import type { DocumentOverview, DocumentSummary } from '../../types'
import { Badge } from '../ui/Alert'
import { ExpiryBadge, fileSize, FileTypeIcon, spaceLabel } from './docUi'

function Stat({
  icon,
  label,
  value,
  tone = 'default',
  onClick,
}: {
  icon: ReactNode
  label: string
  value: string | number
  tone?: 'default' | 'warning' | 'negative'
  onClick?: () => void
}) {
  const color = tone === 'negative' ? 'text-negative' : tone === 'warning' ? 'text-warning' : 'text-accent'
  const inner = (
    <>
      <span className={`${color}`}>{icon}</span>
      <span className="mt-2 block text-2xl font-bold tabular-nums tracking-tight text-[color:var(--color-text)]">{value}</span>
      <span className="block text-xs text-[color:var(--color-text-muted)]">{label}</span>
    </>
  )
  return onClick ? (
    <button type="button" onClick={onClick} className="panel interactive p-4 text-left hover:border-[color:var(--color-border-strong)] focus-visible:ring-2 focus-visible:ring-accent">
      {inner}
    </button>
  ) : (
    <div className="panel p-4">{inner}</div>
  )
}

function DocList({ title, empty, docs, onOpen, showExpiry }: { title: string; empty: string; docs: DocumentSummary[]; onOpen: (id: number) => void; showExpiry?: boolean }) {
  return (
    <section className="panel p-4">
      <h3 className="t-h3 text-[color:var(--color-text)]">{title}</h3>
      {docs.length === 0 ? (
        <p className="mt-3 rounded-lg bg-muted px-3 py-2 text-sm text-[color:var(--color-text-muted)]">{empty}</p>
      ) : (
        <ul className="mt-2 divide-y divide-[color:var(--color-border)]">
          {docs.map((doc) => (
            <li key={doc.id}>
              <button type="button" onClick={() => onOpen(doc.id)} className="flex w-full items-center gap-3 py-2.5 text-left hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-accent">
                <FileTypeIcon type={doc.content_type} className="h-5 w-5 shrink-0 text-accent" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-[color:var(--color-text)]">{doc.title}</span>
                  <span className="block truncate text-xs text-[color:var(--color-text-muted)]">
                    {spaceLabel(doc)} · {doc.category}
                    {!showExpiry && ` · ${formatDateTime(doc.last_updated_timestamp)}`}
                  </span>
                </span>
                {showExpiry && <ExpiryBadge doc={doc} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** The Document Center's front page: what needs attention (expired and expiring documents), what is new, and how much is stored. */
export function Overview({
  data,
  onOpen,
  onFilter,
}: {
  data: DocumentOverview
  onOpen: (id: number) => void
  onFilter: (filter: { expiry?: string; status?: string; tag?: string }) => void
}) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat icon={<Library className="h-5 w-5" />} label="Documents" value={data.total} onClick={() => onFilter({})} />
        <Stat icon={<AlertTriangle className="h-5 w-5" />} label="Expired" value={data.expired} tone={data.expired ? 'negative' : 'default'} onClick={() => onFilter({ expiry: 'expired' })} />
        <Stat icon={<CalendarClock className="h-5 w-5" />} label="Expiring soon" value={data.expiring} tone={data.expiring ? 'warning' : 'default'} onClick={() => onFilter({ expiry: 'expiring' })} />
        <Stat icon={<FilePen className="h-5 w-5" />} label="Drafts" value={data.drafts} onClick={() => onFilter({ status: 'Draft' })} />
        <Stat icon={<HardDrive className="h-5 w-5" />} label="Stored" value={fileSize(data.stored_bytes)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <DocList title="Expired" empty="Nothing has expired." docs={data.expired_documents} onOpen={onOpen} showExpiry />
        <DocList title="Expiring soon" empty="Nothing is close to expiring." docs={data.expiring_documents} onOpen={onOpen} showExpiry />
      </div>
      <DocList title="Recently changed" empty="No documents have been filed yet. Use Upload to file the first one." docs={data.recent} onOpen={onOpen} />

      {data.tags.length > 0 && (
        <section className="panel p-4">
          <h3 className="t-h3 text-[color:var(--color-text)]">Tags</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {data.tags.map((t) => (
              <button key={t.tag} type="button" onClick={() => onFilter({ tag: t.tag })} className="focus-visible:ring-2 focus-visible:ring-accent">
                <Badge variant="cyan">
                  {t.tag} · {t.n}
                </Badge>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
