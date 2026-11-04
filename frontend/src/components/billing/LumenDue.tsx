import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Copy, PartyPopper } from 'lucide-react'
import { inr } from '../dashboard/format'
import { Mark } from '../profile/parts'
import type { DueCase } from '../../types'
import { formatMonth } from './BillDocument'
import { BillNumber } from './BillNumber'

/** A month ("2026-09") a step earlier or later. */
function shift(month: string, by: number): string {
  const [year, number] = month.split('-').map(Number)
  const at = new Date(year, number - 1 + by, 1)
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}`
}

const thisMonth = () => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/**
 * The month's billing as a job to get through. The month sits in a stepper you click forward and back, the top says how far along it is (cases billed, cases still to bill, what the billed ones came to) with a
 * bar, and each case still to bill is a card with its last bill and the one button that matters: copy that bill into a new one. Nothing is issued from here.
 */
export function LumenDue({
  month,
  onMonth,
  cases,
  billed,
  canWrite,
  onCopy,
}: {
  month: string
  onMonth: (next: string) => void
  cases: DueCase[] | null
  billed: { cases: number; total: number } | null
  canWrite: boolean
  onCopy: (row: DueCase) => void
}) {
  const [onlyBehind, setOnlyBehind] = useState(false)
  const label = month ? formatMonth(`${month}-01`) : 'this month'
  const behind = useMemo(() => (cases ?? []).filter((c) => c.months_behind > 1), [cases])
  const shown = onlyBehind ? behind : (cases ?? [])
  const todo = cases?.length ?? 0
  const done = billed?.cases ?? 0
  const share = done + todo > 0 ? (done / (done + todo)) * 100 : 0
  const stillToCome = (cases ?? []).reduce((sum, c) => sum + c.grand_total, 0)

  const stepper = (
    <div className="inline-flex items-center gap-1 rounded-full border border-[color:var(--color-border)] bg-surface p-1 shadow-card" role="group" aria-label="Month to bill">
      <button type="button" onClick={() => month && onMonth(shift(month, -1))} aria-label="The month before" className="interactive grid h-9 w-9 place-items-center rounded-full text-[color:var(--color-text-muted)] hover:bg-muted">
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="font-display min-w-[9rem] px-2 text-center text-sm font-semibold">{label}</span>
      <button type="button" onClick={() => month && onMonth(shift(month, 1))} disabled={!month || month >= thisMonth()} aria-label="The month after" className="interactive grid h-9 w-9 place-items-center rounded-full text-[color:var(--color-text-muted)] hover:bg-muted disabled:opacity-40">
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="t-h2">Monthly billing</h2>
          <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">Cases billed before that have no bill yet for the month. Copy a case&apos;s last bill, change what moved this month, and issue it.</p>
        </div>
        {stepper}
      </div>

      <section aria-label="How far the month is" className="panel relative overflow-hidden !p-0 text-[color:var(--orion-on-primary)]" style={{ backgroundImage: cases !== null && todo === 0 ? 'linear-gradient(120deg, var(--lumen-green), var(--lumen-teal))' : 'var(--orion-highlight-fill)' }}>
        <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
        <div className="relative p-6 sm:p-8">
          {cases === null ? (
            <div className="shimmer h-24 rounded-2xl bg-white/20" aria-busy="true" />
          ) : todo === 0 ? (
            <>
              <p className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] opacity-90">
                <PartyPopper className="h-4 w-4" aria-hidden="true" /> All done
              </p>
              <h3 className="font-display mt-1 text-3xl font-semibold leading-tight sm:text-4xl">Everything is billed for {label}</h3>
              <p className="mt-1 text-sm opacity-90">
                {done} {done === 1 ? 'case has' : 'cases have'} a bill for the month{billed && billed.total > 0 ? `, ${inr(billed.total)} in all` : ''}.
              </p>
            </>
          ) : (
            <>
              <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-90">Still to bill for {label}</p>
              <h3 className="font-display mt-1 text-5xl font-semibold leading-none tabular-nums">
                {todo} <span className="text-2xl font-medium opacity-90">{todo === 1 ? 'case' : 'cases'}</span>
              </h3>
              <p className="mt-2 text-sm opacity-90">
                About {inr(stillToCome)} at what their last bills came to{behind.length ? `, ${behind.length} of them more than a month behind` : ''}.
              </p>
              <div className="mt-5 max-w-xl">
                <div className="h-2.5 overflow-hidden rounded-full bg-white/25" role="img" aria-label={`${done} of ${done + todo} cases billed`}>
                  <span className="block h-full rounded-full bg-white transition-[width] duration-700" style={{ width: `${share}%` }} />
                </div>
                <p className="mt-1.5 text-xs opacity-90">
                  {done} of {done + todo} billed{billed && billed.total > 0 ? ` · ${inr(billed.total)} so far` : ''}
                </p>
              </div>
            </>
          )}
        </div>
      </section>

      {cases !== null && todo > 0 && behind.length > 0 && (
        <div role="group" aria-label="Show" className="flex gap-2">
          {[
            [false, `All ${todo}`],
            [true, `Behind by over a month ${behind.length}`],
          ].map(([value, text]) => (
            <button
              key={String(value)}
              type="button"
              aria-pressed={onlyBehind === value}
              onClick={() => setOnlyBehind(Boolean(value))}
              className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${onlyBehind === value ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {text}
            </button>
          ))}
        </div>
      )}

      {cases !== null && shown.length > 0 && (
        <ul className="space-y-2.5" aria-label="Cases to bill">
          {shown.map((row) => (
            <li key={row.case_code} className="panel flex flex-wrap items-center gap-x-5 gap-y-3 !p-4">
              <Mark name={row.case_name} />
              <div className="min-w-0 flex-1 basis-56">
                <p className="font-display truncate text-base font-semibold">{row.case_name}</p>
                <p className="t-caption truncate text-[color:var(--color-text-muted)]">{[row.client_name, row.location && row.location !== row.case_name ? row.location : ''].filter(Boolean).join(' · ') || 'No client'}</p>
                <p className="t-caption mt-0.5 text-[color:var(--color-text-faint)]">
                  Last billed for {formatMonth(row.service_month)} · bill <BillNumber number={row.bill_number} code={String(row.id)} />
                </p>
              </div>
              <span className={`rounded-full px-3 py-1 text-xs font-bold ${row.months_behind > 1 ? 'bg-warning-dim text-warning' : 'bg-muted text-[color:var(--color-text-muted)]'}`}>
                {row.months_behind === 1 ? 'This month only' : `${row.months_behind} months behind`}
              </span>
              <div className="text-right">
                <p className="t-caption text-[color:var(--color-text-faint)]">Last bill</p>
                <p className="font-display text-xl font-semibold tabular-nums">{inr(row.grand_total)}</p>
              </div>
              {canWrite && (
                <button type="button" onClick={() => onCopy(row)} className="btn-primary interactive inline-flex h-10 items-center gap-2 rounded-full px-5 text-sm font-semibold">
                  <Copy className="h-4 w-4" aria-hidden="true" /> Copy last bill
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
