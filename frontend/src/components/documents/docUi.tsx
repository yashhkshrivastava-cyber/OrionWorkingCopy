import { File as FileIcon, FileImage, FileSpreadsheet, FileText, Presentation } from 'lucide-react'
import type { DocExpiryState, DocScope, DocStatus, DocumentFolder, DocumentSummary } from '../../types'
import { Badge } from '../ui/Alert'
import { IconTile } from '../../lumen/IconTile'
import { useLumen } from '../../lumen/useLumen'

export const fileSize = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`

/** "12 Oct 2026" from a date or a timestamp, or "" when there is none. Uses the date as written, not the viewer's zone. */
export function day(iso: string | null | undefined): string {
  if (!iso) return ''
  const [year, month, date] = iso.slice(0, 10).split('-').map(Number)
  if (!year) return ''
  return `${String(date).padStart(2, '0')} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][month - 1]} ${year}`
}

/** Whole days from today to a date (negative when it has passed). */
export function daysFromToday(iso: string): number {
  const [year, month, date] = iso.slice(0, 10).split('-').map(Number)
  const today = new Date()
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((Date.UTC(year, month - 1, date) - start) / 86400000)
}

export function FileTypeIcon({ type, className = 'h-5 w-5' }: { type: string; className?: string }) {
  const lumen = useLumen()
  const [Icon, hue] = type.startsWith('image/')
    ? [FileImage, 'pink']
    : type.includes('spreadsheet') || type.includes('excel') || type === 'text/csv'
      ? [FileSpreadsheet, 'green']
      : type.includes('presentation') || type.includes('powerpoint')
        ? [Presentation, 'orange']
        : type === 'application/pdf'
          ? [FileText, 'coral']
          : type.includes('word') || type.startsWith('text/')
            ? [FileText, 'blue']
            : [FileIcon, 'slate']
  if (lumen) return <IconTile icon={Icon} hue={hue} className={className} />
  return <Icon className={className} aria-hidden="true" />
}

const STATUS_VARIANT: Record<DocStatus, 'default' | 'cyan' | 'amber' | 'emerald'> = {
  Draft: 'amber',
  Active: 'emerald',
  Superseded: 'default',
  Archived: 'default',
}

export function StatusBadge({ status }: { status: DocStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{status}</Badge>
}

/** The expiry date with how close it is. Nothing for a document with no expiry, or one that no longer matters. */
export function ExpiryBadge({ doc }: { doc: Pick<DocumentSummary, 'expiry_date' | 'expiry_state'> }) {
  if (!doc.expiry_date) return null
  const days = daysFromToday(doc.expiry_date)
  const state: DocExpiryState = doc.expiry_state
  if (state === 'expired') return <Badge variant="rose">Expired {Math.abs(days) === 1 ? 'yesterday' : `${Math.abs(days)} days ago`}</Badge>
  if (state === 'expiring') return <Badge variant="amber">{days === 0 ? 'Expires today' : `Expires in ${days} ${days === 1 ? 'day' : 'days'}`}</Badge>
  return <span className="text-xs text-[color:var(--color-text-muted)]">Expires {day(doc.expiry_date)}</span>
}

/** Where a document belongs, for lists that mix spaces. */
export function spaceLabel(doc: Pick<DocumentSummary, 'scope' | 'case_name' | 'client_name'>): string {
  if (doc.scope === 'company') return 'Company'
  if (doc.scope === 'case') return doc.case_name ? `${doc.case_name}${doc.client_name ? ` · ${doc.client_name}` : ''}` : 'Case'
  return doc.client_name ?? 'Client'
}

export const SCOPE_LABEL: Record<DocScope, string> = { company: 'Company', case: 'Case', client: 'Client' }

/** The folders of a space in tree order, each with how deep it is, for a list or a menu. */
export function folderOrder(folders: DocumentFolder[]): (DocumentFolder & { depth: number; path: string })[] {
  const byParent = new Map<number | null, DocumentFolder[]>()
  for (const folder of folders) byParent.set(folder.parent_id, [...(byParent.get(folder.parent_id) ?? []), folder])
  const out: (DocumentFolder & { depth: number; path: string })[] = []
  const walk = (parent: number | null, depth: number, path: string) => {
    for (const folder of byParent.get(parent) ?? []) {
      const here = path ? `${path} / ${folder.name}` : folder.name
      out.push({ ...folder, depth, path: here })
      walk(folder.id, depth + 1, here)
    }
  }
  walk(null, 0, '')
  return out
}

const GUESSES: [RegExp, string][] = [
  [/tender|rfp|nit\b|bid doc/i, 'Tender / RFP'],
  [/work.?order|\bwo\b|loi|award/i, 'Work order / LOI'],
  [/agreement|contract|mou/i, 'Contract / agreement'],
  [/guarantee|bg\b|emd|security deposit/i, 'Performance guarantee / EMD'],
  [/insurance|policy/i, 'Insurance'],
  [/invoice|bill|payment|receipt/i, 'Invoice and payment'],
  [/attendance|muster|wage|salary|payroll/i, 'Attendance and wages'],
  [/\bpf\b|esic|epf|challan/i, 'Compliance (PF / ESIC)'],
  [/gst/i, 'GST and tax'],
  [/pan\b|tax|itr|tds/i, 'Statutory and tax'],
  [/licen[cs]e|registration|certificate/i, 'Registration and licences'],
]

/** A category guessed from a file's name, if one of the space's categories fits. Never more than a starting point. */
export function guessCategory(fileName: string, categories: string[]): string {
  for (const [pattern, category] of GUESSES) {
    if (pattern.test(fileName) && categories.includes(category)) return category
  }
  return ''
}

export const ACTION_LABEL: Record<string, string> = {
  uploaded: 'Uploaded',
  new_version: 'New version',
  edited: 'Edited',
  moved: 'Moved',
  viewed: 'Viewed',
  downloaded: 'Downloaded',
  deleted: 'Moved to trash',
  restored: 'Restored from trash',
}
