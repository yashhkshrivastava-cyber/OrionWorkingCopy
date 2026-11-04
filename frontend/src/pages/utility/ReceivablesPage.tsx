import { Fragment, useEffect, useMemo, useState } from 'react'
import { Bell, ChevronDown, ChevronRight, FileDown } from 'lucide-react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { formatDay, formatMonth } from '../../components/billing/BillDocument'
import { ShareModal } from '../../components/billing/ShareModal'
import { pdfPath, useLetterheadChoice } from '../../components/billing/letterheadChoice'
import { downloadCsv } from '../../components/dashboard/csv'
import { inr } from '../../components/dashboard/format'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox, Input } from '../../components/ui/Field'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import type { ReceivableClient, ReceivablesReport } from '../../types'
import { BillNumber } from '../../components/billing/BillNumber'
import { AskAiButton } from '../../components/assistant/Launcher'
import { LumenReceivables } from '../../components/billing/LumenReceivables'
import { useLumen } from '../../lumen/useLumen'

/** Older money is more worrying: the last two buckets are drawn in the warning colour. */
const BUCKET_TONE = ['', '', 'text-warning', 'text-negative']

function Tile({ label, value, share, tone = '' }: { label: string; value: number; share?: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
      <p className="text-xs font-medium text-[color:var(--color-text-muted)]">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${tone || 'text-[color:var(--color-text)]'}`}>{inr(value)}</p>
      {share !== undefined && (
        <p className="mt-0.5 text-[11px] text-[color:var(--color-text-faint)]">{Math.round(share * 100)}% of what is owed</p>
      )}
    </div>
  )
}

const cell = 'px-3 py-2'
const num = `${cell} text-right tabular-nums`

/** What each client owes, split by how old the bills are, with a reminder for each. */
export function ReceivablesPage() {
  const { user } = useAuth()
  const { generation } = useDataRefresh()
  const canWrite = Boolean(user?.can_billing_write)
  const [report, setReport] = useState<ReceivablesReport | null>(null)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [reminding, setReminding] = useState<ReceivableClient | null>(null)
  const [onLetterhead, setOnLetterhead] = useLetterheadChoice()
  const lumen = useLumen()

  const load = () =>
    api
      .receivables()
      .then(setReport)
      .catch((e: Error) => setError(e.message))

  useEffect(() => {
    load()
  }, [generation])

  const clients = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (report?.clients ?? []).filter((c) => !needle || c.client_name.toLowerCase().includes(needle))
  }, [report, search])

  const toggle = (code: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })

  const statement = async (client: ReceivableClient) => {
    setError('')
    try {
      await api.downloadPdf(
        pdfPath(`receivables/${encodeURIComponent(client.client_code)}/statement.pdf`, onLetterhead),
        `Statement ${client.client_name}.pdf`,
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const exportCsv = () => {
    if (!report) return
    downloadCsv(
      `outstanding-${report.as_of}.csv`,
      ['CLIENT', 'BILL NO', 'BILL DATE', 'FOR THE MONTH', 'CASE', 'BILL TOTAL', 'RECEIVED', 'TO RECEIVE', 'DAYS', 'AGE BUCKET', 'LAST REMINDER'],
      report.clients.flatMap((client) =>
        client.bills.map((bill) => [
          client.client_name,
          bill.bill_number,
          formatDay(bill.bill_date),
          formatMonth(bill.service_month),
          bill.case_name ?? '',
          bill.grand_total,
          bill.received,
          bill.balance,
          bill.days,
          report.bucket_labels[bill.bucket],
          bill.last_reminder ? formatDay(bill.last_reminder) : '',
        ]),
      ),
    )
  }

  const totals = report?.totals
  const labels = report?.bucket_labels ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="t-h2 text-[color:var(--color-text)]">Outstanding</h2>
          <p className="text-sm text-[color:var(--color-text-muted)]">
            What clients still owe on issued bills, by how long ago each bill was raised. Send a reminder with a
            statement of the unpaid bills.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <Checkbox label="Statements on the company letterhead" checked={onLetterhead} onChange={setOnLetterhead} />
          <Button variant="secondary" size="sm" onClick={exportCsv} disabled={!report?.clients.length}>
            Export list
          </Button>
        </div>
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {report && report.untagged_bills > 0 && (
        <Alert variant="info">
          {report.untagged_bills} issued {report.untagged_bills === 1 ? 'bill is' : 'bills are'} not tagged to a case, so
          there is no payment record for {report.untagged_bills === 1 ? 'it' : 'them'} and {report.untagged_bills === 1 ? 'it is' : 'they are'} left out
          here. Edit a bill to choose its case and it is counted from then on.
        </Alert>
      )}

      {lumen ? (
        report ? (
          <LumenReceivables report={report} canWrite={canWrite} onStatement={statement} onRemind={setReminding} />
        ) : (
          <div className="shimmer h-56 rounded-3xl bg-muted" aria-busy="true" />
        )
      ) : (
        <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile label="Total outstanding" value={totals?.total ?? 0} />
        {labels.map((label, index) => (
          <Tile
            key={label}
            label={label}
            value={totals?.buckets[index] ?? 0}
            share={totals && totals.total > 0 ? totals.buckets[index] / totals.total : undefined}
            tone={BUCKET_TONE[index]}
          />
        ))}
      </div>

      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--color-border)] px-4 py-3">
          <div>
            <h3 className="t-h3 text-[color:var(--color-text)]">By client</h3>
            {report && (
              <p className="text-xs text-[color:var(--color-text-muted)]">
                {totals?.clients ?? 0} {totals?.clients === 1 ? 'client' : 'clients'} · {totals?.bills ?? 0}{' '}
                {totals?.bills === 1 ? 'bill' : 'bills'} · as on {formatDay(report.as_of)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <AskAiButton prompt="Which clients have bills unpaid for more than 90 days, and what should I do about them?">Ask AI</AskAiButton>
            <div className="w-56">
              <Input aria-label="Search clients" placeholder="Search clients" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
          </div>
        </header>

        {report === null ? (
          <div className="shimmer m-4 h-40 rounded-lg bg-muted" aria-busy="true" />
        ) : report.clients.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-sm font-medium text-[color:var(--color-text)]">Nothing is outstanding</p>
            <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">Every issued bill has been received in full.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-[color:var(--color-text-muted)]">
                  <th className={`${cell} font-medium`}>Client</th>
                  {labels.map((label) => (
                    <th key={label} className={`${num} font-medium`}>
                      {label}
                    </th>
                  ))}
                  <th className={`${num} font-medium`}>Total</th>
                  <th className={`${cell} font-medium`}>Last reminder</th>
                  <th className={cell} />
                </tr>
              </thead>
              <tbody>
                {clients.map((client) => {
                  const expanded = open.has(client.client_code)
                  const Chevron = expanded ? ChevronDown : ChevronRight
                  return (
                    <Fragment key={client.client_code}>
                      <tr className="border-t border-[color:var(--color-border)] hover:bg-muted/50">
                        <td className={cell}>
                          <button
                            type="button"
                            onClick={() => toggle(client.client_code)}
                            aria-expanded={expanded}
                            className="flex items-center gap-1.5 text-left font-medium text-[color:var(--color-text)]"
                          >
                            <Chevron className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
                            <span>
                              {client.client_name}
                              <span className="block text-xs font-normal text-[color:var(--color-text-muted)]">
                                {client.bills.length} {client.bills.length === 1 ? 'bill' : 'bills'} · oldest {client.oldest_days} days
                              </span>
                            </span>
                          </button>
                        </td>
                        {client.buckets.map((value, index) => (
                          <td key={index} className={`${num} ${value > 0 ? BUCKET_TONE[index] : 'text-[color:var(--color-text-faint)]'}`}>
                            {value > 0 ? inr(value) : '–'}
                          </td>
                        ))}
                        <td className={`${num} font-semibold text-[color:var(--color-text)]`}>{inr(client.total)}</td>
                        <td className={`${cell} text-xs text-[color:var(--color-text-muted)]`}>
                          {client.last_reminder ? formatDay(client.last_reminder) : 'Never'}
                        </td>
                        <td className={`${cell} whitespace-nowrap text-right`}>
                          <Button variant="ghost" size="sm" onClick={() => statement(client)}>
                            <FileDown className="h-4 w-4" /> Statement
                          </Button>
                          {canWrite && (
                            <Button variant="secondary" size="sm" onClick={() => setReminding(client)}>
                              <Bell className="h-4 w-4" /> Remind
                            </Button>
                          )}
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="bg-muted/40">
                          <td colSpan={labels.length + 4} className="px-3 py-2">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="text-left text-[color:var(--color-text-muted)]">
                                  <th className="px-2 py-1 font-medium">Bill no.</th>
                                  <th className="px-2 py-1 font-medium">Bill date</th>
                                  <th className="px-2 py-1 font-medium">For the month</th>
                                  <th className="px-2 py-1 font-medium">Case</th>
                                  <th className="px-2 py-1 text-right font-medium">Bill total</th>
                                  <th className="px-2 py-1 text-right font-medium">Received</th>
                                  <th className="px-2 py-1 text-right font-medium">To receive</th>
                                  <th className="px-2 py-1 text-right font-medium">Days</th>
                                  <th className="px-2 py-1 font-medium">Reminded</th>
                                </tr>
                              </thead>
                              <tbody>
                                {client.bills.map((bill) => (
                                  <tr key={bill.id} className="border-t border-[color:var(--color-border)]">
                                    <td className="px-2 py-1.5">
                                      <BillNumber number={bill.bill_number} code={String(bill.id)} className="font-medium" />
                                    </td>
                                    <td className="px-2 py-1.5">{formatDay(bill.bill_date)}</td>
                                    <td className="px-2 py-1.5">{formatMonth(bill.service_month)}</td>
                                    <td className="px-2 py-1.5">{bill.case_name}</td>
                                    <td className="px-2 py-1.5 text-right tabular-nums">{money(bill.grand_total)}</td>
                                    <td className="px-2 py-1.5 text-right tabular-nums">{money(bill.received)}</td>
                                    <td className="px-2 py-1.5 text-right font-semibold tabular-nums">{money(bill.balance)}</td>
                                    <td className={`px-2 py-1.5 text-right tabular-nums ${BUCKET_TONE[bill.bucket]}`}>{bill.days}</td>
                                    <td className="px-2 py-1.5 text-[color:var(--color-text-muted)]">
                                      {bill.reminders
                                        ? `${bill.reminders}× · ${formatDay(bill.last_reminder)}`
                                        : 'Not yet'}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
                {clients.length === 0 && (
                  <tr>
                    <td colSpan={labels.length + 4} className="px-4 py-8 text-center text-sm text-[color:var(--color-text-muted)]">
                      No client matches that search.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
        </>
      )}

      {reminding && (
        <ShareModal
          open
          title={`Remind ${reminding.client_name}`}
          target={`receivables/${encodeURIComponent(reminding.client_code)}`}
          pdfPath={`receivables/${encodeURIComponent(reminding.client_code)}/statement.pdf`}
          pdfName={`Statement ${reminding.client_name}.pdf`}
          letterhead={onLetterhead}
          onClose={() => setReminding(null)}
          onSent={load}
        />
      )}
    </div>
  )
}
