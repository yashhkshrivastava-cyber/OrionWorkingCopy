import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { formatDay } from '../../components/billing/BillDocument'
import { StatTile } from '../../components/billing/StatTile'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { Alert } from '../../components/ui/Alert'
import { DataTable, LoadingState } from '../../components/ui/DataTable'
import { Field, Select } from '../../components/ui/Field'
import { useDataRefresh } from '../../context/DataRefreshContext'
import type { StatutoryPosition, TableBlock } from '../../types'

const figure = (value: number) => (value === 0 ? '—' : `${value < 0 ? '−' : ''}${money(Math.abs(value))}`)

/**
 * EPFO and ESIC by month: what the bills charged clients for them and what has been paid over to the authorities, the way the GST page shows GST. The payments are
 * recorded on each bill (open a bill, EPFO and ESIC). EPFO and ESIC are inside the bills' value and Revenue; once paid over they are a cost and lower the margin.
 */
export function StatutoryPage() {
  const { generation } = useDataRefresh()
  const navigate = useNavigate()
  const [fy, setFy] = useState<number | undefined>(undefined)
  const [position, setPosition] = useState<StatutoryPosition | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .statutoryPosition(fy)
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
        epfo_charged: figure(m.epfo_charged),
        esic_charged: figure(m.esic_charged),
        epfo_paid: figure(m.epfo_paid),
        esic_paid: figure(m.esic_paid),
        charged_less_paid: figure(m.net),
        running: m.future ? '' : figure(m.running_net),
      })),
    [position],
  )

  const owed: TableBlock = useMemo(
    () => ({
      filter_key: null,
      columns: [
        { key: 'bill_number', label: 'Bill no.', format: 'bill', align: 'left' },
        { key: 'bill_date', label: 'Bill date', format: 'text', align: 'left' },
        { key: 'client', label: 'Client', format: 'text', align: 'left' },
        { key: 'epfo', label: 'EPFO to pay', format: 'money', align: 'right' },
        { key: 'esic', label: 'ESIC to pay', format: 'money', align: 'right' },
      ],
      rows: (position?.oldest ?? []).map((bill) => ({
        code: bill.id,
        bill_code: bill.id,
        bill_number: bill.bill_number,
        bill_date: formatDay(bill.bill_date),
        bill_date_sort: bill.bill_date,
        client: bill.client ?? '',
        epfo: bill.epfo,
        esic: bill.esic,
      })),
      truncated: (position?.open.bills ?? 0) > (position?.oldest.length ?? 0),
    }),
    [position],
  )

  const totals = position?.totals
  const charged = (totals?.epfo_charged ?? 0) + (totals?.esic_charged ?? 0)
  const paid = (totals?.epfo_paid ?? 0) + (totals?.esic_paid ?? 0)
  const open = position?.open

  return (
    <section aria-label="EPFO and ESIC" className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">EPFO and ESIC</h2>
          <p className="mt-0.5 max-w-3xl text-sm text-[color:var(--color-text-muted)]">
            What the bills charged clients for EPFO and ESIC, and what has been paid over to the authorities, month by month. Payments are recorded on each bill (open a bill and use
            EPFO and ESIC) and go out of the bank on the day they were paid. EPFO and ESIC are inside the bills&apos; value and Revenue; once paid they are a cost and lower the margin. This page shows whether they have been
            paid. The challans and returns are made on the EPFO and ESIC portals.
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

      {error && (
        <Alert variant="error" onDismiss={() => setError('')}>
          {error}
        </Alert>
      )}

      {!position ? (
        <LoadingState />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Charged on bills" text={`₹ ${money(charged)}`} hint={`EPFO ₹ ${money(totals?.epfo_charged ?? 0)} · ESIC ₹ ${money(totals?.esic_charged ?? 0)}`} tone="" />
            <StatTile label="Recorded as paid" text={`₹ ${money(paid)}`} hint={`In ${position.fy_label}, by the day paid`} tone="text-positive" />
            <StatTile
              label="Still to pay, all bills"
              text={`₹ ${money((open?.epfo ?? 0) + (open?.esic ?? 0))}`}
              hint={open?.bills ? `${open.bills} bill${open.bills === 1 ? '' : 's'}, oldest ${open.oldest_bill_date ? formatDay(open.oldest_bill_date) : ''}` : 'Every bill is paid up'}
              tone={open?.bills ? 'text-warning' : ''}
            />
            <StatTile label="EPFO still to pay" text={`₹ ${money(open?.epfo ?? 0)}`} hint={`ESIC still to pay ₹ ${money(open?.esic ?? 0)}`} tone="" />
          </div>

          <DataTable
            columns={['month', 'epfo_charged', 'esic_charged', 'epfo_paid', 'esic_paid', 'charged_less_paid', 'running']}
            rows={rows}
            allColumns
            emptyMessage="No bills in this year."
          />
          <p className="text-xs text-[color:var(--color-text-muted)]">
            Charged is by the bill&apos;s date and paid is by the day it was paid, so a month can show more paid than charged when earlier bills are being paid. Running is
            charged less paid since April; Still to pay, all bills above is over every bill, whatever year it was raised in.
          </p>

          <div className="space-y-2">
            <h3 className="t-h3 text-[color:var(--color-text)]">Bills with EPFO or ESIC still to pay</h3>
            <ReportTable
              block={owed}
              exportName="epfo-esic-to-pay"
              onOpen={(id) => navigate(`/utility/billing/${id}`)}
              searchLabel="Search bill no. or client"
              defaultSort={{ key: 'bill_date', dir: 'asc' }}
              emptyMessage="Every bill's EPFO and ESIC is paid."
              pageSize={15}
            />
          </div>
        </>
      )}
    </section>
  )
}
