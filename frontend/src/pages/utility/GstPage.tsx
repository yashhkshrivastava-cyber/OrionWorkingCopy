import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { DataTable, LoadingState } from '../../components/ui/DataTable'
import { Field, Select } from '../../components/ui/Field'
import { useDataRefresh } from '../../context/DataRefreshContext'
import { useLumen } from '../../lumen/useLumen'
import type { GstPosition } from '../../types'

function Tile({ label, value, hint, tone = '' }: { label: string; value: number; hint?: string; tone?: string }) {
  return <StatTile label={label} text={`₹ ${money(value)}`} hint={hint} tone={tone} />
}

/** A figure in a table: the amount with its commas, and a minus sign where the credit is more than the tax. */
/** Month by month, the tax on the bills (left bar) against the credit on the costs (right bar), with what was left to pay. Drawn only in Lumen, above the table that has the same figures. */
function MonthStrip({ months }: { months: GstPosition['months'] }) {
  const top = Math.max(1, ...months.flatMap((m) => [m.output - m.notes, m.credit]))
  return (
    <section className="panel !p-5" aria-label="GST by month">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-lg font-semibold">Month by month</h3>
        <p className="t-caption flex items-center gap-4 text-[color:var(--color-text-muted)]">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: 'var(--lumen-indigo)' }} /> GST on bills
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: 'var(--lumen-green)' }} /> Input tax credit
          </span>
        </p>
      </div>
      <ol className="grid grid-cols-6 gap-2 sm:grid-cols-12">
        {months.map((m) => (
          <li key={m.label} className={`flex flex-col items-center gap-1 ${m.future ? 'opacity-40' : ''}`} title={`${m.label}: tax ${money(m.output - m.notes)}, credit ${money(m.credit)}, net ${m.net < 0 ? '−' : ''}${money(Math.abs(m.net))}`}>
            <div className="flex h-28 w-full items-end justify-center gap-1">
              <span className="w-1/3 max-w-3 rounded-t-full" style={{ height: `${Math.max(2, ((m.output - m.notes) / top) * 100)}%`, background: 'var(--lumen-indigo)' }} />
              <span className="w-1/3 max-w-3 rounded-t-full" style={{ height: `${Math.max(2, (m.credit / top) * 100)}%`, background: 'var(--lumen-green)' }} />
            </div>
            <span className="text-[11px] font-semibold text-[color:var(--color-text-muted)]">{m.label.slice(0, 3)}</span>
            <span className={`rounded-full px-1.5 text-[10px] font-bold tabular-nums ${m.net > 0 ? 'bg-warning-dim text-warning' : m.net < 0 ? 'bg-positive-dim text-positive' : 'text-[color:var(--color-text-faint)]'}`}>{m.future || m.net === 0 ? '·' : `${m.net < 0 ? '−' : ''}${Math.abs(Math.round(m.net / 1000))}k`}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

const figure = (value: number) => (value === 0 ? '—' : `${value < 0 ? '−' : ''}${money(Math.abs(value))}`)

/**
 * The GST position by month: the tax on the bills, the input tax credit on the costs that carry the supplier's GSTIN and invoice number, and what is
 * left to pay. A planning view of what the books say; the return itself is filed on the GST portal.
 */
export function GstPage() {
  const { generation } = useDataRefresh()
  const [fy, setFy] = useState<number | undefined>(undefined)
  const [position, setPosition] = useState<GstPosition | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .gstPosition(fy)
      .then((found) => {
        setPosition(found)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
  }, [fy, generation])

  const rows = useMemo(
    () =>
      (position?.months ?? []).map((m) => ({
        month: m.label,
        gst_on_bills: figure(m.output),
        credit_notes: figure(m.notes),
        input_credit: figure(m.credit),
        net_payable: figure(m.net),
        running_net: m.future ? '' : figure(m.running_net),
        recorded_as_paid: figure(m.paid),
      })),
    [position],
  )
  const suppliers = useMemo(
    () => (position?.suppliers ?? []).map((s) => ({ supplier_gstin: s.gstin, expenses: s.expenses, input_credit: figure(s.credit) })),
    [position],
  )
  const totals = position?.totals
  const net = totals?.net ?? 0
  const lumen = useLumen()

  return (
    <section aria-label="GST" className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">GST position</h2>
          <p className="mt-0.5 max-w-3xl text-sm text-[color:var(--color-text-muted)]">
            The GST on the bills raised, less credit notes and the input tax credit on the costs, month by month. A cost counts as credit only when it has happened and carries
            the supplier&apos;s GSTIN and invoice number. This is for planning from the books; the return is filed on the GST portal.
          </p>
        </div>
        <Field label="Financial year" className="w-40">
          <Select value={position?.fy_start_year ?? ''} onChange={(e) => setFy(Number(e.target.value))} aria-label="Financial year">
            {(position?.years.length ? position.years : position ? [{ fy_start_year: position.fy_start_year, label: position.fy_label }] : []).map((y) => (
              <option key={y.fy_start_year} value={y.fy_start_year}>
                {y.label}
              </option>
            ))}
          </Select>
        </Field>
      </header>

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}

      {!position ? (
        <LoadingState />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile label="GST on bills" value={(totals?.output ?? 0) - (totals?.notes ?? 0)} hint={(totals?.notes ?? 0) > 0 ? `After ₹ ${money(totals?.notes ?? 0)} of credit notes` : 'CGST + SGST on issued bills'} />
            <Tile label="Input tax credit" value={totals?.credit ?? 0} tone="text-positive" hint="With supplier GSTIN and invoice" />
            <Tile
              label={net >= 0 ? 'Net GST to pay' : 'Credit carried forward'}
              value={Math.abs(net)}
              tone={net > 0 ? 'text-warning' : net < 0 ? 'text-positive' : ''}
              hint="GST on bills less credit"
            />
            <Tile label="Recorded as paid" value={totals?.paid ?? 0} hint="GST payments on bills" />
          </div>

          {position.without_gstin.count > 0 && (
            <Alert variant="warning">
              {position.without_gstin.count} {position.without_gstin.count === 1 ? 'cost carries' : 'costs carry'} ₹ {money(position.without_gstin.gst)} of GST but{' '}
              {position.without_gstin.count === 1 ? 'has' : 'have'} no supplier GSTIN or invoice number, so {position.without_gstin.count === 1 ? 'it is' : 'they are'} not counted as
              credit. Add them to the expense (Data &gt; Orion data &gt; Expense Transaction) to claim it.
            </Alert>
          )}

          {lumen && <MonthStrip months={position.months} />}

          <DataTable
            columns={['month', 'gst_on_bills', 'credit_notes', 'input_credit', 'net_payable', 'running_net', 'recorded_as_paid']}
            rows={rows}
            allColumns
            emptyMessage="No bills or costs with GST in this year."
          />
          <p className="text-xs text-[color:var(--color-text-muted)]">
            A minus in Net payable is a month where the credit was more than the tax: it carries forward, so Running net is what is still to pay since April.
            Recorded as paid is the GST payments entered on bills, by the day they were paid; GST paid net of credit is entered the same way.
          </p>

          {suppliers.length > 0 && (
            <div className="space-y-2">
              <h3 className="t-h3 text-[color:var(--color-text)]">Suppliers giving the most credit</h3>
              <DataTable columns={['supplier_gstin', 'expenses', 'input_credit']} rows={suppliers} allColumns />
            </div>
          )}
        </>
      )}
    </section>
  )
}
