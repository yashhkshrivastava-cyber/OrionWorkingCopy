import { useMemo, useState, type CSSProperties } from 'react'
import { ChevronRight, Search } from 'lucide-react'
import { inr } from '../dashboard/format'
import type { BillListRow } from '../../types'
import { formatDay, formatMonth } from './BillDocument'
import { BillNumber } from './BillNumber'

type Show = 'all' | 'owed' | 'gst' | 'settled' | 'cancelled'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const BATCH = 20

/** What is still to be received on a bill: what it was for, less what has been received and what credit notes took off. A cancelled bill is owed nothing. */
const owedOn = (bill: BillListRow) => (bill.status === 'Issued' ? Math.max(0, bill.grand_total - (bill.credited_amount ?? 0) - bill.received_total) : 0)
const gstState = (bill: BillListRow): 'paid' | 'part' | 'due' => (bill.gst_paid ? 'paid' : bill.gst_paid_amount > 0 ? 'part' : 'due')
/** EPFO and ESIC paid over: due when something charged is not all paid, part when some is paid. A bill that charged none has nothing to pay. */
const statutoryState = (bill: BillListRow): 'none' | 'paid' | 'part' | 'due' => {
  const charged = (bill.epf_amount ?? 0) + (bill.esic_amount ?? 0)
  const paid = (bill.epf_paid_amount ?? 0) + (bill.esic_paid_amount ?? 0)
  return charged <= 0 ? 'none' : paid >= charged - 0.004 ? 'paid' : paid > 0 ? 'part' : 'due'
}
const clientOf = (bill: BillListRow) => bill.client_name ?? bill.legacy_client_ledger ?? ''

function MonthLeaf({ month, hue }: { month: string; hue: string }) {
  const [year, mm] = month.split('-')
  return (
    <span style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="lumen-chip inline-flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-2xl leading-none" aria-hidden="true">
      <span className="text-[11px] font-bold uppercase tracking-wider">{MONTHS[Number(mm) - 1] ?? ''}</span>
      <span className="mt-1 font-display text-base font-semibold tabular-nums">{year?.slice(2)}</span>
    </span>
  )
}

/**
 * The bills register as cards you can scan: the month it is for, the number and the client, how much of it has come in as a bar, what is still to come, and the GST. A search and
 * one-tap questions (what is owed, whose GST is due, what is settled) sit above. It lists the same bills as the table and opens the same page.
 */
export function LumenBillList({ bills, onOpen }: { bills: BillListRow[]; onOpen: (id: string) => void }) {
  const [find, setFind] = useState('')
  const [show, setShow] = useState<Show>('all')
  const [shown, setShown] = useState(BATCH)

  const counts = useMemo(
    () => ({
      all: bills.length,
      owed: bills.filter((b) => owedOn(b) > 0).length,
      gst: bills.filter((b) => b.status === 'Issued' && gstState(b) !== 'paid').length,
      settled: bills.filter((b) => b.status === 'Issued' && owedOn(b) === 0).length,
      cancelled: bills.filter((b) => b.status === 'Cancelled').length,
    }),
    [bills],
  )

  const list = useMemo(() => {
    const needle = find.trim().toLowerCase()
    return bills
      .filter((b) => {
        if (show === 'owed' && owedOn(b) <= 0) return false
        if (show === 'gst' && !(b.status === 'Issued' && gstState(b) !== 'paid')) return false
        if (show === 'settled' && !(b.status === 'Issued' && owedOn(b) === 0)) return false
        if (show === 'cancelled' && b.status !== 'Cancelled') return false
        if (!needle) return true
        // "sep" or "september 2026" finds the bills for that month as well as the words in the other fields
        return [b.bill_number, b.case_name, clientOf(b), b.party_name, b.location, b.ref_no, formatMonth(b.service_month), b.service_month.slice(0, 7)].some((text) => (text ?? '').toLowerCase().includes(needle))
      })
      .sort((a, b) => b.fy_start_year - a.fy_start_year || b.bill_seq - a.bill_seq)
  }, [bills, find, show])

  const chips: { id: Show; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'owed', label: 'To receive' },
    { id: 'gst', label: 'GST to pay' },
    { id: 'settled', label: 'Settled' },
    { id: 'cancelled', label: 'Cancelled' },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
          <span className="sr-only">Search bills</span>
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input value={find} onChange={(e) => { setFind(e.target.value); setShown(BATCH) }} placeholder="Search bill no., case, client or month" className="h-11 w-full rounded-full pr-4 text-sm" style={{ paddingLeft: '2.75rem' }} />
        </label>
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              aria-pressed={show === chip.id}
              onClick={() => { setShow(chip.id); setShown(BATCH) }}
              className={`interactive rounded-full border px-3.5 py-1.5 text-sm font-semibold ${show === chip.id ? 'border-transparent text-on-primary [background-image:var(--orion-primary-fill)] shadow-card' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {chip.label} <span className="tabular-nums opacity-75">{counts[chip.id]}</span>
            </button>
          ))}
        </div>
      </div>

      {list.length === 0 ? (
        <p className="panel px-6 py-10 text-center text-sm text-[color:var(--color-text-muted)]">No bill matches that.</p>
      ) : (
        <ul className="space-y-2.5">
          {list.slice(0, shown).map((bill) => {
            const cancelled = bill.status === 'Cancelled'
            const owed = owedOn(bill)
            const worth = Math.max(0, bill.grand_total - (bill.credited_amount ?? 0))
            const share = worth > 0 ? Math.min(100, (bill.received_total / worth) * 100) : 0
            const gst = gstState(bill)
            const statutory = statutoryState(bill)
            return (
              <li key={bill.id}>
                <div
                  role="link"
                  tabIndex={0}
                  onClick={() => onOpen(bill.id)}
                  onKeyDown={(e) => e.key === 'Enter' && onOpen(bill.id)}
                  className={`panel interactive flex cursor-pointer flex-wrap items-center gap-x-5 gap-y-3 !p-4 focus-visible:ring-2 focus-visible:ring-accent ${cancelled ? 'opacity-70' : ''}`}
                >
                  <MonthLeaf month={bill.service_month} hue={cancelled ? 'slate' : owed === 0 ? 'green' : 'amber'} />
                  <div className="min-w-0 flex-1 basis-56">
                    <p className="flex flex-wrap items-center gap-2">
                      <BillNumber number={bill.bill_number} code={String(bill.id)} className={`font-display text-base font-semibold ${cancelled ? 'line-through' : ''}`} />
                      {cancelled && <span className="rounded-full bg-negative-dim px-2 py-0.5 text-[11px] font-bold text-negative">Cancelled</span>}
                      {!cancelled && gst !== 'paid' && <span className="rounded-full bg-warning-dim px-2 py-0.5 text-[11px] font-bold text-warning">{gst === 'part' ? 'GST part paid' : 'GST to pay'}</span>}
                      {!cancelled && (statutory === 'due' || statutory === 'part') && (
                        <span className="rounded-full bg-warning-dim px-2 py-0.5 text-[11px] font-bold text-warning">{statutory === 'part' ? 'EPFO / ESIC part paid' : 'EPFO / ESIC to pay'}</span>
                      )}
                      {bill.version_no > 1 && <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-bold text-[color:var(--color-text-muted)]">v{bill.version_no}</span>}
                    </p>
                    <p className="mt-0.5 truncate text-sm font-semibold">{clientOf(bill) || bill.party_name}</p>
                    <p className="t-caption truncate text-[color:var(--color-text-muted)]">
                      {[bill.case_name ?? 'Not tagged to a case', `for ${formatMonth(bill.service_month)}`, `raised ${formatDay(bill.bill_date)}`].join(' · ')}
                    </p>
                  </div>
                  {!cancelled && (
                    <div className="w-44 shrink-0">
                      <div className="h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${Math.round(share)}% received`}>
                        <span className="block h-full rounded-full transition-[width] duration-700" style={{ width: `${share}%`, background: `var(--lumen-${owed === 0 ? 'green' : 'teal'})` }} />
                      </div>
                      <p className="t-caption mt-1.5 tabular-nums text-[color:var(--color-text-muted)]">{inr(bill.received_total)} received</p>
                    </div>
                  )}
                  <div className="text-right">
                    <p className="font-display text-xl font-semibold tabular-nums">{inr(bill.grand_total)}</p>
                    <p className={`t-caption tabular-nums ${cancelled ? 'text-[color:var(--color-text-faint)]' : owed > 0 ? 'font-semibold text-warning' : 'text-positive'}`}>
                      {cancelled ? 'Nothing owed' : owed > 0 ? `${inr(owed)} to receive` : 'Settled'}
                    </p>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {list.length > shown && (
        <div className="flex justify-center">
          <button type="button" onClick={() => setShown((n) => n + BATCH)} className="interactive rounded-full border border-[color:var(--color-border)] px-5 py-2 text-sm font-semibold text-[color:var(--color-text-muted)] hover:bg-muted">
            Show {Math.min(BATCH, list.length - shown)} more ({list.length - shown} not shown yet)
          </button>
        </div>
      )}
    </div>
  )
}
