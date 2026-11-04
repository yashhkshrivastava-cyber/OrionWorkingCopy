import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { formatDay } from '../../components/billing/BillDocument'
import { CreditNoteDialog } from '../../components/billing/CreditNoteDialog'
import { StatTile } from '../../components/billing/StatTile'
import { Alert } from '../../components/ui/Alert'
import { DataTable, LoadingState } from '../../components/ui/DataTable'
import { Field, Select } from '../../components/ui/Field'
import { useDataRefresh } from '../../context/DataRefreshContext'
import type { CreditNote, CreditNoteList, CreditNoteStatus } from '../../types'

function Tile({ label, value, hint, tone = '' }: { label: string; value: string; hint?: string; tone?: string }) {
  return <StatTile label={label} text={value} hint={hint} tone={tone} />
}

const COLUMNS = ['credit_note', 'bill_number', 'client', 'kind', 'dated', 'amount', 'status', 'made_by', 'decided_by']
const STATUSES: CreditNoteStatus[] = ['Pending', 'Approved', 'Rejected', 'Withdrawn', 'Reversed']

/** Every credit note and write-off, with the ones waiting for a decision first in mind: open one to approve, refuse, withdraw or reverse it. */
export function CreditNotesPage() {
  const { generation } = useDataRefresh()
  const [list, setList] = useState<CreditNoteList | null>(null)
  const [status, setStatus] = useState('')
  const [fy, setFy] = useState<number | undefined>(undefined)
  const [open, setOpen] = useState<CreditNote | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    api
      .creditNotes({ status: status || undefined, fy })
      .then((found) => {
        setList(found)
        setError('')
      })
      .catch((e: Error) => setError(e.message))
  }, [status, fy])

  useEffect(load, [load, generation])

  const rows = useMemo(
    () =>
      (list?.rows ?? []).map((n) => ({
        id: n.id,
        credit_note: n.cn_number ?? 'Not numbered yet',
        bill_number: n.bill_number,
        client: n.client_name ?? n.party_name ?? '—',
        kind: n.kind,
        dated: formatDay(n.note_date),
        amount: n.total.toFixed(2),
        status: n.status,
        made_by: n.created_by_name ?? '—',
        decided_by: n.decided_by_name ?? '',
      })),
    [list],
  )

  const pick = (row: Record<string, unknown>) => setOpen(list?.rows.find((n) => n.id === row.id) ?? null)

  return (
    <section aria-label="Credit notes" className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">Credit notes</h2>
          <p className="mt-0.5 max-w-3xl text-sm text-[color:var(--color-text-muted)]">
            Credit notes and bad-debt write-offs against issued bills. Each is made on its bill (Billing, the bill, Issue credit note) and takes effect when someone
            other than its maker approves it, or an admin; a write-off is approved by an admin. Open one to decide it.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Field label="Status" className="w-40">
            <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="">All</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Financial year" className="w-40">
            <Select value={fy ?? ''} onChange={(e) => setFy(e.target.value ? Number(e.target.value) : undefined)} aria-label="Financial year">
              <option value="">All years</option>
              {(list?.years ?? []).map((y) => (
                <option key={y.fy_start_year} value={y.fy_start_year}>
                  {y.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </header>

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}

      {!list ? (
        <LoadingState />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile label="Waiting for a decision" value={String(list.pending)} tone={list.pending > 0 ? 'text-warning' : ''} hint="Pending credit notes" />
            <Tile label="Approved" value={`₹ ${money(list.totals.approved)}`} hint={`${list.totals.count} credit notes in this list`} />
            <Tile label="GST credited" value={`₹ ${money(list.totals.gst)}`} hint="Comes off the GST to pay" />
          </div>
          <DataTable
            columns={COLUMNS}
            rows={rows}
            allColumns
            filterable
            kinds={{ amount: 'number' }}
            emptyMessage="No credit notes yet. Make one on a bill in Billing."
            onRowClick={pick}
            rowHint="Open to approve, refuse, withdraw or reverse it"
          />
        </>
      )}

      <CreditNoteDialog
        note={open}
        onClose={() => setOpen(null)}
        onChanged={() => {
          load()
        }}
      />
    </section>
  )
}
