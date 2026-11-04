import { ExternalLink } from 'lucide-react'
import { money } from '../../billing/billCalc'
import type { BillCard } from '../../types'

/** What the card says about a bill, top to bottom: who and what, the figures, the money that has come in, and its history. */

const day = (iso: string | null | undefined): string => {
  if (!iso) return ''
  const when = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)
  return Number.isNaN(when.getTime()) ? '' : when.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}
const month = (iso: string | null | undefined): string => {
  if (!iso) return ''
  const when = new Date(`${iso.slice(0, 10)}T00:00:00`)
  return Number.isNaN(when.getTime()) ? '' : when.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })
}
const rupees = (value: number | null | undefined): string => `₹${money(Number(value ?? 0))}`

const TONE: Record<BillCard['payment_status'], string> = {
  Paid: 'bg-positive-dim text-positive',
  'Part paid': 'bg-warning-dim text-warning',
  Unpaid: 'bg-negative-dim text-negative',
  Settled: 'bg-positive-dim text-positive',
  Cancelled: 'bg-muted text-[color:var(--color-text-muted)]',
}

function Row({ label, children, strong = false }: { label: string; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? 'font-semibold text-[color:var(--color-text)]' : ''}`}>
      <dt className="shrink-0 text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className="min-w-0 text-right tabular-nums">{children}</dd>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-2.5 border-t border-[color:var(--color-border)] pt-2.5">
      <h4 className="eyebrow mb-1.5">{title}</h4>
      {children}
    </section>
  )
}

export function BillCardView({ card }: { card: BillCard }) {
  const f = card.figures
  const pay = card.payments
  const cancelled = card.status === 'Cancelled'
  const where = [card.case_name, card.location].filter(Boolean).join(' · ')
  const more = card.line_count - card.lines.length
  const edited = card.version_no > 1

  return (
    <div className="text-xs leading-relaxed text-[color:var(--color-text)]">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="t-label text-sm font-semibold">Bill {card.bill_number}</p>
          <p className="truncate text-[color:var(--color-text-muted)]">{card.client_name || card.party_name || 'No client'}</p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONE[card.payment_status]}`}>{card.payment_status}</span>
      </header>

      <dl className="mt-2 space-y-0.5">
        <Row label="Bill date">{day(card.bill_date)}</Row>
        {card.service_month && <Row label="For the month of">{month(card.service_month)}</Row>}
        {where && <Row label="Case">{where}</Row>}
        {card.ref_no && <Row label="Reference">{card.ref_no}{card.ref_date ? ` · ${day(card.ref_date)}` : ''}</Row>}
        {card.party_gstin && <Row label="Client GSTIN">{card.party_gstin}</Row>}
      </dl>
      {card.service_description && <p className="mt-1.5 line-clamp-2 text-[color:var(--color-text-muted)]">{card.service_description}</p>}

      {card.lines.length > 0 && (
        <Section title={`${card.line_count} ${card.line_count === 1 ? 'line' : 'lines'}`}>
          <ul className="space-y-0.5">
            {card.lines.map((line, at) => (
              <li key={at} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 truncate">
                  {line.particulars}
                  <span className="text-[color:var(--color-text-faint)]">
                    {' · '}
                    {line.days != null ? `${money(Number(line.rate ?? 0))} × ${Number(line.days)} days` : `${line.qty} × ${money(Number(line.rate ?? 0))}`}
                  </span>
                </span>
                <span className="shrink-0 tabular-nums">{money(Number(line.amount ?? 0))}</span>
              </li>
            ))}
          </ul>
          {more > 0 && <p className="mt-0.5 text-[color:var(--color-text-faint)]">and {more} more</p>}
        </Section>
      )}

      <Section title="Amount">
        <dl className="space-y-0.5">
          <Row label="Lines total">{money(f.lines_total)}</Row>
          {f.epf_amount > 0 && <Row label="EPF">{money(f.epf_amount)}</Row>}
          {f.esic_amount > 0 && <Row label="ESIC">{money(f.esic_amount)}</Row>}
          {f.service_amount > 0 && <Row label="Service charge">{money(f.service_amount)}</Row>}
          {f.extra_charges.map((charge, at) => (
            <Row key={at} label={charge.label}>{money(charge.amount)}</Row>
          ))}
          <Row label="Taxable value">{money(f.taxable_total)}</Row>
          {(f.cgst_amount > 0 || f.sgst_amount > 0) && (
            <>
              <Row label="CGST">{money(f.cgst_amount)}</Row>
              <Row label="SGST">{money(f.sgst_amount)}</Row>
            </>
          )}
          {f.round_off !== 0 && <Row label="Round off">{money(f.round_off)}</Row>}
          <Row label="Grand total" strong>{rupees(f.grand_total)}</Row>
        </dl>
      </Section>

      {!cancelled && (
        <Section title="Payment">
          <dl className="space-y-0.5">
            <Row label="Received">{rupees(pay.received)}</Row>
            <Row label="Still to receive" strong={pay.remaining > 0}>
              {rupees(pay.remaining)}
            </Row>
            {card.age_days !== null && <Row label="Outstanding for">{card.age_days} {card.age_days === 1 ? 'day' : 'days'}</Row>}
            {card.gst.status && card.gst.total && card.gst.total.due > 0 && (
              <>
                <Row label="GST paid to the government">
                  {card.gst.status}
                  {card.gst.status !== 'Not paid' ? ` · ${rupees(card.gst.total.paid)} of ${rupees(card.gst.total.due)}` : ''}
                </Row>
                {card.gst.status === 'Part paid' && card.gst.cgst && card.gst.sgst && (
                  <Row label="Still to pay">
                    {card.gst.cgst.remaining > 0 ? `CGST ${rupees(card.gst.cgst.remaining)}` : ''}
                    {card.gst.cgst.remaining > 0 && card.gst.sgst.remaining > 0 ? ' · ' : ''}
                    {card.gst.sgst.remaining > 0 ? `SGST ${rupees(card.gst.sgst.remaining)}` : ''}
                  </Row>
                )}
                {card.gst.last_paid_date && <Row label="Last GST payment">{day(card.gst.last_paid_date)}</Row>}
              </>
            )}
            {card.statutory?.status && card.statutory.total && card.statutory.total.due > 0 && (
              <>
                <Row label="EPFO and ESIC paid">
                  {card.statutory.status}
                  {card.statutory.status !== 'Not paid' ? ` · ${rupees(card.statutory.total.paid)} of ${rupees(card.statutory.total.due)}` : ''}
                </Row>
                {card.statutory.status === 'Part paid' && card.statutory.epfo && card.statutory.esic && (
                  <Row label="Still to pay">
                    {card.statutory.epfo.remaining > 0 ? `EPFO ${rupees(card.statutory.epfo.remaining)}` : ''}
                    {card.statutory.epfo.remaining > 0 && card.statutory.esic.remaining > 0 ? ' · ' : ''}
                    {card.statutory.esic.remaining > 0 ? `ESIC ${rupees(card.statutory.esic.remaining)}` : ''}
                  </Row>
                )}
              </>
            )}
          </dl>
          {pay.recent.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-[color:var(--color-text-muted)]">
              {pay.recent.map((entry, at) => (
                <li key={at} className="flex justify-between gap-3">
                  <span>Received {day(entry.received_date)}</span>
                  <span className="tabular-nums">{rupees(entry.amount)}</span>
                </li>
              ))}
              {pay.count > pay.recent.length && <li className="text-[color:var(--color-text-faint)]">and {pay.count - pay.recent.length} earlier</li>}
            </ul>
          )}
        </Section>
      )}

      {cancelled && (
        <Section title="Cancelled">
          <p className="text-[color:var(--color-text-muted)]">
            {day(card.cancelled_timestamp)}
            {card.cancelled_reason ? `: ${card.cancelled_reason}` : ''}
          </p>
        </Section>
      )}

      <Section title="History">
        <p className="text-[color:var(--color-text-muted)]">
          Made {day(card.created_timestamp)}
          {card.created_by_name ? ` by ${card.created_by_name}` : ''}.
          {edited && ` Version ${card.version_no}, last changed ${day(card.version_timestamp)}${card.version_by_name ? ` by ${card.version_by_name}` : ''}${card.version_reason ? `: ${card.version_reason}` : ''}.`}
        </p>
      </Section>

      <p className="mt-2.5 flex items-center gap-1 font-medium text-accent">
        <ExternalLink className="h-3 w-3" aria-hidden="true" />
        Click to open this bill in a new tab
      </p>
    </div>
  )
}
