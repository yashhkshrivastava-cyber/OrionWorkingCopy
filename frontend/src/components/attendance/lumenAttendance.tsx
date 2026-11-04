import type { CSSProperties, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronRight, Minus, Pencil, Plus, Save, Send, X } from 'lucide-react'
import { monthName } from '../../attendance/attendanceCalc'
import { figure, type Row } from '../../attendance/attendanceDraft'
import { money } from '../../bank/format'
import { timeAgo } from '../../formatTime'
import type { AttendanceSheetSummary, AttendanceWorker } from '../../types'
import { Button } from '../ui/Button'
import { MoneyInput } from '../ui/MoneyInput'

/** Lumen's forms of Attendance: the same registers, people and figures, drawn so a supervisor can fill a month in without reading a spreadsheet. */

const fieldLabel = 't-caption mb-1 block font-semibold text-[color:var(--color-text-muted)]'
const box = 'w-full rounded-xl border border-[color:var(--color-border)] bg-surface px-3 py-2 text-sm tabular-nums focus:border-accent focus:outline-none focus:ring-2 focus:ring-[color:var(--orion-ring)] disabled:bg-muted disabled:opacity-70'

function Avatar({ name, hue }: { name: string; hue: string }) {
  return (
    <span style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="lumen-chip inline-grid h-11 w-11 shrink-0 place-items-center rounded-2xl text-base font-bold" aria-hidden="true">
      {name.trim()[0]?.toUpperCase() ?? '?'}
    </span>
  )
}

/** A month as a small calendar leaf. */
function MonthLeaf({ month, hue }: { month: string; hue: string }) {
  const [year, mm] = month.split('-')
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return (
    <span style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="lumen-chip inline-flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-2xl leading-none" aria-hidden="true">
      <span className="text-[11px] font-bold uppercase tracking-wider">{names[Number(mm) - 1] ?? ''}</span>
      <span className="mt-1 font-display text-base font-semibold tabular-nums">{year?.slice(2)}</span>
    </span>
  )
}

/** One register in the list: its month, the case, who is on it, what it comes to, and whether it has been posted. */
export function RegisterCard({ sheet, onOpen }: { sheet: AttendanceSheetSummary; onOpen: () => void }) {
  const posted = sheet.status === 'Posted'
  return (
    <li>
      <button type="button" onClick={onOpen} className="panel interactive flex w-full flex-wrap items-center gap-x-5 gap-y-2 !p-4 text-left focus-visible:ring-2 focus-visible:ring-accent">
        <MonthLeaf month={sheet.month_year} hue={posted ? 'green' : 'amber'} />
        <span className="min-w-0 flex-1 basis-52">
          <span className="font-display block truncate text-base font-semibold">{sheet.case_name}</span>
          <span className="t-caption block truncate text-[color:var(--color-text-muted)]">
            {sheet.client_name ? `${sheet.client_name} · ` : ''}
            {sheet.people} {sheet.people === 1 ? 'person' : 'people'} ({sheet.employees} employees, {sheet.workers} others)
          </span>
        </span>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${posted ? 'bg-positive-dim text-positive' : 'bg-warning-dim text-warning'}`}>{posted ? 'Posted' : 'Draft'}</span>
        <span className="text-right">
          <span className="font-display block text-xl font-semibold tabular-nums">{money(Number(sheet.amount))}</span>
          <span className="t-caption block text-[color:var(--color-text-faint)]">
            {sheet.sheet_code} · {timeAgo(sheet.posted_timestamp ?? sheet.last_updated_timestamp)}
          </span>
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
      </button>
    </li>
  )
}

/** A month's heading in the list, with what its registers come to. */
export function MonthHeading({ month, count, amount }: { month: string; count: number; amount: number }) {
  return (
    <h2 className="mb-2 mt-1 flex items-baseline justify-between gap-3 px-1">
      <span className="t-h3">{monthName(month)}</span>
      <span className="t-caption tabular-nums text-[color:var(--color-text-muted)]">
        {count} {count === 1 ? 'register' : 'registers'} · {money(amount)}
      </span>
    </h2>
  )
}

/** A saved person who is not an employee. */
export function WorkerCard({ person, canWrite, onChange }: { person: AttendanceWorker; canWrite: boolean; onChange: () => void }) {
  return (
    <li className="panel flex items-center gap-3 !p-4">
      <Avatar name={person.name} hue="teal" />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold">{person.name}</span>
          {person.status === 'Inactive' && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold text-[color:var(--color-text-muted)]">Inactive</span>}
        </p>
        <p className="t-caption truncate text-[color:var(--color-text-muted)]">
          {[person.designation, person.phone, person.case_name ? `usually at ${person.case_name}` : ''].filter(Boolean).join(' · ') || person.worker_code}
        </p>
        <p className="t-caption text-[color:var(--color-text-faint)]">
          {person.rate_per_day ? `${money(Number(person.rate_per_day))} a day` : 'No day rate'} · {person.registers} {person.registers === 1 ? 'register' : 'registers'}
        </p>
      </div>
      {canWrite && (
        <button type="button" onClick={onChange} aria-label={`Change ${person.name}`} className="interactive grid h-9 w-9 place-items-center rounded-full text-[color:var(--color-text-muted)] hover:bg-muted">
          <Pencil className="h-4 w-4" />
        </button>
      )}
    </li>
  )
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className={fieldLabel}>{label}</span>
      {children}
    </label>
  )
}

/**
 * One person on a register, as a card: whether they are counted, how many days (with + and - and a bar of the month), the pay for a day, an extra and a deduction,
 * and what that comes to in large figures. It edits the same row the plain table edits, with the same rules.
 */
export function PersonCard({
  row,
  editable,
  posted,
  monthDays,
  monthLabel,
  onChange,
  onRemove,
}: {
  row: Row
  editable: boolean
  posted: boolean
  monthDays: number
  monthLabel: string
  onChange: (patch: Partial<Row>) => void
  onRemove?: () => void
}) {
  const off = editable && !row.included
  const lock = !editable || off
  const days = Number(row.days_present) || 0
  const edited = row.amount_set && Number(row.amount) !== Number(figure(row))
  const over = days > monthDays && row.included
  const step = (by: number) => onChange({ days_present: String(Math.min(monthDays, Math.max(0, days + by))) })
  const share = monthDays > 0 ? Math.min(100, (days / monthDays) * 100) : 0
  return (
    <li className={`panel min-w-0 !p-4 ${off ? 'opacity-55' : ''}`}>
      <div className="flex flex-wrap items-start gap-3">
        {editable && (
          <button
            type="button"
            role="checkbox"
            aria-checked={row.included}
            aria-label={`Count ${row.name}`}
            onClick={() => onChange({ included: !row.included })}
            className={`interactive mt-2 grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 ${row.included ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)]' : 'border-[color:var(--color-border-strong)] text-transparent'}`}
          >
            <Check className="h-3.5 w-3.5" strokeWidth={3} />
          </button>
        )}
        <Avatar name={row.name} hue={row.employee_code ? 'indigo' : 'amber'} />
        <div className="min-w-0 flex-1 basis-32">
          <p className="truncate text-sm font-semibold">{row.name}</p>
          <p className="t-caption flex flex-wrap items-center gap-x-1.5 text-[color:var(--color-text-muted)]">
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${row.employee_code ? 'bg-accent-dim text-accent' : 'bg-warning-dim text-warning'}`}>
              {row.employee_code ? 'Employee' : row.new_worker ? 'New person' : 'Not an employee'}
            </span>
            {[row.employee_code ?? row.worker_code, row.designation].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="t-caption text-[color:var(--color-text-faint)]">Amount</p>
          <MoneyInput
            value={row.amount}
            words={false}
            disabled={lock}
            aria-label={`Amount for ${row.name}`}
            className="!w-28 rounded-xl border border-transparent bg-transparent px-1 py-0.5 text-right font-display text-xl font-semibold tabular-nums hover:border-[color:var(--color-border)] focus:border-accent"
            onChange={(v) => onChange({ amount: v, amount_set: true })}
          />
        </div>
        {editable && onRemove && (
          <button type="button" aria-label={`Remove ${row.name}`} onClick={onRemove} className="interactive grid h-8 w-8 shrink-0 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted hover:text-negative">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {row.warnings.map((w) => (
        <p key={w} className="t-caption mt-2 rounded-xl bg-warning-dim px-3 py-1.5 text-warning">
          {w}
        </p>
      ))}
      {over && <p className="t-caption mt-2 rounded-xl bg-negative-dim px-3 py-1.5 text-negative">More days than {monthLabel} has.</p>}

      <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,1fr))]">
        <Labelled label={`Days (of ${monthDays})`}>
          <span className="flex items-center gap-1.5">
            {!lock && (
              <button type="button" aria-label={`One day less for ${row.name}`} onClick={() => step(-1)} className="interactive grid h-9 w-9 shrink-0 place-items-center rounded-full border border-[color:var(--color-border)] hover:bg-muted">
                <Minus className="h-4 w-4" />
              </button>
            )}
            <input
              className={`${box} text-center`}
              type="number"
              inputMode="decimal"
              min={0}
              max={monthDays}
              step={0.5}
              disabled={lock}
              aria-label={`Days present for ${row.name}`}
              value={row.days_present}
              onChange={(e) => onChange({ days_present: e.target.value })}
            />
            {!lock && (
              <button type="button" aria-label={`One day more for ${row.name}`} onClick={() => step(1)} className="interactive grid h-9 w-9 shrink-0 place-items-center rounded-full border border-[color:var(--color-border)] hover:bg-muted">
                <Plus className="h-4 w-4" />
              </button>
            )}
          </span>
          <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${days} of ${monthDays} days`}>
            <span className="block h-full rounded-full transition-[width] duration-300" style={{ width: `${share}%`, background: over ? 'var(--lumen-coral)' : 'var(--lumen-teal)' }} />
          </span>
          {!lock && days !== monthDays && (
            <button type="button" onClick={() => onChange({ days_present: String(monthDays) })} className="mt-1 text-[11px] font-semibold text-accent hover:underline">
              Full month
            </button>
          )}
        </Labelled>
        <Labelled label="Pay for a day">
          <MoneyInput value={row.rate_per_day} decimals={4} words={false} disabled={lock} aria-label={`Pay for a day for ${row.name}`} className={`${box} text-right`} onChange={(v) => onChange({ rate_per_day: v })} />
        </Labelled>
        <Labelled label="Extra">
          <MoneyInput value={row.extra_amount} words={false} disabled={lock} aria-label={`Extra for ${row.name}`} className={`${box} text-right`} onChange={(v) => onChange({ extra_amount: v })} />
        </Labelled>
        <Labelled label="Deduction">
          <MoneyInput value={row.deduction_amount} words={false} disabled={lock} aria-label={`Deduction for ${row.name}`} className={`${box} text-right`} onChange={(v) => onChange({ deduction_amount: v })} />
        </Labelled>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <input
          className={`${box} min-w-[12rem] flex-1 text-left`}
          disabled={lock}
          maxLength={200}
          placeholder="A note (optional)"
          aria-label={`Remarks for ${row.name}`}
          value={row.remarks}
          onChange={(e) => onChange({ remarks: e.target.value })}
        />
        {edited && !lock && (
          <button type="button" className="text-xs font-semibold text-accent hover:underline" onClick={() => onChange({ amount_set: false })}>
            Typed, not worked out · use {money(Number(figure(row)))}
          </button>
        )}
        {posted && (row.salary_code || row.expense_code) && (
          <span className="t-caption text-[color:var(--color-text-muted)]">
            Entered as {row.salary_code ?? row.expense_code}
            {row.paid ? ' · paid' : ' · not paid yet'}
          </span>
        )}
      </div>
    </li>
  )
}

/** The foot of the screen while a register is being filled: what it comes to, and the two things to do with it. It is in the body, not the page, so it stays at the window's edge. */
export function SheetBar({
  people,
  total,
  note,
  saving,
  canSave,
  canPost,
  onSave,
  onPost,
}: {
  people: number
  total: number
  note: string
  saving: boolean
  canSave: boolean
  canPost: boolean
  onSave: () => void
  onPost: () => void
}) {
  return createPortal(
    <div role="region" aria-label="This register" className="pointer-events-none fixed inset-x-0 bottom-24 z-40 flex justify-center px-4 lg:bottom-5">
      <div className="panel pointer-events-auto flex max-w-full flex-wrap items-center gap-x-4 gap-y-2 !rounded-[1.75rem] !px-5 !py-3 shadow-raised">
        <div>
          <p className="t-caption text-[color:var(--color-text-muted)]">
            {people} {people === 1 ? 'person' : 'people'} · {note}
          </p>
          <p className="font-display text-xl font-semibold tabular-nums leading-tight">{money(total)}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={onSave} loading={saving} disabled={!canSave}>
            <Save className="h-4 w-4" /> {canSave ? 'Save draft' : 'Saved'}
          </Button>
          <Button onClick={onPost} disabled={!canPost || saving}>
            <Send className="h-4 w-4" /> Post…
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
