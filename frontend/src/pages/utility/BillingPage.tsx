import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FilePlus2, Settings2 } from 'lucide-react'
import { api } from '../../api/client'
import { downloadCsv } from '../../components/dashboard/csv'
import { inr } from '../../components/dashboard/format'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { formatDay, formatMonth } from '../../components/billing/BillDocument'
import { BillTemplateModal } from '../../components/billing/BillTemplateModal'
import { BillFilters, NO_FILTER, type BillFilter } from '../../components/billing/BillFilters'
import { LumenBillList } from '../../components/billing/LumenBillList'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { SearchSelect } from '../../components/ui/SearchSelect'
import { useAuth } from '../../context/AuthContext'
import { useLumen } from '../../lumen/useLumen'
import type { BillCase, BillListRow, TableBlock } from '../../types'
import { AskAiButton } from '../../components/assistant/Launcher'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const lumen = useLumen()
  if (lumen) return <StatTile label={label} text={value} hint={hint} />
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
      <p className="text-xs font-medium text-[color:var(--color-text-muted)]">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-[color:var(--color-text)]">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-[color:var(--color-text-faint)]">{hint}</p>}
    </div>
  )
}

/** Every bill raised in the application: the register that lives in Excel today. */
export function BillingPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const lumen = useLumen()
  const canWrite = Boolean(user?.can_billing_write)
  const [years, setYears] = useState<{ id: string; label: string }[]>([])
  const [fy, setFy] = useState('')
  const [cases, setCases] = useState<BillCase[]>([])
  const [filter, setFilter] = useState<BillFilter>(NO_FILTER)
  const filtered = Boolean(filter.client || filter.caseCode || filter.month)
  /** Once someone picks a year themselves their choice stays; until then, finding a client, case or month looks in every year. */
  const [yearChosen, setYearChosen] = useState(false)
  const [bills, setBills] = useState<BillListRow[] | null>(null)
  const [error, setError] = useState('')
  const [showTemplate, setShowTemplate] = useState(false)
  const [nextNumber, setNextNumber] = useState('')

  useEffect(() => {
    api
      .billingYears()
      .then((r) => {
        setYears([{ id: 'all', label: 'All years' }, ...r.years])
        setFy((current) => current || r.years[0]?.id || '')
      })
      .catch((e: Error) => setError(e.message))
    api.billingCases().then((r) => setCases(r.cases)).catch(() => undefined) // only the choices of the filter boxes
    const today = new Date().toISOString().slice(0, 10)
    api.billingNextNumber(today).then((r) => setNextNumber(r.bill_number)).catch(() => undefined)
  }, [])

  const changeFilter = (next: BillFilter) => {
    setFilter(next)
    if (!yearChosen && (next.client || next.caseCode || next.month)) setFy('all')
  }

  useEffect(() => {
    if (!fy) return
    setBills(null)
    let live = true
    api
      .bills(fy === 'all' ? undefined : fy, undefined, { client_code: filter.client, case_code: filter.caseCode, month: filter.month })
      .then((r) => live && setBills(r.bills))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [fy, filter])

  const issued = useMemo(() => (bills ?? []).filter((b) => b.status === 'Issued'), [bills])
  const sum = (key: 'taxable_total' | 'cgst_amount' | 'sgst_amount' | 'grand_total') =>
    issued.reduce((total, bill) => total + bill[key], 0)
  const gstUnpaid = issued.filter((bill) => !bill.gst_paid).length
  const received = issued.reduce((total, bill) => total + bill.received_total, 0)
  const credited = issued.reduce((total, bill) => total + (bill.credited_amount ?? 0), 0)
  /** What is still to be received on a bill: what it was for, less what has been received and what credit notes took off. A cancelled bill is owed nothing. */
  const balance = (bill: BillListRow) => (bill.status === 'Issued' ? bill.grand_total - (bill.credited_amount ?? 0) - bill.received_total : 0)
  /** The client a bill belongs to, or the Tally ledger on bills raised before case tagging. */
  /** Yes, Part (some of the GST paid) or No; nothing for a cancelled bill. */
  const gstLabel = (bill: BillListRow) => (bill.status === 'Cancelled' ? '' : bill.gst_paid ? 'Yes' : bill.gst_paid_amount > 0 ? 'Part' : 'No')
  /** Yes, Part or No for EPFO or ESIC paid over; a dash where the bill charged none, and nothing for a cancelled bill. */
  const dueLabel = (charged: number, paid: number, bill: BillListRow) =>
    bill.status === 'Cancelled' ? '' : charged <= 0 ? '—' : paid >= charged - 0.004 ? 'Yes' : paid > 0 ? 'Part' : 'No'
  const clientOf = (bill: BillListRow) => bill.client_name ?? bill.legacy_client_ledger ?? ''

  const table: TableBlock = useMemo(
    () => ({
      filter_key: null,
      columns: [
        { key: 'bill_number', label: 'Bill no.', format: 'bill', align: 'left' },
        { key: 'bill_date', label: 'Date', format: 'text', align: 'left' },
        { key: 'case', label: 'Case', format: 'text', align: 'left' },
        { key: 'client', label: 'Client', format: 'text', align: 'left' },
        { key: 'month', label: 'For month', format: 'text', align: 'left' },
        { key: 'taxable_total', label: 'Taxable amt', format: 'money', align: 'right' },
        { key: 'cgst_amount', label: 'CGST', format: 'money', align: 'right' },
        { key: 'sgst_amount', label: 'SGST', format: 'money', align: 'right' },
        { key: 'grand_total', label: 'Grand total', format: 'money', align: 'right' },
        { key: 'received', label: 'Received', format: 'money', align: 'right' },
        { key: 'balance', label: 'To receive', format: 'money', align: 'right' },
        { key: 'gst_paid', label: 'GST paid', format: 'text', align: 'left' },
        { key: 'epfo_paid', label: 'EPFO paid', format: 'text', align: 'left' },
        { key: 'esic_paid', label: 'ESIC paid', format: 'text', align: 'left' },
        { key: 'status', label: 'Status', format: 'text', align: 'left' },
      ],
      rows: (bills ?? []).map((bill) => ({
        code: String(bill.id),
        bill_code: String(bill.id),
        bill_number: bill.bill_number,
        bill_date: formatDay(bill.bill_date),
        bill_date_sort: bill.bill_date,
        case: bill.case_name ?? 'Not tagged',
        client: clientOf(bill),
        gst_paid: gstLabel(bill),
        epfo_paid: dueLabel(bill.epf_amount, bill.epf_paid_amount, bill),
        esic_paid: dueLabel(bill.esic_amount, bill.esic_paid_amount, bill),
        month: formatMonth(bill.service_month),
        month_sort: bill.service_month,
        taxable_total: bill.taxable_total,
        cgst_amount: bill.cgst_amount,
        sgst_amount: bill.sgst_amount,
        grand_total: bill.grand_total,
        received: bill.received_total,
        balance: balance(bill),
        status: bill.status,
      })),
      truncated: (bills?.length ?? 0) >= 500,
      totals: {
        taxable_total: sum('taxable_total'),
        cgst_amount: sum('cgst_amount'),
        sgst_amount: sum('sgst_amount'),
        grand_total: sum('grand_total'),
        received,
        balance: sum('grand_total') - credited - received,
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bills],
  )

  // The Excel bills register's columns first, so it can still be pasted into it, then the tracking columns.
  const exportRegister = () =>
    downloadCsv(
      `bills-register-${fy}.csv`,
      ['SR NO', 'SITE', 'BILL NO', 'Taxable AMT', 'CGST', 'SGST', 'G TOTAL', 'MONTHS', 'BILL DATE', 'STATUS', 'CASE', 'CLIENT', 'GST PAID', 'RECEIVED', 'TO RECEIVE'],
      (bills ?? [])
        .slice()
        .reverse()
        .map((bill, index) => [
          index + 1,
          bill.location || clientOf(bill),
          bill.bill_number,
          bill.taxable_total,
          bill.cgst_amount,
          bill.sgst_amount,
          bill.grand_total,
          formatMonth(bill.service_month),
          formatDay(bill.bill_date),
          bill.status,
          bill.case_name ?? '',
          clientOf(bill),
          gstLabel(bill),
          bill.received_total,
          balance(bill),
        ]),
    )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">Bills</h2>
          <p className="text-sm text-[color:var(--color-text-muted)]">
            Raise tax invoices for your cases. Each one is numbered by financial year, tagged to its case and
            client, and keeps every version it has had.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AskAiButton prompt="Who owes us the most, and which cases still need to be billed this month?">Ask AI</AskAiButton>
          <Button variant="ghost" size="sm" onClick={() => setShowTemplate(true)}>
            <Settings2 className="h-4 w-4" /> Bill template
          </Button>
          {canWrite && (
            <Button onClick={() => navigate('/utility/billing/new')}>
              <FilePlus2 className="h-4 w-4" /> New bill
            </Button>
          )}
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Bills issued" value={String(issued.length)} hint={fy === 'all' || !fy ? 'All years' : `FY ${fy}-${String((Number(fy) + 1) % 100).padStart(2, '0')}`} />
        <Stat label="Taxable value" value={inr(sum('taxable_total'))} />
        <Stat
          label="GST"
          value={inr(sum('cgst_amount') + sum('sgst_amount'))}
          hint={gstUnpaid ? `CGST + SGST · not yet paid on ${gstUnpaid}` : 'CGST + SGST · paid on every bill'}
        />
        <Stat
          label="Billed incl. GST"
          value={inr(sum('grand_total'))}
          hint={`${inr(received)} received · ${inr(sum('grand_total') - credited - received)} to receive`}
        />
      </div>

      <section aria-label="Find bills" className="panel !p-4">
        <BillFilters cases={cases} value={filter} onChange={changeFilter} />
      </section>

      {lumen && (
        <section aria-label="Bills register" className="space-y-4">
          <header className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="t-h3">Bills register</h3>
            <div className="flex items-center gap-2">
              <div className="w-40">
                <SearchSelect value={fy} options={years} onChange={(value) => { setYearChosen(true); setFy(value ?? '') }} allowEmpty={false} />
              </div>
              <Button variant="secondary" size="sm" onClick={exportRegister} disabled={!bills?.length}>
                Export register
              </Button>
            </div>
          </header>
          {bills === null ? (
            <div className="shimmer h-40 rounded-2xl bg-muted" aria-busy="true" />
          ) : bills.length === 0 ? (
            <div className="panel px-6 py-12 text-center">
              <p className="font-display text-lg font-semibold">{filtered ? 'No bill matches that' : 'No bills in this financial year yet'}</p>
              <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
                {filtered ? 'Try another month, or clear the client and case. Every year is searched unless you chose one.' : canWrite ? `The first bill you raise will be numbered ${nextNumber || 'from 1'}.` : 'Bills raised by your team will appear here.'}
              </p>
            </div>
          ) : (
            <LumenBillList bills={bills} onOpen={(id) => navigate(`/utility/billing/${id}`)} />
          )}
        </section>
      )}

      {!lumen && (
      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--color-border)] px-4 py-3">
          <h3 className="t-h3 text-[color:var(--color-text)]">Bills register</h3>
          <div className="flex items-center gap-2">
            <div className="w-40">
              <SearchSelect value={fy} options={years} onChange={(value) => { setYearChosen(true); setFy(value ?? '') }} allowEmpty={false} />
            </div>
            <Button variant="secondary" size="sm" onClick={exportRegister} disabled={!bills?.length}>
              Export register
            </Button>
          </div>
        </header>
        <div className="py-3">
          {bills === null ? (
            <div className="shimmer mx-4 h-40 rounded-lg bg-muted" aria-busy="true" />
          ) : bills.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <p className="text-sm font-medium text-[color:var(--color-text)]">{filtered ? 'No bill matches that' : 'No bills in this financial year yet'}</p>
              <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
                {filtered
                  ? 'Try another month, or clear the client and case. Every year is searched unless you chose one.'
                  : canWrite
                    ? `The first bill you raise will be numbered ${nextNumber || 'from 1'}.`
                    : 'Bills raised by your team will appear here.'}
              </p>
            </div>
          ) : (
            <ReportTable
              block={table}
              exportName={`bills-${fy}`}
              onOpen={(id) => navigate(`/utility/billing/${id}`)}
              searchLabel="Search bill no., case, client or month"
              defaultSort={{ key: 'bill_number', dir: 'desc' }}
              emptyMessage="No bills."
              pageSize={25}
            />
          )}
        </div>
      </section>
      )}

      <BillTemplateModal open={showTemplate} canEdit={canWrite} onClose={() => setShowTemplate(false)} onSaved={() => undefined} />
    </div>
  )
}
