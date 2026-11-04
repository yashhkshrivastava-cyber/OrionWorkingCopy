import type { CSSProperties, ReactNode } from 'react'
import { ArrowDownLeft, ArrowUpRight, ListChecks, Undo2 } from 'lucide-react'
import { day, money } from '../../bank/format'
import { Button } from '../ui/Button'
import type { PayableBucket, PayableRow, PayrollMonth, PayrollRun } from '../../types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Later is hotter: the colour each ageing group is drawn in. */
const BUCKET_HUE: Record<PayableBucket, string> = { not_due: 'teal', '0-30': 'amber', '31-60': 'orange', '61-90': 'coral', '90+': 'coral' }

/** A day as a small calendar leaf: the number large, the month under it. */
function DateLeaf({ iso, hue }: { iso: string | null | undefined; hue: string }) {
  const [, month, date] = (iso ?? '').split('-')
  return (
    <span style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="lumen-chip inline-flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-2xl leading-none" aria-hidden="true">
      <span className="font-display text-xl font-semibold tabular-nums">{date ? Number(date) : '—'}</span>
      <span className="mt-1 text-[10px] font-bold uppercase tracking-wider">{month ? MONTHS[Number(month) - 1] : ''}</span>
    </span>
  )
}

/** How much of something is done, as a bar that fills. */
function Meter({ part, whole, hue = 'teal', label }: { part: number; whole: number; hue?: string; label: string }) {
  const share = whole > 0 ? Math.min(100, Math.max(0, (part / whole) * 100)) : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={`${label}: ${Math.round(share)}%`}>
      <span className="block h-full rounded-full transition-[width] duration-700" style={{ width: `${share}%`, background: `var(--lumen-${hue})` }} />
    </div>
  )
}

/**
 * One expense in the queue of what is owed: when it is due as a calendar leaf (tinted by how late it is), what it is, how much of it is paid as a bar, and
 * what is left with the two things to do about it. It carries what a row of the plain table carries and calls the same actions.
 */
export function PayableCard({ row, late, canWrite, onPay, onPayments }: { row: PayableRow; late: ReactNode; canWrite: boolean; onPay: () => void; onPayments: () => void }) {
  const hue = row.bucket ? BUCKET_HUE[row.bucket] : 'teal'
  return (
    <li className="panel flex flex-wrap items-center gap-x-5 gap-y-3 !p-4">
      <DateLeaf iso={row.pay_by} hue={row.left > 0 ? hue : 'green'} />
      <div className="min-w-0 flex-1 basis-56">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-display text-base font-semibold">{row.expense_type || 'Expense'}</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">{row.expense_code}</span>
          {row.payment_status && row.payment_status !== 'Unpaid' && <span className="rounded-full bg-accent-dim px-2 py-0.5 text-[11px] font-bold text-accent">{row.payment_status}</span>}
        </p>
        <p className="t-caption mt-0.5 truncate text-[color:var(--color-text-muted)]">{[row.case_name, row.description].filter(Boolean).join(' · ') || 'No case'}</p>
        <p className="mt-1 flex items-center gap-2 text-xs">
          <span className="tabular-nums text-[color:var(--color-text-muted)]">Pay by {day(row.pay_by)}</span>
          {late}
        </p>
      </div>
      <div className="w-44 shrink-0">
        <Meter part={row.paid} whole={row.total} hue={row.left > 0 ? hue : 'green'} label="Paid" />
        <p className="t-caption mt-1.5 tabular-nums text-[color:var(--color-text-muted)]">
          {money(row.paid)} of {money(row.total)}
        </p>
      </div>
      <div className="text-right">
        <p className="t-caption text-[color:var(--color-text-faint)]">Left</p>
        <p className="font-display text-xl font-semibold tabular-nums">{money(row.left)}</p>
      </div>
      <div className="flex items-center gap-2">
        {canWrite && row.left > 0 && (
          <Button size="sm" onClick={onPay}>
            Pay…
          </Button>
        )}
        <button type="button" onClick={onPayments} className="interactive inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-semibold text-[color:var(--color-text-muted)] hover:bg-muted">
          <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
          Payments
        </button>
      </div>
    </li>
  )
}

/** One month of salary: how much of it has gone out as a bar, what is still to pay, and the transfer to make. */
export function MonthCard({ month, label, canWrite, onPay }: { month: PayrollMonth; label: string; canWrite: boolean; onPay: () => void }) {
  const total = Number(month.total)
  const paid = Number(month.paid_total)
  const left = Number(month.unpaid_total)
  const settled = month.unpaid_lines === 0
  return (
    <li className="panel flex flex-wrap items-center gap-x-5 gap-y-3 !p-4">
      <span style={{ '--hue': `var(--lumen-${settled ? 'green' : 'amber'})` } as CSSProperties} className="lumen-chip inline-grid h-14 w-14 shrink-0 place-items-center rounded-2xl text-center text-[11px] font-bold uppercase leading-tight tracking-wide" aria-hidden="true">
        {label.split(' ').map((part) => (
          <span key={part} className="block">
            {part}
          </span>
        ))}
      </span>
      <div className="min-w-0 flex-1 basis-56">
        <p className="font-display text-base font-semibold">{label}</p>
        <p className="t-caption mt-0.5 text-[color:var(--color-text-muted)]">
          {month.lines} {month.lines === 1 ? 'line' : 'lines'} · {month.paid_lines} paid
          {month.unpaid_lines > 0 ? ` · ${month.unpaid_lines} to pay` : ''}
        </p>
      </div>
      <div className="w-48 shrink-0">
        <Meter part={paid} whole={total} hue={settled ? 'green' : 'amber'} label="Paid" />
        <p className="t-caption mt-1.5 tabular-nums text-[color:var(--color-text-muted)]">
          {money(paid)} of {money(total)}
        </p>
      </div>
      <div className="text-right">
        <p className="t-caption text-[color:var(--color-text-faint)]">Still to pay</p>
        <p className={`font-display text-xl font-semibold tabular-nums ${settled ? 'text-[color:var(--color-text-faint)]' : ''}`}>{money(left)}</p>
      </div>
      <div className="w-28 text-right">
        {canWrite && !settled && (
          <Button size="sm" onClick={onPay}>
            Mark paid…
          </Button>
        )}
      </div>
    </li>
  )
}

/** A pay run that has gone out (or been reversed, and kept): its day as a leaf, who and how much, and the way back. */
export function RunRow({ run, label, canWrite, onReverse }: { run: PayrollRun; label: string; canWrite: boolean; onReverse: () => void }) {
  return (
    <li className={`flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 ${run.reversed ? 'opacity-60' : ''}`}>
      <DateLeaf iso={run.paid_date} hue={run.reversed ? 'coral' : 'green'} />
      <div className="min-w-0 flex-1 basis-56">
        <p className={`font-semibold ${run.reversed ? 'line-through' : ''}`}>
          {label} · {run.lines} {run.lines === 1 ? 'employee' : 'employees'}
        </p>
        <p className="t-caption mt-0.5 text-[color:var(--color-text-muted)]">
          {[run.account_name, run.reference].filter(Boolean).join(' · ') || 'No reference'}
          {run.reversed && ` · Reversed ${day(run.reversed_timestamp)}: ${run.reversal_reason}`}
        </p>
      </div>
      <p className="font-display text-lg font-semibold tabular-nums">{money(Number(run.total))}</p>
      <div className="w-24 text-right">
        {canWrite && !run.reversed && (
          <button type="button" onClick={onReverse} className="interactive inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-xs font-semibold text-[color:var(--color-text-muted)] hover:bg-muted hover:text-negative">
            <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
            Reverse
          </button>
        )}
      </div>
    </li>
  )
}

/**
 * The reconciliation as a pair of scales: what the bank says on the left, what Orion's book says on the right, and between them the gap and whether it is
 * explained. The figures are the ones the plain list shows.
 */
export function BalanceScale({ statement, book, difference, clean }: { statement?: number | null; book?: number | null; difference?: number | null; clean: boolean }) {
  const side = (label: string, value: number | null | undefined, hue: string) => (
    <div style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="panel lumen-kpi relative flex-1 basis-52 overflow-hidden !p-5">
      <p className="t-caption relative font-semibold text-[color:var(--color-text-muted)]">{label}</p>
      <p className="lumen-figure relative mt-1 font-display font-semibold tabular-nums">{money(value)}</p>
    </div>
  )
  return (
    <div className="mt-4 flex flex-wrap items-stretch gap-3">
      {side('The bank says', statement, 'blue')}
      <div className="grid shrink-0 basis-full place-items-center sm:basis-auto">
        <span className={`rounded-full px-4 py-2 text-sm font-bold tabular-nums ${clean ? 'bg-positive-dim text-positive' : 'bg-warning-dim text-warning'}`}>{clean ? 'Agree' : `Gap ${money(Math.abs(difference ?? 0))}`}</span>
      </div>
      {side('Orion’s book says', book, 'teal')}
    </div>
  )
}

/** Which way the money went, as a small coloured arrow beside a statement line. */
export function DirectionTile({ direction }: { direction: 'in' | 'out' }) {
  const Icon = direction === 'in' ? ArrowDownLeft : ArrowUpRight
  return (
    <span style={{ '--hue': `var(--lumen-${direction === 'in' ? 'green' : 'coral'})` } as CSSProperties} className="lumen-chip inline-grid h-9 w-9 shrink-0 place-items-center rounded-xl" aria-hidden="true">
      <Icon className="h-[18px] w-[18px]" />
    </span>
  )
}
