/**
 * The parts of a printed bill that one bill can leave off. The keys are the ones in `HIDEABLE` in
 * backend/app/billing.py (a test compares them), and BillDocument.tsx and billing_pdf.py both honour them.
 * A bill stores the keys it hides; everything else prints.
 */

import type { LineSetup, SummaryLabelKey } from '../types'

export type LayoutPart = { key: string; label: string }

export const LAYOUT_GROUPS: { title: string; parts: LayoutPart[] }[] = [
  {
    title: 'Our details',
    parts: [
      { key: 'address', label: 'Address' },
      { key: 'phone', label: 'Contact numbers' },
      { key: 'gstin', label: 'GSTIN' },
      { key: 'pan', label: 'PAN' },
      { key: 'pf_no', label: 'PF No.' },
      { key: 'esi_no', label: 'ESI No.' },
      { key: 'reg_no', label: 'Reg. No.' },
    ],
  },
  {
    title: 'Billed to',
    parts: [
      { key: 'party_address', label: 'Client address' },
      { key: 'party_state', label: 'Client state' },
      { key: 'party_gstin', label: 'Client GSTIN' },
    ],
  },
  {
    title: 'Invoice details',
    parts: [
      { key: 'for_month', label: 'For the month' },
      { key: 'ref', label: 'Your ref.' },
      { key: 'tender_id', label: 'Tender ID' },
      { key: 'tender_date', label: 'Tender start date' },
    ],
  },
  {
    title: 'Service',
    parts: [
      { key: 'location', label: 'Location' },
      { key: 'service_description', label: 'Service description' },
    ],
  },
  { title: 'Lines', parts: [{ key: 'qty_rate', label: 'Quantity and rate columns' }] },
  {
    title: 'Totals',
    parts: [
      { key: 'amount_in_words', label: 'Amount in words' },
      { key: 'lines_total', label: 'Total of lines' },
      { key: 'sub_total', label: 'Sub total' },
      { key: 'taxable_total', label: 'Taxable value' },
      { key: 'round_off', label: 'Round off' },
    ],
  },
  {
    title: 'Footer',
    parts: [
      { key: 'bank', label: 'Bank details' },
      { key: 'terms', label: 'Terms' },
      { key: 'signatory', label: 'Company signature and title' },
      { key: 'customer_signature', label: "Customer's signature" },
    ],
  },
]

export const LAYOUT_KEYS: string[] = LAYOUT_GROUPS.flatMap((group) => group.parts.map((part) => part.key))

export const UNIT_SETUP: LineSetup = {
  basis: 'unit',
  qty_multiplies: true,
  month_days: null,
  totals_row: false,
  charge_by_line: false,
  service_on: 'lines',
  labels: {},
  columns: [],
}

/** The names of the rows of the totals when the bill has not named them (the same as in billing_pdf.total_lines). */
export const SUMMARY_LABELS: Record<SummaryLabelKey, string> = {
  lines_total: 'Total of lines',
  sub_total: 'Sub total',
  taxable_total: 'Taxable value',
  epf: 'EPFO',
  esic: 'ESIC',
  service: 'Service charges',
}

export type LineColumnId = 'particulars' | 'qty' | 'rate' | 'days' | 'amount' | `field:${string}`

/** The names the lines' columns have when the bill has not named them. */
export function standardLabel(key: Exclude<LineColumnId, `field:${string}`>, basis: LineSetup['basis']): string {
  if (key === 'rate') return basis === 'daily' ? 'Rate per day' : basis === 'monthly' ? 'Rate per month' : 'Rate'
  return { particulars: 'Particulars', qty: 'Qty', days: 'Days', amount: 'Amount' }[key]
}

/**
 * The columns of the lines table after the running number, left to right: the particulars, the bill's own columns, then quantity,
 * rate, days (a day-based bill only) and amount. The quantity, rate and days go when the bill hides `qty_rate`.
 * The same as line_columns() in backend/app/billing_pdf.py.
 */
export function lineColumns(bill: { hidden?: string[]; line_setup?: LineSetup }): { id: LineColumnId; label: string }[] {
  const setup: LineSetup = { ...UNIT_SETUP, ...bill.line_setup } // a bill saved before this has {}
  const name = (key: Exclude<LineColumnId, `field:${string}`>) => setup.labels[key] || standardLabel(key, setup.basis)
  const columns: { id: LineColumnId; label: string }[] = [{ id: 'particulars', label: name('particulars') }]
  for (const column of setup.columns) columns.push({ id: `field:${column.key}`, label: column.label })
  if (!(bill.hidden ?? []).includes('qty_rate')) {
    columns.push({ id: 'qty', label: name('qty') }, { id: 'rate', label: name('rate') })
    if (setup.basis !== 'unit') columns.push({ id: 'days', label: name('days') })
  }
  columns.push({ id: 'amount', label: name('amount') })
  return columns
}
