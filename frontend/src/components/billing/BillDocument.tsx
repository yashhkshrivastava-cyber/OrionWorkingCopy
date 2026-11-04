import { money } from '../../billing/billCalc'
import { DEFAULT_FONT, fontCss, fontPx } from '../../billing/billFonts'
import { SUMMARY_LABELS, lineColumns } from '../../billing/billLayout'
import { rupeesInWords } from '../../billing/rupeeWords'
import type { BillView } from '../../types'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return ''
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  if (!year) return ''
  return `${String(day).padStart(2, '0')} ${MONTHS[month - 1].slice(0, 3)} ${year}`
}

export function formatMonth(iso: string | null | undefined): string {
  if (!iso) return ''
  const [year, month] = iso.slice(0, 7).split('-').map(Number)
  return year ? `${MONTHS[month - 1]} ${year}` : ''
}

const trim = (value: number) => String(Number(value.toFixed(2)))

/** A quantity or a number of days as printed: no trailing zeros. */
const plain = (value: number | string | null | undefined) => (value === null || value === undefined || value === '' ? '' : String(Number(Number(value).toFixed(3))))

/** The sum of one column of the lines, for the row under them. */
const sumOf = (values: (number | string | null | undefined)[]) =>
  plain(values.reduce<number>((total, value) => total + (value === null || value === undefined || value === '' ? 0 : Number(value)), 0))

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.667em_1fr] gap-2 py-[3px]">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-900">{children}</dd>
    </div>
  )
}

/**
 * The tax invoice. It is always drawn on white in fixed colours, so a bill looks and
 * prints the same whichever theme the app is in. The letterhead (company details, bank,
 * terms) comes from the profile saved with the bill. The typeface and size are the bill's (billFonts.ts); every size in the bill is in em, so
 * choosing a larger base size scales the whole page, columns and headings included.
 */
export function BillDocument({ bill }: { bill: BillView }) {
  const p = bill.profile
  const rates = bill.rates
  const draft = bill.status === 'Draft'
  const font = bill.font ?? DEFAULT_FONT
  // Parts this bill leaves off (billLayout.ts). A bill saved before the setting existed shows everything.
  const off = new Set(bill.hidden ?? [])
  const show = (key: string) => !off.has(key)
  const columns = lineColumns(bill)
  const setup = bill.line_setup
  const figures = new Set(['qty', 'rate', 'days', 'amount'])
  const widths: Record<string, string> = { qty: 'w-[6.4em]', rate: 'w-[9.6em]', days: 'w-[6.4em]', amount: 'w-[11.2em]' }

  // The same rows as total_lines() in backend/app/billing_pdf.py. A charge at 0% is left off unless its amount was entered by hand.
  const names = { ...SUMMARY_LABELS, ...setup?.labels }
  const entered = bill.manual_figures ?? {}
  const charge = (label: string, rate: number, amount: number, key: keyof typeof entered) =>
    rate > 0 || key in entered ? [{ label: rate > 0 ? `${label} @ ${trim(rate)}%` : label, value: amount }] : []
  const totals: { label: string; value: number; strong?: boolean }[] = [
    ...(show('lines_total') ? [{ label: names.lines_total || SUMMARY_LABELS.lines_total, value: bill.lines_total }] : []),
    ...charge(names.epf || SUMMARY_LABELS.epf, rates.epf_pct, bill.epf_amount, 'epf_amount'),
    ...charge(names.esic || SUMMARY_LABELS.esic, rates.esic_pct, bill.esic_amount, 'esic_amount'),
    ...((rates.epf_pct > 0 || rates.esic_pct > 0 || 'epf_amount' in entered || 'esic_amount' in entered) && show('sub_total')
      ? [{ label: names.sub_total || SUMMARY_LABELS.sub_total, value: bill.sub_total }]
      : []),
    ...charge(names.service || SUMMARY_LABELS.service, rates.service_pct, bill.service_amount, 'service_amount'),
    ...(bill.extra_charges ?? [])
      .filter((charge) => charge.amount !== 0)
      .map((charge) => ({ label: charge.kind === 'pct' ? `${charge.label} @ ${trim(charge.value)}%` : charge.label, value: charge.amount })),
    ...(show('taxable_total') ? [{ label: names.taxable_total || SUMMARY_LABELS.taxable_total, value: bill.taxable_total, strong: true }] : []),
    ...charge('CGST', rates.cgst_pct, bill.cgst_amount, 'cgst_amount'),
    ...charge('SGST', rates.sgst_pct, bill.sgst_amount, 'sgst_amount'),
    ...(Math.abs(bill.round_off) >= 0.005 && show('round_off') ? [{ label: 'Round off', value: bill.round_off }] : []),
  ]

  return (
    <article
      className="bill-sheet relative mx-auto w-full max-w-[210mm] bg-white px-[11mm] py-[10mm] leading-snug text-slate-900 shadow-[0_8px_30px_rgba(15,23,42,0.12)] print:max-w-none print:shadow-none"
      style={{ fontFamily: fontCss(font.family), fontSize: `${fontPx(font.size)}px` }}
    >
      {bill.status === 'Cancelled' && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden"
        >
          <span className="-rotate-[28deg] select-none text-[110px] font-black tracking-widest text-red-600/15">
            CANCELLED
          </span>
        </div>
      )}

      <header>
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="text-[1.75em] font-extrabold uppercase leading-tight tracking-tight text-[#0f2f57]">
              {p.company_name}
            </h1>
            {p.address && show('address') && <p className="mt-1 text-[0.9167em] text-slate-600">{p.address}</p>}
            {p.phone && show('phone') && <p className="text-[0.9167em] text-slate-600">Contact: {p.phone}</p>}
          </div>
          <div className="shrink-0 text-right">
            <p className="inline-block rounded bg-[#0f2f57] px-3 py-1.5 text-[0.9167em] font-bold uppercase tracking-[0.2em] text-white">
              Tax Invoice
            </p>
            {draft && <p className="mt-1.5 text-[0.8333em] font-semibold uppercase tracking-wider text-amber-600">Preview</p>}
          </div>
        </div>

        {(() => {
          const ids = [
            ['gstin', 'GSTIN', p.gstin],
            ['pan', 'PAN', p.pan],
            ['pf_no', 'PF No.', p.pf_no],
            ['esi_no', 'ESI No.', p.esi_no],
            ['reg_no', 'Reg. No.', p.reg_no],
          ].filter(([key, , value]) => value && show(key))
          // This bill's own details come after the standard ones.
          for (const field of bill.header_fields ?? []) ids.push([`field:${field.label}`, field.label, field.value])
          return ids.length ? (
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 border-y border-slate-200 py-2 text-[0.875em] sm:grid-cols-3 print:grid-cols-5">
              {ids.map(([key, label, value]) => (
                <div key={key}>
                  <dt className="text-[0.75em] font-semibold uppercase tracking-wider text-slate-500">{label}</dt>
                  <dd className="font-medium text-slate-900">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null
        })()}
      </header>

      <section className="mt-5 grid gap-6 sm:grid-cols-[1.5fr_1fr] print:grid-cols-[1.5fr_1fr]">
        <div>
          <p className="text-[0.75em] font-semibold uppercase tracking-wider text-slate-500">Billed to</p>
          <p className="mt-1 text-[1.1667em] font-bold leading-snug text-slate-900">{bill.party_name || '—'}</p>
          {bill.party_address && show('party_address') && <p className="mt-0.5 text-slate-600">{bill.party_address}</p>}
          {bill.party_state && show('party_state') && <p className="text-slate-600">{bill.party_state}</p>}
          {bill.party_gstin && show('party_gstin') && (
            <p className="mt-1 text-slate-700">
              GSTIN <span className="font-semibold tracking-wide">{bill.party_gstin}</span>
            </p>
          )}
          {(bill.party_fields ?? []).map((field) => (
            <p key={field.label} className="text-slate-700">
              {field.label} <span className="font-semibold">{field.value}</span>
            </p>
          ))}
        </div>
        <dl className="rounded-md bg-slate-50 px-3 py-2 print:bg-slate-50">
          <Meta label="Invoice no.">
            {bill.number ? (
              <span className="text-[1.0833em] font-bold text-[#0f2f57]">{bill.number}</span>
            ) : (
              <span className="text-slate-400">Assigned on save</span>
            )}
          </Meta>
          <Meta label="Invoice date">{formatDay(bill.bill_date) || '—'}</Meta>
          {show('for_month') && <Meta label="For the month">{formatMonth(bill.service_month) || '—'}</Meta>}
          {(bill.ref_no || bill.ref_date) && show('ref') && (
            <Meta label="Your ref.">
              {bill.ref_no}
              {bill.ref_date && <span className="block text-[0.875em] font-normal text-slate-600">dated {formatDay(bill.ref_date)}</span>}
            </Meta>
          )}
          {bill.tender_id && show('tender_id') && <Meta label="Tender ID">{bill.tender_id}</Meta>}
          {bill.tender_start_date && show('tender_date') && <Meta label="Tender start">{formatDay(bill.tender_start_date)}</Meta>}
        </dl>
      </section>

      {((bill.location && show('location')) || (bill.service_description && show('service_description'))) && (
        <section className="mt-5 rounded-md border border-slate-200 px-3 py-2">
          {bill.location && show('location') && (
            <p>
              <span className="text-slate-500">Location </span>
              <span className="font-semibold">{bill.location}</span>
            </p>
          )}
          {bill.service_description && show('service_description') && (
            <p className="mt-0.5 text-slate-700">
              {formatMonth(bill.service_month)} <span className="text-slate-400">·</span> {bill.service_description}
            </p>
          )}
        </section>
      )}

      <table className="mt-4 w-full border-collapse text-[1em]">
        <thead>
          <tr className="bg-[#0f2f57] text-white print:bg-[#0f2f57]">
            <th className="w-[3.2em] px-2 py-1.5 text-left text-[0.8333em] font-semibold uppercase tracking-wider">No.</th>
            {columns.map((column) => (
              <th
                key={column.id}
                className={`px-2 py-1.5 text-[0.8333em] font-semibold uppercase tracking-wider ${figures.has(column.id) ? `${widths[column.id]} text-right` : 'text-left'}`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {bill.lines.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1} className="border-b border-slate-200 px-2 py-6 text-center text-slate-400">
                Lines you add appear here.
              </td>
            </tr>
          )}
          {bill.lines.map((line, index) => (
            <tr key={index} className="border-b border-slate-200 align-top">
              <td className="px-2 py-2 text-slate-500">{index + 1}</td>
              {columns.map((column) => {
                if (column.id === 'particulars') return <td key={column.id} className="px-2 py-2 font-medium">{line.particulars}</td>
                if (column.id.startsWith('field:')) return <td key={column.id} className="px-2 py-2">{line.fields?.[column.id.slice(6)] ?? ''}</td>
                if (column.id === 'qty') return <td key={column.id} className="px-2 py-2 text-right tabular-nums">{plain(line.qty)}</td>
                if (column.id === 'rate') return <td key={column.id} className="px-2 py-2 text-right tabular-nums">{line.rate === null ? '' : money(line.rate)}</td>
                if (column.id === 'days') return <td key={column.id} className="px-2 py-2 text-right tabular-nums">{plain(line.days)}</td>
                return <td key={column.id} className="px-2 py-2 text-right font-medium tabular-nums">{money(line.amount)}</td>
              })}
            </tr>
          ))}
          {setup?.totals_row && bill.lines.length > 0 && (
            <tr className="border-t-2 border-slate-800 bg-slate-50 font-semibold print:bg-slate-50">
              <td className="px-2 py-2" />
              {columns.map((column) => (
                <td key={column.id} className={`px-2 py-2 ${figures.has(column.id) ? 'text-right tabular-nums' : ''}`}>
                  {column.id === 'particulars'
                    ? 'Total'
                    : column.id === 'qty'
                      ? sumOf(bill.lines.map((line) => line.qty))
                      : column.id === 'days'
                        ? sumOf(bill.lines.map((line) => line.days))
                        : column.id === 'amount'
                          ? money(bill.lines.reduce((total, line) => total + line.amount, 0))
                          : ''}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>

      <div className="mt-3 grid gap-4 sm:grid-cols-[1fr_22.667em] print:grid-cols-[1fr_22.667em]" style={{ breakInside: 'avoid' }}>
        <div>
          {show('amount_in_words') && (
            <>
              <p className="text-[0.75em] font-semibold uppercase tracking-wider text-slate-500">Amount in words</p>
              <p className="mt-1 font-semibold leading-snug text-slate-900">{rupeesInWords(bill.grand_total)}</p>
            </>
          )}
        </div>
        <dl>
          {totals.map((row) => (
            <div
              key={row.label}
              className={`flex justify-between gap-4 border-b border-slate-100 py-1 ${row.strong ? 'font-semibold' : 'text-slate-700'}`}
            >
              <dt>{row.label}</dt>
              <dd className="tabular-nums">{row.value < 0 ? '−' : ''}{money(Math.abs(row.value))}</dd>
            </div>
          ))}
          <div className="mt-1 flex items-baseline justify-between gap-4 rounded bg-[#0f2f57] px-3 py-2 text-white print:bg-[#0f2f57]">
            <dt className="text-[0.8333em] font-semibold uppercase tracking-wider">Grand total</dt>
            <dd className="text-[1.3333em] font-extrabold tabular-nums">₹ {money(bill.grand_total)}</dd>
          </div>
        </dl>
      </div>

      <footer className="mt-8 grid gap-6 border-t border-slate-200 pt-4 sm:grid-cols-2 print:grid-cols-2" style={{ breakInside: 'avoid' }}>
        <div className="space-y-3 text-[0.875em]">
          {(p.bank_name || p.bank_account) && show('bank') && (
            <div>
              <p className="text-[0.75em] font-semibold uppercase tracking-wider text-slate-500">Bank details</p>
              <p className="mt-0.5 font-medium">{p.bank_name}</p>
              {p.bank_account && <p>A/c No. <span className="font-medium">{p.bank_account}</span></p>}
              {p.bank_ifsc && <p>IFSC <span className="font-medium">{p.bank_ifsc}</span></p>}
            </div>
          )}
          {p.terms.length > 0 && show('terms') && (
            <div>
              <p className="text-[0.75em] font-semibold uppercase tracking-wider text-slate-500">Terms</p>
              <ol className="mt-0.5 list-decimal space-y-0.5 pl-4 text-slate-600">
                {p.terms.map((term) => (
                  <li key={term}>{term}</li>
                ))}
              </ol>
            </div>
          )}
        </div>
        <div className="flex flex-col justify-between text-[0.875em]">
          <p className="text-right font-semibold text-slate-800">{show('signatory') ? p.signatory : ''}</p>
          <div className="mt-14 flex justify-between gap-6 text-slate-600">
            {show('customer_signature') && <p className="border-t border-slate-300 pt-1">Customer&apos;s signature</p>}
            {show('signatory') && <p className="ml-auto border-t border-slate-300 pt-1 text-right">{p.signatory_title}</p>}
          </div>
        </div>
      </footer>
    </article>
  )
}
