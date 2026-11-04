import type { CSSProperties } from 'react'
import { Award, ChevronRight, File, FileText, FileUp, Receipt, type LucideIcon } from 'lucide-react'
import { IconTile } from '../../lumen/IconTile'
import type { LetterSummary } from '../../types'
import { formatDay } from '../billing/BillDocument'

const BY_TEMPLATE: Record<string, [LucideIcon, string]> = {
  letter: [FileText, 'indigo'],
  quotation: [Receipt, 'amber'],
  certificate: [Award, 'green'],
  blank: [File, 'slate'],
}

/** A big door to one thing to write: what it is, in a line, and a coloured mark so the four are told apart at a glance. */
export function StartCard({ id, label, hint, onClick }: { id: string; label: string; hint: string; onClick: () => void }) {
  const [Icon, hue] = BY_TEMPLATE[id] ?? [FileText, 'indigo']
  return (
    <button type="button" onClick={onClick} style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="panel lumen-kpi interactive relative flex flex-col items-start gap-3 overflow-hidden !p-5 text-left focus-visible:ring-2 focus-visible:ring-accent">
      <IconTile icon={Icon} hue={hue} className="h-10 w-10" />
      <span className="relative">
        <span className="font-display block text-lg font-semibold">{label}</span>
        <span className="t-caption block text-[color:var(--color-text-muted)]">{hint}</span>
      </span>
    </button>
  )
}

/** The way into the other thing the letterhead does: putting a PDF made elsewhere onto it. */
export function PdfCard({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{ '--hue': 'var(--lumen-teal)' } as CSSProperties} className="panel lumen-kpi interactive relative flex flex-col items-start gap-3 overflow-hidden !p-5 text-left focus-visible:ring-2 focus-visible:ring-accent">
      <IconTile icon={FileUp} hue="teal" className="h-10 w-10" />
      <span className="relative">
        <span className="font-display block text-lg font-semibold">Put a PDF on the letterhead</span>
        <span className="t-caption block text-[color:var(--color-text-muted)]">Already written elsewhere? Stamp the header and footer on it.</span>
      </span>
    </button>
  )
}

/** One saved letter: its date as a leaf, its name and reference, how it begins, and who changed it last. */
export function LetterCard({ letter, onOpen }: { letter: LetterSummary; onOpen: () => void }) {
  const [, month, date] = letter.letter_date.split('-')
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return (
    <li>
      <button type="button" onClick={onOpen} className="panel interactive flex w-full items-center gap-4 !p-4 text-left focus-visible:ring-2 focus-visible:ring-accent">
        <span style={{ '--hue': 'var(--lumen-indigo)' } as CSSProperties} className="lumen-chip inline-flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-2xl leading-none" aria-hidden="true">
          <span className="font-display text-xl font-semibold tabular-nums">{Number(date) || '—'}</span>
          <span className="mt-1 text-[10px] font-bold uppercase tracking-wider">{names[Number(month) - 1] ?? ''}</span>
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-display truncate text-base font-semibold">{letter.title}</span>
            {letter.ref_no && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold text-[color:var(--color-text-muted)]">{letter.ref_no}</span>}
          </span>
          <span className="t-caption block truncate text-[color:var(--color-text-muted)]">{letter.preview || 'Empty letter'}</span>
          <span className="t-caption block text-[color:var(--color-text-faint)]">
            Changed {formatDay(letter.last_updated_timestamp)}
            {letter.last_updated_by_name ?? letter.created_by_name ? ` by ${letter.last_updated_by_name ?? letter.created_by_name}` : ''}
          </span>
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
      </button>
    </li>
  )
}
