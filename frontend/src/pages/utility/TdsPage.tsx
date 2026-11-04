import { useCallback, useEffect, useMemo, useState } from 'react'
import { CircleCheck, FileDown } from 'lucide-react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { formatDay } from '../../components/billing/BillDocument'
import { downloadCsv } from '../../components/dashboard/csv'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { DataTable, LoadingState } from '../../components/ui/DataTable'
import { Field, Input, Select } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import type { TdsLedger, TdsRow } from '../../types'

function Tile({ label, value, hint, tone = '' }: { label: string; value: number | string; hint?: string; tone?: string }) {
  return <StatTile label={label} text={typeof value === 'number' ? `₹ ${money(value)}` : value} hint={hint} tone={tone} />
}

const COLUMNS = ['bill_number', 'client', 'received_on', 'quarter', 'section', 'rate_percent', 'tds_amount', 'form_26as', 'certificate']

/**
 * The TDS that clients held back from their payments, by financial year, for checking against each client's Form 26AS. A deduction is recorded
 * with the payment (Billing > a bill > Record payment); here it is ticked as found in the 26AS, which is what makes it a credit that can be claimed.
 */
export function TdsPage() {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const canWrite = Boolean(user?.can_billing_write)
  const [ledger, setLedger] = useState<TdsLedger | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [fy, setFy] = useState<number | undefined>(undefined)
  const [client, setClient] = useState('')
  const [quarter, setQuarter] = useState('')
  const [match, setMatch] = useState('all')
  // The clients to choose from are those of the unfiltered list: choosing one must not leave only that one to choose from.
  const [clientOptions, setClientOptions] = useState<{ client_code: string | null; client_name: string | null }[]>([])
  const [picked, setPicked] = useState<TdsRow | null>(null)
  const [ref, setRef] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api
      .tdsLedger({ fy, client_code: client || undefined, quarter: quarter || undefined, match })
      .then((found) => {
        setLedger(found)
        if (!client) setClientOptions(found.by_client)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [fy, client, quarter, match])

  useEffect(load, [load, generation])

  const rows = useMemo(
    () =>
      (ledger?.rows ?? []).map((row) => ({
        id: row.deduction_id,
        bill_number: row.bill_number,
        client: row.client_name ?? '—',
        received_on: formatDay(row.received_date),
        quarter: row.quarter ?? '',
        section: row.section,
        rate_percent: row.rate ?? '',
        tds_amount: row.amount.toFixed(2),
        form_26as: row.matched ? 'Found' : 'Not yet checked',
        certificate: row.certificate_ref ?? '',
      })),
    [ledger],
  )

  const open = (row: Record<string, unknown>) => {
    const found = ledger?.rows.find((r) => r.deduction_id === row.id)
    if (!found) return
    setPicked(found)
    setRef(found.certificate_ref ?? '')
    setError('')
  }

  const save = async (matched: boolean) => {
    if (!picked || busy) return
    setBusy(true)
    try {
      await api.tdsMatch(picked.deduction_id, matched, ref.trim())
      setPicked(null)
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const exportCsv = () => {
    if (!ledger) return
    downloadCsv(
      `tds-${ledger.rows[0]?.fy_label ?? 'all'}.csv`,
      ['Bill', 'Client', 'Received on', 'Quarter', 'Section', 'Rate %', 'TDS', 'In Form 26AS', 'Certificate / 26AS reference'],
      ledger.rows.map((r) => [r.bill_number, r.client_name, r.received_date, r.quarter, r.section, r.rate, r.amount, r.matched ? 'Yes' : 'No', r.certificate_ref]),
    )
  }

  const totals = ledger?.totals
  const clients = clientOptions

  return (
    <section aria-label="TDS" className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">TDS held back by clients</h2>
          <p className="mt-0.5 max-w-3xl text-sm text-[color:var(--color-text-muted)]">
            When a client pays a bill net of TDS, the deduction is recorded with the payment and the bill closes. Check each one against the
            client's Form 26AS and tick it here once it shows there: only then is the credit safe to claim in the income-tax return.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={exportCsv} disabled={!ledger || ledger.rows.length === 0}>
          <FileDown className="h-4 w-4" /> Export to CSV
        </Button>
      </header>

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="TDS held back" value={totals?.total ?? 0} hint={`${totals?.count ?? 0} deductions`} />
        <Tile label="Found in Form 26AS" value={totals?.matched ?? 0} tone="text-positive" />
        <Tile label="Still to check" value={totals?.unmatched ?? 0} tone={(totals?.unmatched ?? 0) > 0 ? 'text-warning' : ''} hint="Not yet seen in a 26AS" />
        <Tile
          label="By quarter"
          value={(ledger?.by_quarter ?? []).map((q) => `${q.quarter} ${money(q.total)}`).join(' · ') || '—'}
        />
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Financial year" className="w-40">
          <Select value={fy ?? ''} onChange={(e) => setFy(e.target.value ? Number(e.target.value) : undefined)} aria-label="Financial year">
            <option value="">All years</option>
            {(ledger?.years ?? []).map((y) => (
              <option key={y.fy_start_year} value={y.fy_start_year}>
                {y.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Client" className="w-56">
          <Select value={client} onChange={(e) => setClient(e.target.value)} aria-label="Client">
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c.client_code ?? ''} value={c.client_code ?? ''}>
                {c.client_name ?? 'No client'}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Quarter" className="w-32">
          <Select value={quarter} onChange={(e) => setQuarter(e.target.value)} aria-label="Quarter">
            <option value="">All</option>
            <option value="Q1">Q1 Apr–Jun</option>
            <option value="Q2">Q2 Jul–Sep</option>
            <option value="Q3">Q3 Oct–Dec</option>
            <option value="Q4">Q4 Jan–Mar</option>
          </Select>
        </Field>
        <Field label="Form 26AS" className="w-44">
          <Select value={match} onChange={(e) => setMatch(e.target.value)} aria-label="Form 26AS">
            <option value="all">All</option>
            <option value="unmatched">Still to check</option>
            <option value="matched">Found</option>
          </Select>
        </Field>
      </div>

      {loading && !ledger ? (
        <LoadingState />
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={rows}
          allColumns
          filterable
          kinds={{ tds_amount: 'number', rate_percent: 'number' }}
          emptyMessage="No TDS has been held back by a client yet. Record it with the payment on a bill."
          onRowClick={canWrite ? open : undefined}
          rowHint={canWrite ? 'Open to tick it as found in Form 26AS' : undefined}
        />
      )}
      {ledger?.truncated && <p className="text-xs text-[color:var(--color-text-muted)]">Only the newest {ledger.rows.length} deductions are shown. Narrow the year or the client.</p>}

      <Modal
        open={Boolean(picked)}
        title="Form 26AS check"
        onClose={() => setPicked(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPicked(null)}>
              Close
            </Button>
            {picked?.matched && (
              <Button variant="secondary" onClick={() => save(false)} loading={busy}>
                Take the tick off
              </Button>
            )}
            <Button onClick={() => save(true)} loading={busy}>
              <CircleCheck className="h-4 w-4" /> {picked?.matched ? 'Save the reference' : 'Found in Form 26AS'}
            </Button>
          </>
        }
      >
        {picked && (
          <div className="space-y-3 text-sm">
            <p className="text-[color:var(--color-text-muted)]">
              ₹ {money(picked.amount)} held back by {picked.client_name ?? 'the client'} under section {picked.section}
              {picked.rate ? ` at ${picked.rate}%` : ''}, paid on {formatDay(picked.received_date)} ({picked.fy_label}, {picked.quarter}) against bill {picked.bill_number}.
            </p>
            <Field label="Certificate or 26AS reference" hint="Optional: the Form 16A number, or the line in the 26AS.">
              <Input value={ref} onChange={(e) => setRef(e.target.value)} maxLength={120} />
            </Field>
            {picked.matched && picked.matched_by_name && <p className="text-xs text-[color:var(--color-text-faint)]">Ticked by {picked.matched_by_name}.</p>}
          </div>
        )}
      </Modal>
    </section>
  )
}
